"""Small real-inference HTTP smoke; requires a separately started, asset-mounted app."""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def request(base, path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {"Content-Type": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(base.rstrip("/") + path, data=payload, headers=headers), timeout=20) as response:
        data = response.read()
        return json.loads(data) if "application/json" in response.headers.get("Content-Type", "") else data


def small_geometry(patch):
    points = patch["geometry"]["coordinates"][0][:-1]
    center = [sum(p[i] for p in points) / len(points) for i in (0, 1)]
    ring = [[center[i] + (p[i] - center[i]) * .05 for i in (0, 1)] for p in points]
    return dict(type="Polygon", coordinates=[ring + [ring[0]]]), center


def run(base, output, timeout, patch_id):
    import numpy as np
    import rasterio
    from PIL import Image
    from rasterio.io import MemoryFile

    deadline = time.monotonic() + timeout
    while True:
        try:
            health = request(base, "/api/health")
            break
        except (OSError, urllib.error.URLError):
            if time.monotonic() >= deadline:
                raise RuntimeError("Application did not become ready before the deadline")
            time.sleep(1)
    expected = json.loads((ROOT / "assets/model-manifest.json").read_text())["sha256"]
    assert health["status"] == "ok" and health["device"] == "cpu"
    assert health["checkpoint_sha256"] == expected
    catalog = request(base, "/api/catalog")
    patch = next(p for p in catalog["patches"] if p["id"] == patch_id)
    geometry, center = small_geometry(patch)
    body = dict(patch_id=patch_id, season=catalog["seasons"][0], geometry=geometry)
    plan = request(base, "/api/imagery-plan", body)
    assert 0 < plan["windows"] <= 4, "Smoke refuses an unexpectedly expensive AOI"
    jobs = []
    for _ in range(2):
        created = request(base, "/api/analyses", body)
        assert created["cached"] is False
        jobs.append(created["id"])
        while True:
            status = request(base, "/api/analyses/" + jobs[-1])
            if status["status"] in ("done", "error", "cancelled"):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("Inference did not finish before the deadline")
            time.sleep(.25)
        assert status["status"] == "done", status.get("message")
        assert status["result"]["reused_prediction"] is False
        assert status["result"]["checkpoint_sha256"] == expected
    assert jobs[0] != jobs[1]
    result = status["result"]
    assert result["pixels"] > 0
    assert sum(c["pixels"] for c in result["classes"]) == result["pixels"]
    assert abs(result["area_ha"] - result["pixels"] * .01) < .00001
    pixel = request(base, f"/api/analyses/{jobs[-1]}/pixel?lng={center[0]}&lat={center[1]}")
    assert 0 <= pixel["id"] <= 18 and 0 <= pixel["confidence"] <= 1
    payloads = {}
    for format in ("tif", "csv", "png", "geojson", "zip"):
        payloads[format] = request(base, f"/api/analyses/{jobs[-1]}/download/{format}")
        # application/geo+json may be decoded by the client only as bytes here.
        if isinstance(payloads[format], dict):
            payloads[format] = json.dumps(payloads[format]).encode()
        (output / f"classification.{format}").write_bytes(payloads[format])
    with MemoryFile(payloads["tif"]) as memory, memory.open() as raster:
        labels = raster.read(1)
        assert raster.nodata == 255 and raster.crs.to_string() == result["crs"]
        assert raster.transform.a == 10 and raster.transform.e == -10
        valid = labels != 255
        assert int(valid.sum()) == result["pixels"]
        assert np.all(labels[valid] <= 18)
        raster_info = dict(shape=list(labels.shape), crs=str(raster.crs), nodata=raster.nodata)
    rows = list(csv.DictReader(io.StringIO(payloads["csv"].decode("utf-8-sig"))))
    assert sum(int(row["pixels"]) for row in rows) == result["pixels"]
    features = json.loads(payloads["geojson"])
    assert features["type"] == "FeatureCollection" and features["features"]
    for feature in features["features"]:
        assert 0 <= feature["properties"]["class_id"] <= 18
    with Image.open(io.BytesIO(payloads["png"])) as image:
        image.verify()
    with zipfile.ZipFile(io.BytesIO(payloads["zip"])) as archive:
        assert archive.testzip() is None
        assert set(archive.namelist()) == {"classification.tif", "summary.csv", "classification.png", "classification.geojson", "result.json"}
        for format, name in [("tif", "classification.tif"), ("csv", "summary.csv"), ("png", "classification.png")]:
            assert archive.read(name) == payloads[format]
    for image_name in ("overlay", "preview"):
        image_bytes = request(base, f"/api/analyses/{jobs[-1]}/{image_name}.png")
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.verify()
    summary = dict(status="passed", checkpoint_sha256=expected, device=health["device"],
                   jobs=jobs, patch_id=patch_id, windows=plan["windows"], pixels=result["pixels"],
                   area_ha=result["area_ha"], raster=raster_info, pixel=pixel,
                   exports=list(payloads), repeated_request_runs_new_inference=True)
    (output / "smoke.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--patch-id", type=int, default=10003)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    args.output.mkdir(parents=True, exist_ok=False)
    run(args.url, args.output, args.timeout, args.patch_id)


if __name__ == "__main__":
    main()
