"""Prepare a minimal verified named build context. Never downloads or loads a model."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def prepare(source, destination, repository=ROOT):
    manifest = json.loads((repository / "assets/model-manifest.json").read_text())
    if not source.is_file():
        raise ValueError("Missing checkpoint; provision a trusted file and set CROP_CHECKPOINT_FILE.")
    if source.stat().st_size != manifest["bytes"] or digest(source) != manifest["sha256"]:
        raise ValueError("Source checkpoint integrity mismatch.")
    if digest(repository / "weights/config.yaml") != manifest["config_sha256"]:
        raise ValueError("Tracked configuration differs from the checkpoint manifest.")
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError("Checkpoint context must be empty; refusing to overwrite existing files.")
    target = destination / "best.pth"
    with source.open("rb") as incoming, target.open("xb") as output:
        shutil.copyfileobj(incoming, output)
    if target.stat().st_size != manifest["bytes"] or digest(target) != manifest["sha256"]:
        raise ValueError("Copied checkpoint integrity mismatch; do not build this context.")
    target.chmod(0o444)
    (destination / ".dockerignore").write_text("**\n!best.pth\n")
    print("Verified checkpoint context prepared; no source directory was copied.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.source, args.destination)
    except (ValueError, OSError) as error:
        parser.exit(1, f"Checkpoint provisioning failed: {error}\n")


if __name__ == "__main__":
    main()
