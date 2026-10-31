"""Release provisioning rejects substitutions and never copies sibling secrets."""
import hashlib
import json
from pathlib import Path

import pytest

from scripts.prepare_release_checkpoint import prepare


@pytest.fixture
def repository(tmp_path):
    root = tmp_path / "repository"
    (root / "assets").mkdir(parents=True)
    (root / "weights").mkdir()
    config = b"MODEL: unchanged"
    checkpoint = b"trusted checkpoint"
    (root / "weights/config.yaml").write_bytes(config)
    manifest = dict(bytes=len(checkpoint), sha256=hashlib.sha256(checkpoint).hexdigest(),
                    config_sha256=hashlib.sha256(config).hexdigest())
    (root / "assets/model-manifest.json").write_text(json.dumps(manifest))
    source = tmp_path / "trusted"
    source.mkdir()
    (source / "best.pth").write_bytes(checkpoint)
    (source / ".env").write_text("PRIVATE_TEST_VALUE=do-not-copy")
    return root, source / "best.pth"


def test_only_the_verified_file_enters_context(repository, tmp_path):
    root, source = repository
    destination = tmp_path / "context"
    prepare(source, destination, root)
    assert {p.name for p in destination.iterdir()} == {"best.pth", ".dockerignore"}
    assert (destination / "best.pth").read_bytes() == source.read_bytes()
    assert (destination / "best.pth").stat().st_mode & 0o222 == 0


def test_checkpoint_substitution_rejected_before_context_creation(repository, tmp_path):
    root, source = repository
    source.write_bytes(b"changed checkpoint")
    destination = tmp_path / "context"
    with pytest.raises(ValueError, match="integrity"):
        prepare(source, destination, root)
    assert not destination.exists()


def test_existing_context_is_not_overwritten(repository, tmp_path):
    root, source = repository
    destination = tmp_path / "context"
    destination.mkdir()
    (destination / "existing").write_text("preserve")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        prepare(source, destination, root)
    assert (destination / "existing").read_text() == "preserve"


def test_wrong_tracked_configuration_rejected(repository, tmp_path):
    root, source = repository
    (root / "weights/config.yaml").write_text("MODEL: incompatible")
    with pytest.raises(ValueError, match="configuration"):
        prepare(source, tmp_path / "context", root)
