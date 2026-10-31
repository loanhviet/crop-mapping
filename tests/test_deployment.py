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
DATA = '/home/ubuntu/crop-map/data'


class FakeDeployment(Deployment):
    def __init__(self, root):
        super().__init__(root, NEW, REVISION,
                         hashlib.sha256((root / 'compose.production.yaml').read_bytes()).hexdigest(), NEW_SHA)
        self.current = OLD
        self.up_images = []
        self.fail_candidate = False
        self.fail_rollback = False
        self.volume = 'actual-results'
        self.running_volume = 'actual-results'

    def compose(self, override, *args):
        if args[0] == 'config':
            return json.dumps({'services': {'crop-map': {
                'volumes': [{'type': 'bind', 'target': '/app/data', 'source': DATA, 'read_only': True},
                            {'type': 'volume', 'target': '/app/results', 'source': 'results'}],
                'ports': [{'host_ip': '127.0.0.1', 'published': '8000'}]}},
                'volumes': {'results': {'name': self.volume}}})
        assert args == ('pull', 'crop-map')
        return ''

    def container(self, override):
        return {'Image': self.current, 'Config': {'Image': self.current},
                'State': {'Health': {'Status': 'healthy'}},
                'Mounts': [{'Destination': '/app/data', 'Type': 'bind', 'Source': DATA, 'RW': False},
                           {'Destination': '/app/results', 'Type': 'volume', 'Name': self.running_volume, 'Source': '/volume', 'RW': True}],
                'NetworkSettings': {'Ports': {'8000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '8000'}]}}}

    def image_info(self, image):
        return {'Id': image, 'RepoDigests': [image], 'Architecture': 'amd64', 'Os': 'linux',
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
    (tmp_path / '.env').write_text(f'CROP_IMAGE={OLD}\nCROP_RESULTS_VOLUME=actual-results\n')
    original_is_dir = Path.is_dir
    monkeypatch.setattr(Path, 'is_dir', lambda p: str(p) == DATA or original_is_dir(p))
    return FakeDeployment(tmp_path)


def test_success_and_repeat_preserve_volume_and_pin_config(deploy):
    deploy.execute()
    deploy.execute()
    assert deploy.current == NEW
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
    deploy.composefile.write_text('unreviewed')
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


def test_existing_env_and_verified_ec2_digest_are_idempotent(deploy):
    current = REPOSITORY + '@sha256:e4001dc8787c610981c08e1cd52bd14a9afd5e8606dc6aaacf9eaa56b6945d71'
    checkpoint = '92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733'
    deploy.current = deploy.image = current
    deploy.volume = deploy.running_volume = 'crop-mapping-results'
    deploy.checkpoint_sha = checkpoint
    deploy.health = lambda: dict(status='ok', model='TSViT', device='cpu', checkpoint_sha256=checkpoint)
    deploy.envfile.write_text(f'CROP_IMAGE={current}\nCROP_RESULTS_VOLUME=crop-mapping-results\nCROP_THREADS=2\n')
    deploy.execute()
    deploy.execute()
    assert deploy.envfile == deploy.root / '.env'
    assert not (deploy.root / '.env.production').exists()
    assert deploy.current == current and deploy.up_images == []
    assert 'CROP_RESULTS_VOLUME=crop-mapping-results' in deploy.envfile.read_text()
    assert 'CROP_THREADS=2' in deploy.envfile.read_text()
    assert deploy.envfile.read_text().count('CROP_IMAGE=') == 1
