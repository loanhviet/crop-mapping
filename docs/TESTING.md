# Validation and regression tests

Run from the repository root after installing `requirements-dev.txt` in an isolated environment.

```bash
python -m pytest -q -rs
```

Without provisioned assets, the current suite includes the original lightweight and asset-integrity tests plus the Phase 2 Compose/checkpoint contract tests. In the Phase 2 environment the full suite completed with 36 passed and one Starlette deprecation warning; the 11 original data-dependent tests are skipped unless assets are provisioned. The original four regression files and their assertions remain unchanged.

```bash
python -m pytest -q -m 'not external_assets'
python scripts/verify_assets.py --profile ci
python -m pytest -q --require-assets
```

The last command fails collection if selected tests lack external assets; it must be used for a full regression gate. Full regression includes real model inference and should run only in a validation environment where this is authorized. `-m inference` selects the five tests that perform real inference; other asset-dependent tests still need the checkpoint or PASTIS fixtures.

See [asset provisioning](ASSETS.md). Minimal PASTIS fixtures include patch 10000, patch 10003, their catalog and the official metadata including feature 20000. The tests generate small temporary COG/mosaic arrays themselves. Full Normandy cubes and ground-truth targets are not required for this regression suite.

No assets are downloaded automatically by pytest. Keep writable data/results and pytest temporary directories separate from a working deployment. Environment paths must be exported before Python imports the application; several defaults are captured at import time.

Health verifies startup and HTTP, not prediction quality. Phase 2 additionally builds the AMD64 release image and uses a small fixture-backed real-inference smoke to poll until `done`, then validate overlay, pixel lookup and TIFF/CSV/GeoJSON/ZIP exports. Results and environment limits are recorded in [container validation](CONTAINER_VALIDATION.md).

The supplied Postman collection selects a small PASTIS test patch. A `--live` bundle contains only external COG regions, so it requires a separate smoke profile; do not treat a failed PASTIS selection as failed inference.

Phase 2 adds Compose host/container path-contract tests and a reusable real-inference HTTP smoke helper. See [container validation](CONTAINER_VALIDATION.md); original migration results remain historical.
