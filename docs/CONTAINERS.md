# CPU AMD64 containers and Docker Hub

This phase targets **Linux CPU / linux/amd64**. ARM64 and multi-platform publishing are out of scope. Application/model/preprocessing/UI behavior is unchanged. Docker Hub target: `loanhviet070105/crop-mapping`. Phase 2 local validation evidence is recorded separately; the owner reports that an AMD64 image was subsequently published.

## Build

The existing Dockerfile retains Python 3.13, PyTorch CPU, Rasterio wheels with bundled GDAL, `libexpat1`, UID 10001, one Uvicorn worker and the HTTP healthcheck. Direct runtime dependency versions are unchanged. The Python base/frontend are pinned by digest; transitive Python versions and wheel hashes are locked. Pytest moved to `requirements-dev.txt` because production does not need it. See [dependency lock](../requirements/README.md).

```bash
docker version
docker buildx ls
# A clean committed checkout is required for commit-derived tags.
CROP_CHECKPOINT_FILE=/trusted/artifacts/best.pth scripts/build_image.sh amd64
```

The helper verifies the checkpoint against the committed manifest, copies only best.pth into a fresh ignored named context, and builds the release target. Docker independently verifies checkpoint/config hashes inside the image. It builds/loads a local image tagged `loanhviet070105/crop-mapping:sha-<12-character-commit>-amd64`, labels its full source revision and writes local metadata under ignored `.validation/phase2/`. It never pushes. Source/label changes reuse the dependency layer; the pip cache is a BuildKit mount, not part of the image. APT security packages come from the live Bookworm repository, so the entire build is not claimed to be bit-reproducible.

The release image includes the verified TSViT checkpoint/config and licenses/notices, but no private .env, Git metadata, virtual environment or satellite data. The default development target retains external weights mounts. See [publication review](../THIRD_PARTY_NOTICES.md) and [actual validation](CONTAINER_VALIDATION.md).

## External assets

Follow [ASSETS.md](ASSETS.md). Release builders obtain the exact checkpoint from a trusted source; production users pull it packaged in the release image and only provision a consistent satellite catalog/images. A clone still lacks checkpoint/data. A release image still needs external imagery.

```bash
python scripts/verify_assets.py --weights-dir /trusted/weights --data-dir /trusted/data --profile ci
```

The CI profile needs PASTIS patches 10000/10003 and metadata. Full Normandy is unnecessary for smoke. Checkpoint files remain outside Git and enter only the release image. Satellite assets remain external and are mounted read-only; no source dataset was modified during validation.

## Pull and run after approved publication

`compose.yaml` remains unchanged for local builds. `compose.production.yaml` has no build step. Its `unpublished` image default is intentionally not a real release claim: replace it before pulling.

```bash
cp deployment/production.env.example .env.production
# Edit image and host paths before continuing.
docker compose --env-file .env.production -f compose.production.yaml config --quiet
docker compose --env-file .env.production -f compose.production.yaml pull
docker compose --env-file .env.production -f compose.production.yaml up -d --no-build --wait
curl --fail http://127.0.0.1:8000/api/health
```

Example environment after publication:

```dotenv
CROP_IMAGE=loanhviet070105/crop-mapping@sha256:REPLACE_WITH_VERIFIED_PUBLISHED_DIGEST
CROP_DATA_DIR=./data
CROP_DEVICE=cpu
CROP_BIND=127.0.0.1
CROP_PORT=8000
CROP_THREADS=2
CROP_CPUS=2
CROP_MEMORY_LIMIT=2g
CROP_RESULTS_VOLUME=crop-mapping-results
```

CROP_DATA_DIR selects the imagery host bind source; relative paths resolve against the Compose project directory. The application reads `/app/data`, packaged `/app/weights` and writable `/app/results`. Production intentionally has NO weights bind, so host settings cannot hide the packaged checkpoint. Native Python reads exported process environment paths; local development Compose retains its original data/weights binds and uses the default development build target. Only CPU is supported by this image.

The production configuration preserves a read-only imagery mount, a writable named results volume, non-root user, read-only root filesystem, 64 MiB temporary storage, dropped capabilities, no-new-privileges, health/restart policies and log rotation. Resource defaults match the local 2 CPU/2 GiB limits and remain configurable. Keep one worker. Do not share a results volume between concurrent application instances or use `down -v` on outputs you need.

Before changing an existing deployment, record its actual project/volume/mount identities and back up results. This phase did not contact EC2/Oracle and does not implement deployment automation, TLS, login or rollback. Localhost remains the default bind.

Linux AMD64 is the validation target. Docker Desktop Linux containers on compatible x86-64 hosts may be usable but were not tested. Native ARM64, macOS/Windows-specific sharing and performance are not claimed. No architecture is hardcoded in production Compose; users must choose a host compatible with the published AMD64 image.

## Real inference smoke

Health only verifies startup. After starting a release container with external satellite imagery:

```bash
.venv/bin/python scripts/container_smoke.py --url http://127.0.0.1:8000 --output .validation/smoke-new-run
```

Install host test tooling with `requirements-dev.txt`. The smoke helper selects a tiny AOI in PASTIS patch 10003, refuses plans over four windows, submits two identical requests and checks distinct jobs, model hash, done status, fresh inference metadata, pixel/area, TIFF grid/classes/nodata and CSV/GeoJSON/PNG/ZIP/overlay/preview. Output directories must be new. An external-only bundle requires a suitable separate fixture rather than assuming patch 10003 exists.

## Publishing commands — approval required, not executed

Prerequisites: ownership of the public Docker Hub repository, a scoped access token available in your terminal/credential helper, image validation, distribution-rights review and explicit approval before the first public push. Do not send credentials in chat or store them in .env/source.

```bash
docker login --username loanhviet070105
IMAGE=loanhviet070105/crop-mapping
# Exact local tag verified for source commit 8a90dfd9b4b6; publication is still gated.
docker push "$IMAGE:sha-8a90dfd9b4b6-amd64"
docker buildx imagetools inspect "$IMAGE:sha-8a90dfd9b4b6-amd64"
```

Optionally alias the same verified image as `sha-<commit>` or an actual approved semantic version; do not label an AMD64-only release as multi-platform:

```bash
docker tag "$IMAGE:sha-8a90dfd9b4b6-amd64" "$IMAGE:sha-8a90dfd9b4b6"
docker push "$IMAGE:sha-8a90dfd9b4b6"
# VERSION must be a real approved release version, not an invented milestone.
docker tag "$IMAGE:sha-8a90dfd9b4b6-amd64" "$IMAGE:$VERSION"
docker push "$IMAGE:$VERSION"
```

Inspect the published digest, pin it in CROP_IMAGE, then verify a pull from a separate unauthenticated machine. Local image IDs or locally exported manifest digests do not establish a public registry digest.

```bash
docker pull loanhviet070105/crop-mapping@sha256:REPLACE_WITH_PUBLISHED_DIGEST
```

## Troubleshooting

- Missing model/data: follow provisioning; health cannot succeed until startup assets load.
- Hash/wheel failure: do not remove integrity checks or compile native libraries silently; review the exact lock and target platform.
- Permission errors: verify UID 10001 can read assets and write results; do not make source mounts writable.
- `exec format error`: this image is validated for AMD64, not native ARM64.
- Slow whole-region inference: use a small AOI; one worker and prepared window-limit behavior are unchanged.
- Health failure after update: preserve results, inspect this service's logs and restore a compatible image/model/data set. Automated recovery remains future work.

## GitHub Actions checkpoint provisioning

The implemented publishing workflow and private Release asset setup are described
in [CI.md](CI.md). The owner supplies the actual private repository, asset ID and
read-only token. Each run obtains a fresh download via the GitHub API and applies
the same manifest verification and named-context release build as local builds.
No personal path, expiring URL, binary weights, or credential is committed.

Only the verified checkpoint enters the named context; root .dockerignore still
excludes .pth files. Use trusted runners and do not export model layers as public
caches without distribution rights. The workflow initializes the packaged model;
real satellite inference additionally requires external imagery. Public model
and application redistribution must be authorized by the owner.
