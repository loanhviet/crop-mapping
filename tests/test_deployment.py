"""Exercise deployment transactions without SSH, Docker mutation or external assets."""
import hashlib
import json
from pathlib import Path

import pytest

from deployment.deploy import Deployment, REPOSITORY

OLD = REPOSITORY + '@sha256:' + 'a' * 64
NEW = REPOSITORY + '@sha256:' + 'b' * 64
OLD_SHA = 'c' * 64
NEW_SHA = 'd' * 64
REVISION = 'e' * 40
DATA = '/home/ubuntu/crop-mapping/data'
WEIGHTS = '/home/ubuntu/crop-mapping/weights'
PORT = '18080'


class FakeDeployment(Deployment):
    def __init__(self, root):
        compose = b''.join((root / name).read_bytes() for name in ('compose.production.yaml', 'compose.oracle.yaml'))
        super().__init__(root, NEW, REVISION, hashlib.sha256(compose).hexdigest(), NEW_SHA)
        self.current = OLD
        self.up_images = []
        self.fail_candidate = False
        self.fail_rollback = False
        self.volume = 'actual-results'
        self.arch = 'arm64'
        self.running_volume = 'actual-results'
        self.pulled = []

        self.free = 50 * 1024**3

    def run(self, *args):
        if args[:2] == ('info', '--format'):
            return '/var/lib/docker'
        assert args[0] == 'pull' and len(args) == 2, 'only info and explicit image pulls reach Docker in tests'
        self.pulled.append(args[1])
        return ''

    def free_bytes(self, path):
        return self.free

    def compose(self, override, *args):
        if args[0] == 'config':
            return json.dumps({'services': {'crop-map': {
                'volumes': [{'type': 'bind', 'target': '/app/data', 'source': DATA, 'read_only': True},
                            {'type': 'bind', 'target': '/app/weights', 'source': WEIGHTS, 'read_only': True},
                            {'type': 'volume', 'target': '/app/results', 'source': 'results'}],
                'ports': [{'host_ip': '127.0.0.1', 'published': PORT}]}},
                'volumes': {'results': {'name': self.volume}}})
        raise AssertionError(f'unexpected compose call {args}')

    def container(self, override):
        return {'Image': self.current, 'Config': {'Image': self.current},
                'State': {'Health': {'Status': 'healthy'}},
                'Mounts': [{'Destination': '/app/data', 'Type': 'bind', 'Source': DATA, 'RW': False},
                           {'Destination': '/app/weights', 'Type': 'bind', 'Source': WEIGHTS, 'RW': False},
                           {'Destination': '/app/results', 'Type': 'volume', 'Name': self.running_volume, 'Source': '/volume', 'RW': True}],
                'NetworkSettings': {'Ports': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': PORT}]}}}

    def image_info(self, image):
        return {'Id': image, 'RepoDigests': [image], 'Architecture': self.arch, 'Os': 'linux',
                'Config': {'Labels': {'org.opencontainers.image.revision': REVISION}}}

    def health(self):
        checkpoint = NEW_SHA if self.current == NEW else OLD_SHA
        if self.current == NEW and self.fail_candidate:
            checkpoint = '0' * 64
        return dict(status='ok', model='TSViT', device='cpu', checkpoint_sha256=checkpoint)

    def up(self, override):
        image = override.read_text().strip().split('=', 1)[1]
        self.up_images.append(image)
        if image == OLD and self.fail_rollback:
            raise RuntimeError('simulated rollback failure')
        self.current = image


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    (tmp_path / 'compose.production.yaml').write_text('reviewed compose fixture')
    (tmp_path / 'compose.oracle.yaml').write_text('reviewed oracle overlay fixture')
    (tmp_path / '.env.oracle').write_text(f'CROP_IMAGE={OLD}\nCROP_RESULTS_VOLUME=actual-results\n')
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, 'is_dir', lambda p: str(p) in (DATA, WEIGHTS) or original_is_dir(p))
    return FakeDeployment(tmp_path)


def test_success_and_repeat_preserve_volume_and_pin_config(deploy):
    deploy.execute()
    deploy.execute()
    assert deploy.current == NEW and deploy.pulled == [NEW, NEW]
    assert 'CROP_RESULTS_VOLUME=actual-results' in deploy.envfile.read_text()
    assert deploy.envfile.read_text().count('CROP_IMAGE=') == 1
    assert NEW in deploy.envfile.read_text()
    assert not (deploy.state / 'pending.json').exists()


def test_wrong_checkpoint_rolls_back_and_fails_job(deploy):
    original = deploy.envfile.read_bytes()
    deploy.fail_candidate = True
    with pytest.raises(RuntimeError, match='checkpoint verification failed'):
        deploy.execute()
    assert deploy.up_images == [NEW, OLD]
    assert deploy.current == OLD and deploy.envfile.read_bytes() == original
    assert json.loads((deploy.state / 'pending.json').read_text())['previous'] == OLD


def test_rollback_failure_retains_recovery_identity(deploy):
    deploy.fail_candidate = deploy.fail_rollback = True
    with pytest.raises(RuntimeError, match='ROLLBACK FAILED'):
        deploy.execute()
    assert json.loads((deploy.state / 'pending.json').read_text())['previous'] == OLD


def test_volume_mismatch_stops_before_update(deploy):
    deploy.volume = 'wrong-new-volume'
    with pytest.raises(RuntimeError, match='persistent identities'):
        deploy.execute()
    assert deploy.up_images == []


def test_compose_drift_stops_before_update(deploy):
    deploy.composefiles[1].write_text('unreviewed')
    with pytest.raises(RuntimeError, match='differs'):
        deploy.execute()
    assert deploy.up_images == []


def test_mutable_tag_is_rejected_before_any_update(deploy):
    deploy.image = REPOSITORY + ':latest'
    with pytest.raises(ValueError, match='digest is required'):
        deploy.execute()
    assert deploy.up_images == []


def test_partial_update_timeout_restores_previous_image(deploy, monkeypatch):
    original_up = deploy.up
    def failing_up(override):
        original_up(override)
        if deploy.current == NEW:
            raise RuntimeError('simulated health timeout')
    monkeypatch.setattr(deploy, 'up', failing_up)
    with pytest.raises(RuntimeError, match='health timeout'):
        deploy.execute()
    assert deploy.up_images == [NEW, OLD] and deploy.current == OLD


def test_redeploying_running_digest_is_idempotent(deploy):
    deploy.current = deploy.image
    deploy.health = lambda: dict(status='ok', model='TSViT', device='cpu', checkpoint_sha256=NEW_SHA)
    deploy.envfile.write_text(f'CROP_IMAGE={NEW}\nCROP_RESULTS_VOLUME=actual-results\nCROP_THREADS=2\n')
    deploy.execute()
    deploy.execute()
    assert deploy.envfile == deploy.root / '.env.oracle'
    assert deploy.up_images == []
    text = deploy.envfile.read_text()
    assert 'CROP_THREADS=2' in text and text.count('CROP_IMAGE=') == 1


def test_amd64_candidate_is_rejected_before_update(deploy):
    deploy.arch = 'amd64'
    with pytest.raises(RuntimeError, match='platform'):
        deploy.execute()
    assert deploy.up_images == []


def test_weights_mount_must_be_read_only(deploy):
    original = deploy.compose
    def writable(override, *args):
        config = json.loads(original(override, *args))
        config['services']['crop-map']['volumes'][1]['read_only'] = False
        return json.dumps(config)
    deploy.compose = writable
    with pytest.raises(RuntimeError, match='read-only'):
        deploy.execute()
    assert deploy.up_images == []


def test_low_disk_stops_before_pull(deploy):
    deploy.free = 1024**3
    with pytest.raises(RuntimeError, match='GiB free'):
        deploy.execute()
    assert deploy.pulled == [] and deploy.up_images == []


def test_rollback_still_runs_when_ssh_output_is_gone(deploy, monkeypatch):
    def broken_print(*args, **kwargs):
        raise BrokenPipeError
    monkeypatch.setattr('builtins.print', broken_print)
    deploy.fail_candidate = True
    with pytest.raises(BrokenPipeError):
        deploy.execute()
    assert deploy.up_images == [NEW, OLD] and deploy.current == OLD


def test_overlapping_deployment_is_refused(deploy):
    import fcntl
    deploy.state.mkdir()
    with (deploy.state / 'lock').open('w') as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        with pytest.raises(RuntimeError, match='overlap'):
            deploy.execute()
    assert deploy.up_images == []
