"""Catch substituted checkpoints and unsafe/inconsistent fixture catalogs."""
import hashlib
import json

import pytest

from scripts.verify_assets import verify_ci_data, verify_model


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def model_files(tmp_path):
    (tmp_path / "best.pth").write_bytes(b"trusted-model")
    (tmp_path / "config.yaml").write_bytes(b"MODEL: {}")
    return tmp_path, dict(filename="best.pth", bytes=13, sha256=sha(b"trusted-model"), config_sha256=sha(b"MODEL: {}"))


def test_verified_checkpoint(model_files):
    verify_model(*model_files)


def test_same_size_checkpoint_substitution_rejected(model_files):
    directory, manifest = model_files
    (directory / "best.pth").write_bytes(b"altered-model")
    with pytest.raises(ValueError, match="integrity"):
        verify_model(directory, manifest)


def test_changed_model_configuration_rejected(model_files):
    directory, manifest = model_files
    (directory / "config.yaml").write_bytes(b"MODEL: changed")
    with pytest.raises(ValueError, match="configuration"):
        verify_model(directory, manifest)


@pytest.fixture
def ci_data(tmp_path):
    patches = []
    for identifier in (10000, 10003):
        content = f"fixture-{identifier}".encode()
        (tmp_path / f"S2_{identifier}.npy").write_bytes(content)
        patches.append(dict(id=identifier, split="test" if identifier == 10003 else "training", sha256=sha(content)))
    (tmp_path / "catalog.json").write_text(json.dumps(dict(patches=patches)))
    (tmp_path / "metadata.geojson").write_text(json.dumps(dict(features=[dict(properties=dict(ID_PATCH=20000))])))
    return tmp_path


def test_verified_fixture_identities(ci_data):
    verify_ci_data(ci_data)


def test_changed_fixture_content_rejected(ci_data):
    (ci_data / "S2_10003.npy").write_bytes(b"substitution")
    with pytest.raises(ValueError, match="integrity"):
        verify_ci_data(ci_data)


def test_catalog_cannot_escape_fixture_directory(ci_data):
    catalog = json.loads((ci_data / "catalog.json").read_text())
    catalog["patches"][0]["image_path"] = "../outside.npy"
    (ci_data / "catalog.json").write_text(json.dumps(catalog))
    with pytest.raises(ValueError, match="escapes"):
        verify_ci_data(ci_data)
