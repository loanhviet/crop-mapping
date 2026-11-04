"""OCI isolation and fail-closed model startup regressions."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_oracle_overlay_keeps_shared_host_isolated():
    if shutil.which('docker') is None:
        pytest.skip('Docker Compose CLI is not installed')
    environment = {k: v for k, v in os.environ.items() if not k.startswith('CROP_')}
    environment.update(CROP_RESULTS_VOLUME='existing-crop-results', CROP_BIND='0.0.0.0',
                       CROP_DEVICE='cuda', CROP_PORT='18081')
    result = subprocess.run(
        ['docker', 'compose', '--env-file', os.devnull, '-f', 'compose.production.yaml',
         '-f', 'compose.oracle.yaml', 'config', '--format', 'json'],
        cwd=ROOT, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    assert config['name'] == 'crop-mapping-oracle'
    assert set(config['services']) == {'crop-map'}
    service = config['services']['crop-map']
    assert service['build']['target'] == 'runtime'
    assert service['pull_policy'] == 'never'
    assert len(service['ports']) == 1
    assert service['ports'][0]['host_ip'] == '127.0.0.1'
    assert int(service['ports'][0]['published']) == 18081
    assert service['environment']['CROP_DEVICE'] == 'cpu'
    assert service['restart'] == 'unless-stopped'
    assert float(service['cpus']) == 2 and int(service['mem_limit']) == 2 * 1024**3
    mounts = {v['target']: v for v in service['volumes']}
    assert mounts['/app/data']['read_only'] and mounts['/app/weights']['read_only']
    assert config['volumes']['results']['name'] == 'existing-crop-results'


@pytest.mark.parametrize('problem', ['missing', 'corrupt', 'config'])
def test_engine_rejects_invalid_assets_before_deserialization(tmp_path, monkeypatch, problem):
    import inference
    monkeypatch.setattr(inference, 'WEIGHTS', tmp_path)
    monkeypatch.setattr(inference, 'ROOT', tmp_path)
    (tmp_path / 'assets').mkdir()
    trusted = b'trusted checkpoint'
    config = b'MODEL: trusted'
    manifest = dict(filename='best.pth', bytes=len(trusted),
                    sha256=hashlib.sha256(trusted).hexdigest(),
                    config_sha256=hashlib.sha256(config).hexdigest())
    (tmp_path / 'assets/model-manifest.json').write_text(json.dumps(manifest))
    if problem != 'missing':
        if problem == 'corrupt':
            (tmp_path / 'best.pth').write_bytes(b'corrupt checkpoint')
        else:
            (tmp_path / 'best.pth').write_bytes(trusted)
            (tmp_path / 'config.yaml').write_text('MODEL: invalid')
    with patch.object(inference.torch, 'load') as load:
        with pytest.raises(RuntimeError, match='Model asset verification failed'):
            inference.Engine()
        load.assert_not_called()
