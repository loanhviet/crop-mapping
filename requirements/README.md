# CPU AMD64 runtime dependency lock

Direct runtime versions are unchanged. Pytest 9.1.1 moved to `requirements-dev.txt`.
The Dockerfile installs `locks/linux-amd64.txt` using `--require-hashes` and binary
wheels only. CPU torch keeps the explicit `+cpu` version suffix; build verifies
that CUDA is not compiled in. This phase does not build or validate ARM64 images.

Generated using uv 0.12.2:

```bash
uv pip compile requirements.txt --python-version 3.13 --python-platform x86_64-manylinux_2_28 --only-binary :all: --generate-hashes --emit-index-url --index-strategy unsafe-best-match --output-file requirements/locks/linux-amd64.txt
```

Regeneration can update transitive versions and must be reviewed/tested. The lock
may include multiple distribution hashes, but pip selects target-compatible wheels.
Python 3.13.18 Bookworm and the Dockerfile frontend are pinned by index digest.
Bookworm glibc 2.36 satisfies the wheel baseline. Rasterio wheels bundle GDAL;
libexpat1 is installed without system GDAL build tools. APT uses the live Bookworm
repository: Python artifact identity is locked, not every future OS package byte.
