"""Update the existing Oracle ARM64 Compose service by GHCR digest, with health check and rollback.

Python standard library only: CD streams this file to the VM over SSH stdin.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import urllib.request

REPOSITORY = 'ghcr.io/loanhviet/crop-mapping'
PROJECT = 'crop-mapping-oracle'
COMPOSE_FILES = ('compose.production.yaml', 'compose.oracle.yaml')
ARCH = 'arm64'
# Refuse to pull when the shared disk is low: a full disk would also take down OpenDubber.
MIN_FREE_BYTES = 5 * 1024**3
IMAGE = re.compile(re.escape(REPOSITORY) + r'@sha256:[0-9a-f]{64}\Z')


def atomic_write(path, content):
    fd, name = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class Deployment:
    def __init__(self, directory, image, revision, compose_sha, checkpoint_sha):
        self.root = directory.resolve()
        self.envfile = self.root / '.env.oracle'
        self.composefiles = [self.root / name for name in COMPOSE_FILES]
        self.port = None
        self.image, self.revision = image, revision
        self.compose_sha, self.checkpoint_sha = compose_sha, checkpoint_sha
        self.state = self.root / '.deployment'
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith('CROP_')}

    def run(self, *args):
        return subprocess.run(['sudo', '-n', 'docker', *args], cwd=self.root,
                              env=self.environment, check=True, text=True,
                              stdout=subprocess.PIPE).stdout.strip()

    def compose(self, override, *args):
        files = [arg for path in self.composefiles for arg in ('-f', str(path))]
        return self.run('compose', '--project-directory', str(self.root), '-p', PROJECT,
                        '--env-file', str(self.envfile), '--env-file', str(override), *files, *args)

    def container(self, override):
        ids = self.compose(override, 'ps', '--all', '-q', 'crop-map').split()
        if len(ids) != 1:
            raise RuntimeError('Expected exactly one existing crop-map container; refusing bootstrap')
        return json.loads(self.run('inspect', ids[0]))[0]

    def image_info(self, image):
        return json.loads(self.run('image', 'inspect', image))[0]

    def health(self):
        with urllib.request.urlopen(f'http://127.0.0.1:{self.port}/api/health', timeout=10) as response:
            return json.load(response)

    def verify(self, override, image, checkpoint, mounts):
        container = self.container(override)
        if container['Image'] != self.image_info(image)['Id']:
            raise RuntimeError('Running image differs from requested digest')
        if container['State'].get('Health', {}).get('Status') != 'healthy':
            raise RuntimeError('Container is not healthy')
        if self.mounts(container) != mounts:
            raise RuntimeError('Mount identities changed')
        health = self.health()
        if (health.get('status'), health.get('model'), health.get('device'), health.get('checkpoint_sha256')) != ('ok', 'TSViT', 'cpu', checkpoint):
            raise RuntimeError('API model/checkpoint verification failed')

    @staticmethod
    def free_bytes(path):
        # The Docker root is not traversable by the SSH user; statvfs of its parent is the same filesystem in practice.
        target = Path(path)
        return shutil.disk_usage(target if os.access(target, os.X_OK) else target.parent).free

    @staticmethod
    def mounts(container):
        return sorted((m['Destination'], m['Type'], m.get('Name', m['Source']), m['RW'])
                      for m in container['Mounts'])

    def up(self, override):
        self.compose(override, 'up', '-d', '--no-build', '--pull', 'never', '--wait',
                     '--wait-timeout', '180', 'crop-map')

    def execute(self):
        if not IMAGE.fullmatch(self.image):
            raise ValueError('A pinned crop-mapping GHCR digest is required')
        # Workflow side: cat compose.production.yaml compose.oracle.yaml | sha256sum
        if hashlib.sha256(b''.join(p.read_bytes() for p in self.composefiles)).hexdigest() != self.compose_sha:
            raise RuntimeError('Remote Compose differs from reviewed workflow revision; reconcile it first')
        self.state.mkdir(mode=0o700, exist_ok=True)
        with (self.state / 'lock').open('w') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise RuntimeError('Another deployment holds .deployment/lock; refusing to overlap') from None
            original = self.envfile.read_bytes()
            with tempfile.TemporaryDirectory(prefix='transaction-', dir=self.state) as temp:
                override = Path(temp) / 'image.env'
                atomic_write(override, f'CROP_IMAGE={self.image}\n'.encode())
                config = json.loads(self.compose(override, 'config', '--format', 'json'))
                service = config['services']['crop-map']
                binds = {v['target']: v for v in service['volumes'] if v['type'] == 'bind'}
                results = [v for v in service['volumes'] if v['target'] == '/app/results']
                if set(binds) != {'/app/data', '/app/weights'} or not all(v.get('read_only') for v in binds.values()):
                    raise RuntimeError('Expected read-only imagery and weights binds only')
                # Source compose hash pins create_host_path:false even when Compose omits false JSON fields.
                if not all(Path(v['source']).is_dir() for v in binds.values()):
                    raise RuntimeError('Expected existing host imagery and weights directories')
                if len(results) != 1 or results[0]['type'] != 'volume':
                    raise RuntimeError('Expected persistent results volume')
                volume_name = config['volumes'][results[0]['source']]['name']
                current = self.container(override)
                mounts = self.mounts(current)
                expected = sorted([(t, 'bind', v['source'], False) for t, v in binds.items()]
                                  + [('/app/results', 'volume', volume_name, True)])
                if mounts != expected:
                    raise RuntimeError('Running mounts differ from Compose; refusing to replace persistent identities')
                self.port = str(service['ports'][0]['published'])
                ports = current['NetworkSettings']['Ports'].get('8000/tcp', [])
                if len(service['ports']) != 1 or service['ports'][0].get('host_ip') != '127.0.0.1' or ports != [{'HostIp': '127.0.0.1', 'HostPort': self.port}]:
                    raise RuntimeError('Expected the existing loopback-only port binding')
                digests = [d for d in self.image_info(current['Image']).get('RepoDigests', []) if IMAGE.fullmatch(d)]
                if not digests:
                    raise RuntimeError('Current image has no registry digest for rollback')
                previous = current['Config']['Image'] if current['Config']['Image'] in digests else digests[0]
                old_checkpoint = self.health().get('checkpoint_sha256', '')
                if not re.fullmatch('[0-9a-f]{64}', old_checkpoint):
                    raise RuntimeError('Previous checkpoint identity unavailable')
                self.verify(override, previous, old_checkpoint, mounts)
                docker_root = self.run('info', '--format', '{{.DockerRootDir}}')
                if self.free_bytes(docker_root) < MIN_FREE_BYTES:
                    raise RuntimeError(f'Less than {MIN_FREE_BYTES >> 30} GiB free for {docker_root}; refusing to pull on the shared host')
                # Pull before changing any running container; previous image remains cached.
                # Explicit pull: the OCI overlay sets pull_policy: never so `up` never pulls implicitly.
                self.run('pull', self.image)
                candidate = self.image_info(self.image)
                if candidate['Architecture'] != ARCH or candidate['Os'] != 'linux' or candidate['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != self.revision:
                    raise RuntimeError('Candidate platform/source revision mismatch')
                if previous == self.image:
                    self.verify(override, self.image, self.checkpoint_sha, mounts)
                atomic_write(self.state / 'pending.json', json.dumps(dict(previous=previous, candidate=self.image, checkpoint=old_checkpoint)).encode())
                try:
                    if previous != self.image:
                        self.up(override)
                    self.verify(override, self.image, self.checkpoint_sha, mounts)
                    lines = [line for line in original.decode().splitlines() if not re.match(r'^\s*(?:export\s+)?CROP_IMAGE\s*=', line)]
                    atomic_write(self.envfile, ('\n'.join(lines) + f'\nCROP_IMAGE={self.image}\n').encode())
                    atomic_write(self.state / 'last-success.json', json.dumps(dict(image=self.image, previous=previous, checkpoint=self.checkpoint_sha)).encode())
                except Exception:
                    # Restore before printing: if the SSH client is gone, stdout is a broken pipe.
                    atomic_write(override, f'CROP_IMAGE={previous}\n'.encode())
                    try:
                        self.up(override)
                        self.verify(override, previous, old_checkpoint, mounts)
                        atomic_write(self.envfile, original)
                    except Exception as rollback_error:
                        raise RuntimeError('ROLLBACK FAILED; inspect .deployment/pending.json and service health') from rollback_error
                    print('Deployment verification failed; previous image restored and verified', flush=True)
                    raise
                self.state.joinpath('pending.json').unlink()
                print(f'Deployment healthy and verified: {self.image}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    for name in ['image', 'revision', 'compose-sha', 'checkpoint-sha']:
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise RuntimeError(f'Deployment interrupted by signal {signum}')
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, interrupted)
    Deployment(**vars(args)).execute()


if __name__ == '__main__':
    main()
