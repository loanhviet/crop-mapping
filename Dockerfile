FROM python:3.13-slim-bookworm

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
COPY requirements.txt .
RUN python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 cropmap \
    && useradd --uid 10001 --gid cropmap --no-create-home cropmap \
    && mkdir -p /app/data /app/weights /app/results \
    && chown cropmap:cropmap /app/results

# Rasterio's bundled GDAL still needs the system XML parser on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

COPY app.py inference.py imagery.py model.py predictions.py ./
COPY web/ ./web/
USER cropmap
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).read()"
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
