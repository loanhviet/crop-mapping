"""Update the existing EC2 Compose service by digest; Python standard library only."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import urllib.request

REPOSITORY = 'loanhviet070105/crop-mapping'
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
        self.envfile = self.root / '.env.production'
        self.composefile = self.root / 'compose.production.yaml'
        self.image, self.revision = image, revision
        self.compose_sha, self.checkpoint_sha = compose_sha, checkpoint_sha
        self.state = self.root / '.deployment'
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith('CROP_')}

    def run(self, *args):
        return subprocess.run(['sudo', '-n', 'docker', *args], cwd=self.root,
                              env=self.environment, check=True, text=True,
                              stdout=subprocess.PIPE).stdout.strip()

    def compose(self, override, *args):
        return self.run('compose', '--project-directory', str(self.root), '-p', 'crop-mapping-production',
                        '--env-file', str(self.envfile), '--env-file', str(override),
                        '-f', str(self.composefile), *args)

    def container(self, override):
        ids = self.compose(override, 'ps', '--all', '-q', 'crop-map').split()
        if len(ids) != 1:
            raise RuntimeError('Expected exactly one existing crop-map container; refusing bootstrap')
        return json.loads(self.run('inspect', ids[0]))[0]

    def image_info(self, image):
        return json.loads(self.run('image', 'inspect', image))[0]

    def health(self):
        with urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=10) as response:
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
    def mounts(container):
        return sorted((m['Destination'], m['Type'], m.get('Name', m['Source']), m['RW'])
                      for m in container['Mounts'])

    def up(self, override):
        self.compose(override, 'up', '-d', '--no-build', '--pull', 'never', '--wait',
                     '--wait-timeout', '180', 'crop-map')

    def execute(self):
        if not IMAGE.fullmatch(self.image):
            raise ValueError('A pinned crop-mapping Docker Hub digest is required')
        if hashlib.sha256(self.composefile.read_bytes()).hexdigest() != self.compose_sha:
            raise RuntimeError('Remote Compose differs from reviewed workflow revision; reconcile it first')
        self.state.mkdir(mode=0o700, exist_ok=True)
        with (self.state / 'lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            original = self.envfile.read_bytes()
            with tempfile.TemporaryDirectory(prefix='transaction-', dir=self.state) as temp:
                override = Path(temp) / 'image.env'
                atomic_write(override, f'CROP_IMAGE={self.image}\n'.encode())
                config = json.loads(self.compose(override, 'config', '--format', 'json'))
                service = config['services']['crop-map']
                binds = [v for v in service['volumes'] if v['type'] == 'bind']
                results = [v for v in service['volumes'] if v['target'] == '/app/results']
                if len(binds) != 1 or binds[0]['target'] != '/app/data' or not binds[0]['read_only']:
                    raise RuntimeError('Expected the existing read-only imagery bind only')
                # Source compose hash pins create_host_path:false even when Compose v2 omits false JSON fields.
                if binds[0]['source'] != '/home/ubuntu/crop-map/data' or not Path(binds[0]['source']).is_dir():
                    raise RuntimeError('Expected existing EC2 imagery directory')
                if len(results) != 1 or results[0]['type'] != 'volume':
                    raise RuntimeError('Expected persistent results volume')
                volume_name = config['volumes'][results[0]['source']]['name']
                current = self.container(override)
                mounts = self.mounts(current)
                if ('/app/data', 'bind', binds[0]['source'], False) not in mounts or ('/app/results', 'volume', volume_name, True) not in mounts or len(mounts) != 2:
                    raise RuntimeError('Running mounts differ from Compose; refusing to replace persistent identities')
                ports = current['NetworkSettings']['Ports'].get('8000/tcp', [])
                if ports != [{'HostIp': '127.0.0.1', 'HostPort': '8000'}] or service['ports'][0].get('host_ip') != '127.0.0.1' or str(service['ports'][0]['published']) != '8000':
                    raise RuntimeError('Expected existing localhost:8000 binding')
                digests = [d for d in self.image_info(current['Image']).get('RepoDigests', []) if IMAGE.fullmatch(d)]
                if not digests:
                    raise RuntimeError('Current image has no registry digest for rollback')
                previous = current['Config']['Image'] if current['Config']['Image'] in digests else digests[0]
                old_checkpoint = self.health().get('checkpoint_sha256', '')
                if not re.fullmatch('[0-9a-f]{64}', old_checkpoint):
                    raise RuntimeError('Previous checkpoint identity unavailable')
                self.verify(override, previous, old_checkpoint, mounts)
                # Pull before changing any running container; previous image remains cached.
                self.compose(override, 'pull', 'crop-map')
                candidate = self.image_info(self.image)
                if candidate['Architecture'] != 'amd64' or candidate['Os'] != 'linux' or candidate['Config'].get('Labels', {}).get('org.opencontainers.image.revision') != self.revision:
                    raise RuntimeError('Candidate platform/source revision mismatch')
                atomic_write(self.state / 'pending.json', json.dumps(dict(previous=previous, candidate=self.image, checkpoint=old_checkpoint)).encode())
                try:
                    self.up(override)
                    self.verify(override, self.image, self.checkpoint_sha, mounts)
                    lines = [line for line in original.decode().splitlines() if not re.match(r'^\s*(?:export\s+)?CROP_IMAGE\s*=', line)]
                    atomic_write(self.envfile, ('\n'.join(lines) + f'\nCROP_IMAGE={self.image}\n').encode())
                    atomic_write(self.state / 'last-success.json', json.dumps(dict(image=self.image, previous=previous, checkpoint=self.checkpoint_sha)).encode())
                except Exception:
                    print('Deployment verification failed; restoring previous digest', flush=True)
                    atomic_write(override, f'CROP_IMAGE={previous}\n'.encode())
                    try:
                        self.up(override)
                        self.verify(override, previous, old_checkpoint, mounts)
                        atomic_write(self.envfile, original)
                    except Exception as rollback_error:
                        raise RuntimeError('ROLLBACK FAILED; inspect .deployment/pending.json and service health') from rollback_error
                    print('Previous image restored and verified', flush=True)
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
