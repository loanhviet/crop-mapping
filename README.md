# Crop Mapping

A TSViT crop-classification application with FastAPI, Leaflet and Docker Compose. Users select an area and season, run classification on prepared Sentinel-2 time series, inspect crop labels and download geospatial outputs.

This application is independent of the DINOv3 research project. The application has previously been deployed on AWS EC2 according to its owner. The current EC2 configuration was not inspected during migration.

## Architecture and features

Browser → FastAPI → one bounded background worker → prepared imagery → preprocessing → TSViT → exports → Leaflet overlay.

- Select an area inside an available region; inspect imagery and acquisition dates.
- Each accepted Analyze request performs a new prediction, including repeated selections.
- Track progress, request cancellation, inspect pixels and crop areas.
- Export GeoTIFF, GeoJSON, CSV, PNG and ZIP.
- Preserve completed results in a writable volume across container replacement.

Python/FastAPI/Uvicorn, PyTorch/einops, NumPy, Rasterio/GDAL, pyproj, Pillow and vanilla HTML/CSS/JavaScript with Leaflet. There is no frontend build step. Esri basemap tiles require browser Internet access.

## Repository layout

```text
app.py, inference.py, model.py, imagery.py, predictions.py  runtime modules
web/                                                     frontend and licensed assets
prepare_*.py, cog_data.py, precompute_regions.py           data tools
scripts/benchmark_cog.py, scripts/validate_cog.py                         validation tools
tests/, conftest.py, pytest.ini                          regressions and asset gates
preparation/                                             configs and standalone notebooks
assets/model-manifest.json, scripts/verify_assets.py      integrity metadata and verification
weights/                                                 tracked config/license; external checkpoint
data/                                                    external imagery; tracked README only
docs/, deployment/                                       guides, architecture and deployment notes
Dockerfile, compose*.yaml                                CPU deployment configurations
```

Runtime modules stay at root to preserve import, CLI and notebook assumptions; regression tests are under `tests/`. `scripts/benchmark_cog.py` and `precompute_regions.py` are retained because original tests import them. Run the relocated tools from the repository root as `python -m scripts.benchmark_cog` and `python -m scripts.validate_cog`.

Specialized guides: [COG preparation](docs/COG.md), [multi-block regions](docs/REGIONS.md), [GEODES acquisition](docs/GEODES.md), and [deployment bundles](docs/DEPLOYMENT.md).

## Prerequisites

Python 3.13 and the pinned dependencies in `requirements.txt`; Docker Engine and Compose v2 for container use. Native COG preparation uses Linux `fcntl`. A hash-locked CPU AMD64 container build is provided; see [container workflow and validation](docs/CONTAINERS.md). The supplied image uses CPU PyTorch; GPU is not required.

## Local development

Run commands from this repository root, using a new environment:

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check
cp .env.example .env
```

Git intentionally does **not** contain checkpoint binaries or satellite datasets. The release image packages the verified checkpoint/config; development and native execution still provision weights separately. Obtain the exact checkpoint and verify it before starting:

```bash
python3 scripts/verify_assets.py --profile model
```

See [model/data provisioning](docs/ASSETS.md). A fresh clone cannot perform inference until assets are installed. Production release containers need external imagery but no host weights mount.

For a small prepared PASTIS demo (downloads official imagery):

```bash
.venv/bin/python prepare_data.py --patches 10000 10003
.venv/bin/python scripts/verify_assets.py --profile ci
CROP_SOURCE=prepared CROP_DEVICE=cpu CROP_THREADS=2 \
  .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1
```

Open http://127.0.0.1:8000. Patch 10000 supports regression fixtures and is not advertised as a public test region. `./run.sh` is also available, but may create a virtual environment and install dependencies. Path/device settings must be exported before importing the app; see `.env.example`.

## Tests

```bash
.venv/bin/python -m pytest -q -rs
# After provisioning CI fixtures and weights; includes real inference:
.venv/bin/python scripts/verify_assets.py --profile ci
.venv/bin/python -m pytest -q --require-assets
```

Without assets, 11 original asset-dependent tests skip explicitly. Lightweight tests do not establish real inference readiness. See [test profiles](docs/TESTING.md) and [actual migration results](docs/VALIDATION.md).

## Docker build and Compose

After provisioning `data/` and `weights/best.pth` (the local configuration is preserved; [production Compose](docs/CONTAINERS.md#portable-production-compose) pulls a verified registry reference):

```bash
docker build -t crop-map:prepared .
docker compose up -d --no-build --wait
docker compose ps
curl --fail http://127.0.0.1:8000/api/health
```

Alternatively `docker compose up -d --build` builds locally. These are setup instructions; migration did not build or start containers.

The unchanged Compose defaults bind localhost:8000, mount data/weights read-only, use a named results volume, run as UID 10001 with a read-only root filesystem, and limit the service to 2 CPUs/2 GiB. `/tmp` is a 64 MiB tmpfs. Do not share a results volume between concurrent application instances. Do not run `down -v` if results must survive.

See [deployment constraints](deployment/README.md) before changing an existing host. Production release builds use `CROP_CHECKPOINT_FILE=/trusted/artifacts/best.pth scripts/build_image.sh amd64`. The helper supplies only the verified file through a named context; the default Docker build target remains development. Production Compose is available in `compose.production.yaml` and never mounts over packaged weights. Docker Hub publication, native Oracle validation and Actions remain separate gated steps; see [CPU container deployment](docs/CONTAINERS.md).

## API

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Startup/model/device/hash status |
| GET | `/api/catalog` | Regions, seasons and classes |
| POST | `/api/imagery-plan` | Validate selection and describe imagery |
| GET | `/api/patches/{patch_id}/preview`, `/preview-bounds` | Satellite RGB preview and placement |
| POST | `/api/analyses` | Enqueue analysis; 202 with id/cached=false |
| GET / DELETE | `/api/analyses/{job_id}` | Poll status / request cancellation |
| GET | `/api/analyses/{job_id}/overlay.png`, `/preview.png` | Completed-job images |
| GET | `/api/analyses/{job_id}/pixel?lat=...&lng=...` | Pixel class/confidence |
| GET | `/api/analyses/{job_id}/download/{format}` | tif/csv/png/geojson/zip |

Swagger: `/docs`; OpenAPI: `/openapi.json`. Prepared patch classification tile/pixel endpoints intentionally return 404; use completed-job endpoints. See [Postman](docs/postman/README.md).

## Known limitations

Prepared data currently uses season `2018–2019` and installed footprints only. Model classes are 0–18; nodata is 255. Confidence is uncalibrated model probability, not measured accuracy. The full-region classification accuracy is not established by functional tests.

There is one inference worker and at most four pending/running jobs. The prepared window limit is disabled in the imported implementation; whole-region inference may take a long time. Cancellation is cooperative and does not interrupt an in-progress forward pass/export immediately. Health does not perform inference. There is no application login, rate limiting, TLS, results retention policy or automated rollback in this repository.

## Licensing and contribution workflow

Keep [model license](weights/LICENSE.txt), [Leaflet license](web/assets/LEAFLET-LICENSE.txt) and [font license](web/assets/CARLITO-LICENSE.txt). Dataset attribution is documented separately. No project-wide license has been selected by the owner; the upstream model license does not automatically license all application code/assets.

See [branch strategy](docs/BRANCHING.md), [architecture](docs/ARCHITECTURE.md) and [migration scope](docs/MIGRATION.md). GitHub origin is configured; no Actions workflow or deployment automation is implemented.
