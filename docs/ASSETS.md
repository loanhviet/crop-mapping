# External model and dataset provisioning

A clone contains source/configuration/licenses, not runnable inference assets. Never commit checkpoints, raw imagery, predictions, results or credentials.

## Checkpoint

Obtain `best.pth` from the original project's trusted maintainer or an authorized artifact store. The recorded source reference is https://github.com/loanhviet/tsvit-crop-segmentation; a working direct checkpoint download URL has **not** been verified. No download credential or guessed URL is provided.

Place it at `weights/best.pth`, or export `CROP_WEIGHTS_DIR` for native execution. Keep the matching tracked `config.yaml` and `LICENSE.txt` in that directory.

- Bytes: 6,665,903.
- SHA256: `92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733`.
- Machine-readable identity: [model manifest](../assets/model-manifest.json).

```bash
# Explicitly copy from a trusted, separately supplied file; do not overwrite an existing checkpoint.
test ! -e weights/best.pth && cp /trusted/path/best.pth weights/best.pth
python3 scripts/verify_assets.py --profile model
```

The verifier reads files and hashes only; it never loads PyTorch checkpoints or performs inference. Matching a hash proves identity against this manifest, not scientific accuracy.

## PASTIS demo and CI fixtures

After installing requirements:

```bash
.venv/bin/python prepare_data.py --patches 10000 10003
.venv/bin/python scripts/verify_assets.py --profile ci
```

The existing tool uses official PASTIS archive HTTP Range requests. Internet access and upstream availability are required; no download was performed during migration. It writes its generated catalog only after preparing imagery. Default invocation without `--patches` prepares eight test patches but omits training patch 10000 required by regression tests.

```text
data/
├── catalog.json
├── metadata.geojson
├── S2_10000.npy
└── S2_10003.npy
```

Original arrays have `[T,10,128,128]` shape; inference uses a 120×120 usable footprint in 24×24 windows. CI metadata must include feature 20000, which one test uses to generate a temporary array. Ground-truth TARGET arrays are not required for normal inference or this regression suite. `python -m scripts.validate_cog` separately requires reference targets.

Catalog metadata includes region id, split, season, CRS/origin/shape, geometry, dates, DOY, frame order and image hash. `inference.PreparedProvider` is the runtime source of truth. Do not edit frame order or replace sources with unrelated imagery to satisfy tests.

## Continuous Normandy regions

```bash
.venv/bin/python prepare_cog.py --config preparation/cog_config.json
# Larger nine-block region:
.venv/bin/python prepare_regions.py --config preparation/regions_config.json
```

These preparation operations access Earth Search STAC/AWS COG assets and write datasets; they are not smoke tests. Preparation pins geographic/quality configuration and retains provenance, scale/offset and quality masks. Keep each catalog, cube, masks and dataset version together:

```text
data/cog/catalog.json
data/cog/<region-slug>/observations.npy
data/cog/<region-slug>/valid-mask.npy
data/cog/<region-slug>/report.json
```

A mosaic catalog also requires every referenced child region. The original nine-block arrays occupy approximately 8.28 GB before caches. Full dataset hashes and reproducibility from today's upstream catalog were not revalidated during migration. Prefer immutable artifact versions/checksums when exact reproduction is required.

## Docker mounts and artifact storage

Phase 2 release images package the exact manifest-verified checkpoint and tracked config/license. Production Compose mounts imagery only, not weights. The build helper accepts CROP_CHECKPOINT_FILE and prepares a minimal named context; the root build context still excludes checkpoint binaries. See [release build and CI provisioning](CONTAINERS.md).

Local development Compose binds `./data` to `/app/data` and `./weights` to `/app/weights`, both read-only. Results use a writable named volume at `/app/results`. Native path variables do not change the host-side bind sources in this unchanged Compose file.

An external asset directory is suitable for native use; Docker requires explicit bind configuration or provisioning into the expected host directories. An application image alone is insufficient. Do not symlink catalog members outside the data root; the provider rejects escaping paths.

Recommended future storage: versioned object storage for imagery and the exact checkpoint; Git holds only manifests. Record object/version identity, bytes, SHA256, dataset version, CRS/grid/dates/band order, source and license. Never commit credentials or expiring signed URLs. No bucket, remote artifact store or automated fetch service was created.

## Packaging

Deployment bundles contain runtime/preparation material, not the full pytest suite. Run repository tests from a full source checkout.

`package_deploy.py --live` packages prepared raw time series, checkpoint and application without saved predictions. Output bundles are ignored by Git and must be written to a new destination. `--live` does not fetch imagery at request time. The legacy `--predictions-only` option is retained for compatibility but its output is rejected by the current interactive server.

PASTIS source and attribution: https://zenodo.org/records/5012942 (CC BY 4.0 as documented upstream). Verify redistribution rights for each dataset/artifact before publication; dataset permissions do not derive from the model license.
