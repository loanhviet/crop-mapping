"""Check host/container configuration separation through the real Compose parser."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="Docker Compose CLI is not installed")


def compose_config(settings):
    environment = {k: v for k, v in os.environ.items() if not k.startswith("CROP_")}
    environment.update(settings)
    result = subprocess.run(
        ["docker", "compose", "--env-file", os.devnull, "-f", "compose.production.yaml", "config", "--format", "json"],
        cwd=ROOT, env=environment, capture_output=True, text=True,
    )
    if "is not a docker command" in result.stderr or "unknown command" in result.stderr:
        pytest.skip("Docker Compose plugin is not installed")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_host_paths_and_legacy_weights_setting_do_not_hide_packaged_model(tmp_path):
    digest = "loanhviet070105/crop-mapping@sha256:" + "a" * 64
    config = compose_config(dict(CROP_IMAGE=digest, CROP_DATA_DIR=str(tmp_path / "imagery"),
                                 CROP_WEIGHTS_DIR=str(tmp_path / "model"), CROP_THREADS="3",
                                 CROP_MEMORY_LIMIT="3g", CROP_CPUS="2", CROP_PORT="18088"))
    service = config["services"]["crop-map"]
    assert service["image"] == digest and "build" not in service and "platform" not in service
    assert service["environment"]["CROP_DATA_DIR"] == "/app/data"
    assert service["environment"]["CROP_WEIGHTS_DIR"] == "/app/weights"
    assert service["environment"]["CROP_THREADS"] == "3"
    bind = {v["target"]: v for v in service["volumes"] if v["type"] == "bind"}
    assert bind["/app/data"]["source"] == str(tmp_path / "imagery")
    assert "/app/weights" not in bind
    assert all(v["read_only"] and not v["bind"]["create_host_path"] for v in bind.values())
    assert int(service["mem_limit"]) == 3 * 1024**3
    assert float(service["cpus"]) == 2
    assert int(service["ports"][0]["published"]) == 18088


def test_portable_defaults_do_not_select_a_cpu_architecture():
    service = compose_config({})["services"]["crop-map"]
    assert service["image"] == "loanhviet070105/crop-mapping:unpublished"
    assert "platform" not in service and "build" not in service
    assert service["user"] == "10001:10001" and service["read_only"]
    assert service["environment"]["CROP_DEVICE"] == "cpu"
    assert service["healthcheck"]["test"][0] == "CMD"
