# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
# Pinned base index: CPython 3.13.18, Debian Bookworm (glibc 2.36).
# This phase validates CPU linux/amd64 only.
FROM python:3.13.18-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f AS runtime

ARG TARGETARCH

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    CROP_DATA_DIR=/app/data \
    CROP_WEIGHTS_DIR=/app/weights \
    CROP_RESULTS_DIR=/app/results \
    CROP_SOURCE=prepared \
    CROP_DEVICE=cpu \
    CROP_THREADS=2

WORKDIR /app
# Rasterio wheels bundle GDAL; slim still needs the system XML parser.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 cropmap \
    && useradd --uid 10001 --gid cropmap --no-create-home cropmap \
    && mkdir -p /app/data /app/weights /app/results /app/licenses \
    && chown cropmap:cropmap /app/results

COPY requirements/locks/linux-amd64.txt ./requirements/locks/linux-amd64.txt
RUN --mount=type=cache,id=crop-mapping-pip-amd64,target=/root/.cache/pip \
    test "$TARGETARCH" = amd64 \
    && python -m pip install --only-binary=:all: --require-hashes \
       -r requirements/locks/linux-amd64.txt \
    && python -m pip check \
    && python -c "import torch, rasterio, pyproj; assert torch.version.cuda is None, 'CPU-only PyTorch required'"

ARG VCS_REF
ARG IMAGE_VERSION=local
LABEL org.opencontainers.image.title="Crop Mapping" \
      org.opencontainers.image.source="https://github.com/loanhviet/crop-mapping" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.version="${IMAGE_VERSION}"

COPY app.py inference.py imagery.py model.py predictions.py ./
COPY web/ ./web/
COPY weights/LICENSE.txt ./licenses/TSViT-APACHE-2.0.txt
COPY THIRD_PARTY_NOTICES.md ./licenses/THIRD_PARTY_NOTICES.md
USER cropmap
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).read()"
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]

# Release builds receive only a verified best.pth through a named local context.
# The checkpoint remains excluded from Git and the main build context.
FROM runtime AS release
COPY --from=checkpoint best.pth /app/weights/best.pth
COPY weights/config.yaml weights/LICENSE.txt /app/weights/
COPY assets/model-manifest.json /app/assets/model-manifest.json
RUN python -c "import hashlib,json,pathlib; r=pathlib.Path('/app'); m=json.loads((r/'assets/model-manifest.json').read_text()); p=r/'weights/best.pth'; assert p.stat().st_size == m['bytes']; assert hashlib.sha256(p.read_bytes()).hexdigest() == m['sha256']; assert hashlib.sha256((r/'weights/config.yaml').read_bytes()).hexdigest() == m['config_sha256']"

# Preserve docker build / local Compose behavior without requiring a checkpoint context.
FROM runtime AS development
