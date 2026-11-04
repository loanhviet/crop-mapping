# CPU runtime dependency locks

Direct runtime versions are unchanged. Pytest 9.1.1 moved to `requirements-dev.txt`.
The Dockerfile selects `locks/linux-${TARGETARCH}.txt` using `--require-hashes` and binary
wheels only. CPU torch keeps the explicit `+cpu` version suffix; build verifies
that CUDA is not compiled in. The OCI runtime also selects `locks/linux-arm64.txt` for ARM64. Availability of wheels does not prove native inference compatibility.

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

ARM64 lock generation preserves all existing direct and transitive versions:

```bash
uv pip compile requirements.txt --constraint requirements/locks/linux-amd64.txt --python-version 3.13 --python-platform aarch64-manylinux_2_28 --only-binary :all: --generate-hashes --emit-index-url --index-strategy unsafe-best-match --output-file requirements/locks/linux-arm64.txt
```

The pinned Python image index includes AMD64 and ARM64. ARM wheels require
manylinux glibc baselines satisfied by Debian Bookworm inside the Ubuntu host.
The CPU-only check runs during each architecture's build. See
[OCI deployment](../docs/ORACLE_ARM64_DEPLOYMENT.md) and its handoff for actual
validation results. Keep the AMD64 lock unchanged when regenerating ARM64.
