# GitHub Actions CI

`ci.yml` runs on pull requests, on pushes to branches other than `main`, and as
the first stage of [CD](CD.md) (`workflow_call`) for every push to `main`.

| Job | Runner | Checks |
| --- | --- | --- |
| `regression` | `ubuntu-24.04` | Hash-locked AMD64 runtime install + `pip check`; pytest excluding `external_assets`; development, production and Oracle Compose configurations; Dockerfile `--check` |
| `arm64-runtime` | `ubuntu-24.04-arm` (native) | Builds the `runtime` target for `linux/arm64`; runs `aarch64`, CPU-only torch, Rasterio/pyproj imports and a tensor product with `--network none` |

The ARM64 build writes BuildKit layers to the GitHub Actions cache
(`scope=arm64-runtime`); the CD build job reads the same scope, so the image it
pushes reuses the layers CI just tested. Pull-request caches are scoped to the
PR ref and cannot be read by `main`.

CI has no checkpoint or satellite fixtures, so asset-dependent tests and real
inference are not run there. Run the full suite locally with provisioned assets:

```bash
.venv/bin/python -m pytest --require-assets -q
```

No secrets are used by CI. Image publication and deployment are part of
[CD](CD.md); the former manual Docker Hub `publish.yml` has been removed.
