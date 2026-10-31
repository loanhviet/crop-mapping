"""Read-only integrity checks for provisioned assets; never imports the AI runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def verify_model(weights: Path, manifest: dict) -> None:
    checkpoint = weights / manifest["filename"]
    if not checkpoint.is_file():
        raise ValueError("Missing checkpoint: provision weights/best.pth first.")
    if checkpoint.stat().st_size != manifest["bytes"] or digest(checkpoint) != manifest["sha256"]:
        raise ValueError("Checkpoint integrity mismatch; refuse to use this artifact.")
    config = weights / "config.yaml"
    if not config.is_file() or digest(config) != manifest["config_sha256"]:
        raise ValueError("Model configuration does not match the pinned artifact manifest.")


def verify_ci_data(data: Path) -> None:
    """Check fixture presence, identities and containment, without reading imagery."""
    required = [data / name for name in ("catalog.json", "metadata.geojson", "S2_10000.npy", "S2_10003.npy")]
    if not all(p.is_file() for p in required):
        raise ValueError("Missing CI fixtures: catalog, metadata, S2_10000.npy and S2_10003.npy are required.")
    catalog = json.loads((data / "catalog.json").read_text())
    patches = {p["id"]: p for p in catalog["patches"]}
    if not {10000, 10003}.issubset(patches):
        raise ValueError("CI catalog must contain patch 10000 and patch 10003.")
    if patches[10003].get("split") != "test":
        raise ValueError("Patch 10003 must retain its test split.")
    metadata = json.loads((data / "metadata.geojson").read_text())
    if not any(f["properties"]["ID_PATCH"] == 20000 for f in metadata["features"]):
        raise ValueError("CI metadata must include feature 20000.")
    for patch_id in (10000, 10003):
        patch = patches[patch_id]
        image = (data / patch.get("image_path", f"S2_{patch_id}.npy")).resolve()
        if not image.is_relative_to(data.resolve()) or not image.is_file():
            raise ValueError("Catalog image path is missing or escapes the data directory.")
        if not patch.get("sha256") or digest(image) != patch["sha256"]:
            raise ValueError("Fixture image integrity differs from its catalog.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights-dir", type=Path, default=Path(os.getenv("CROP_WEIGHTS_DIR", ROOT / "weights")))
    parser.add_argument("--data-dir", type=Path, default=Path(os.getenv("CROP_DATA_DIR", ROOT / "data")))
    parser.add_argument("--profile", choices=("model", "ci"), default="model")
    args = parser.parse_args()
    try:
        verify_model(args.weights_dir, json.loads((ROOT / "assets/model-manifest.json").read_text()))
        if args.profile == "ci":
            verify_ci_data(args.data_dir)
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"Asset verification failed: {error}\n")
    print("Asset integrity checks passed. Model loading and inference were not executed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
