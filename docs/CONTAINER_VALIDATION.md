# Phase 2 AMD64 release validation

This records checks performed locally on 2026-10-31. It is evidence for one Linux x86_64 host and one committed source revision; it does not establish ARM64, cloud-host, or public-registry behavior.

## Release artifact

| Field | Observed value |
| --- | --- |
| Source revision | `8a90dfd9b4b65a1a0e68b878fb965d9bec21c377` |
| Local image tag | `loanhviet070105/crop-mapping:sha-8a90dfd9b4b6-amd64` |
| Platform | `linux/amd64`, native execution on x86_64 |
| Local image ID / exported local OCI index digest | `sha256:5042c7f742c240531711ef9b86cf59373295ed67e1131b43b33c9a71fcca1372` |
| Single platform manifest digest | `sha256:33a65b0a4e235dc0beba1b98479f8406cdf4d49b8148bbb5bc697138dc096741` |
| Docker-reported image size | 1,731,903,742 bytes (about 1.73 GB decimal) |
| Model SHA256 | `92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733` |
| Model bytes | 6,665,903 |

These are local build identities, **not Docker Hub digests**. No image has been pushed. The image contains the exact checkpoint and matching `weights/config.yaml`; the Docker release stage checks both against `assets/model-manifest.json`. The separate checkpoint preparation helper verifies the trusted source file and copy before making the minimal named build context. `best.pth` remains ignored by Git and excluded from the default Docker context.

## Checks

| Check | Result | Evidence / limits |
| --- | --- | --- |
| AMD64 release image build | **PASSED** | Docker Buildx completed `--platform linux/amd64 --target release --load`; checkpoint and config hash assertions ran in the build. |
| Development target without checkpoint context | **PASSED** | Default development target built and ran without packaged weights; existing development Compose continues using its external read-only weights mount. |
| Full pytest suite | **PASSED** | `36 passed`, no failures/skips in this provisioned environment, one Starlette deprecation warning. |
| Production Compose config | **PASSED** | Compose config validation completed; production has no build step and has no `/app/weights` mount. |
| Dockerfile static check | **PASSED** | Release target and checkpoint context configuration checked without reported Dockerfile warnings. |
| Image checkpoint/config integrity | **PASSED** | In-image checkpoint SHA/size and config SHA match the tracked manifest. |
| Image content exclusion | **PASSED** | Runtime audit found no satellite arrays/data, `.env` probe, Git metadata, local virtual environment, or credentials; notices are present. |
| Native AMD64 startup and health | **PASSED** | Production Compose started the image, reported healthy, UID/GID `10001:10001`, read-only root, dropped all capabilities, and `no-new-privileges`. |
| Inference without external weights mount | **PASSED** | The production container had only the external read-only `/app/data` bind and persistent `/app/results` volume; the checkpoint remained image-provided. |
| Real TSViT inference | **PASSED** | Two analysis requests on PASTIS patch `10003`, one `120×120` window and 36 sampled pixels; both completed. Result: `0.36 ha`, CRS `EPSG:32630`, nodata `255`; sample class 12 confidence `0.8735`. This is a smoke test, not an accuracy benchmark. |
| Repeated request and restart persistence | **PASSED** | Repeated request produced a distinct completed job and validation completed after the Compose service restart. Results volume was isolated to this test and removed afterward. |
| Prediction/export checks | **PASSED** | TIFF grid/classes/nodata, CSV, GeoJSON, PNG, ZIP contents/CRC, overlay and preview were checked by the smoke helper. |
| ARM64 build/runtime | **NOT VERIFIED / OUT OF SCOPE** | No ARM64 image was built or published in this narrowed AMD64 phase. |
| Docker Hub pull/public digest | **NOT VERIFIED** | No authentication or public push was performed; local digest is not a registry digest. |
| Oracle/EC2 deployment | **NOT VERIFIED** | No cloud infrastructure was contacted. |

The container used Python `3.13.18`, PyTorch `2.14.1+cpu` (`torch.version.cuda is None`), Rasterio `1.5.2`, GDAL `3.12.2`, and pyproj `3.8.0`. The observed container cgroup peak was `391,585,792` bytes (about 374 MiB) during this single small smoke run, with a `2 GiB` configured memory ceiling. This is not a production sizing recommendation or full-area workload benchmark. CPU usage recorded by cgroup covers startup, image audit, and smoke together, not isolated model latency.

## Reproduction

The tracked build helper expects a clean commit and obtains a checkpoint path from `CROP_CHECKPOINT_FILE` or the default ignored local `weights/best.pth`:

```bash
CROP_CHECKPOINT_FILE=/trusted/artifacts/best.pth scripts/build_image.sh amd64
```

The helper prepares a fresh ignored context containing only verified `best.pth`, then invokes Buildx for the release target. The normal Docker context continues to exclude `.pth` files. Production runtime and the exact validation commands are documented in [CONTAINERS.md](CONTAINERS.md).

For the real inference smoke, the validation environment supplied only the required small PASTIS fixture files through the read-only data mount. It did not copy or alter the original dataset. A clone without the model cannot reproduce the release build until a trusted authorized checkpoint source has been provisioned. An image without the satellite catalog/imagery can start only when application startup requirements are met, but cannot run this inference request.

## Publication gate

Before publishing, the project owner must confirm redistribution rights for this exact trained checkpoint and the application/UI code. The Apache-2.0 text in the original weights directory does not by itself establish that the trained file is covered. See [third-party notices](../THIRD_PARTY_NOTICES.md). The trusted artifact source and access policy for a future GitHub Actions runner also remain to be selected. Do not publish until those gates and explicit first-push approval are satisfied.
