# Application architecture

Runtime remains at repository root to preserve imports, `__file__` roots, Uvicorn `app:app`, notebooks and Docker COPY paths.

`app.py` imports `inference`, `imagery`, `predictions`; `inference` imports TSViT from `model`. The backend serves `web/` directly. There is no DINOv3 dependency and no frontend build system.

1. Browser loads catalog and selects a closed one-ring WGS84 Polygon, coordinates `[lng,lat]`.
2. Imagery plan resolves coverage and quality. It does not run classification.
3. POST analyses validates selection, creates UUID/request/status files, then submits one bounded worker.
4. PreparedProvider maps each 24×24 window to the appropriate raw cube/calendar. NumPy mmap avoids loading the complete time series into RAM.
5. Bands B2/B3/B4/B5/B6/B7/B8/B8A/B11/B12 are normalized using the existing fold-1 mean/std. DOY/365.0001 is appended, frames cut/zero-padded to 60, tensor shape `[60,24,24,11]`.
6. TSViT temporal/spatial Transformers produce 19 class logits. Softmax/argmax provides labels and confidence.
7. Exports share one native 10 m label grid, class 0 remains valid and nodata is 255. Each valid pixel contributes 0.01 ha. TIFF/native PNG retain native grid, overlay is projected to Web Mercator, GeoJSON is WGS84.
8. Browser polls status and loads completed-job overlays, pixel lookup and downloads.

Every accepted Analyze executes a fresh prediction. PredictionStore/precompute tooling remain for original imports/tests but interactive saved classifications are disabled. Startup rejects prediction-only regions. Completed jobs persist; interrupted jobs become errors after restart. Jobs/locks are process-local, so keep one Uvicorn worker.

Prepared source uses installed imagery offline, except browser basemap. Optional native GEODES mode downloads full scene ZIPs, aligns bands and caches crops. Supplied Compose pins prepared/CPU, mounts data read-only and provides only 64 MiB temporary storage: it is not a GEODES deployment profile.

Model loader uses `weights_only=True`, strict state loading and eval/inference modes. Health reports loaded model/config state but does not execute a forward pass. Full-region accuracy and current ARM64 performance are unverified.

Editable diagrams and retained SVGs: [diagram sources](bao-cao/README.md). [API collection](postman/README.md) and [asset contracts](ASSETS.md) provide execution details.
