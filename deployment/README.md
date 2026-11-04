# Deployment entry points

For Oracle A1 ARM64, use [the OCI guide](../docs/ORACLE_ARM64_DEPLOYMENT.md)
and [CD](../docs/CD.md). `cd.yml` builds the ARM64 runtime image on a GitHub
runner, pushes it to GHCR and runs `deploy.py` on the VM over SSH (health check
and rollback). The OCI Compose overlay mounts verified weights outside the image.
The former Docker Hub publish and EC2 deploy workflows were removed.

## Historical EC2 deployment context

The local Compose is preserved. Phase 2 pins the Docker base/frontend and installs hash-locked runtime wheels for CPU AMD64; see [container workflow](../docs/CONTAINERS.md). Local image tag: `crop-map:prepared`; build context: repository root. CPU inference only in the supplied image. Health calls `/api/health`; actual Phase 2 execution status is recorded in [container validation](../docs/CONTAINER_VALIDATION.md).

Before using an existing EC2 installation, record its actual image/digest, architecture, Compose project name, data/weights bind sources, results volume, port overrides and asset versions. EC2 was previously deployed according to the owner; this migration did not contact it. A renamed checkout can select a different Compose project/volume. Do not infer the existing volume name from the new directory name.

For local setup see [README](../README.md) and [external assets](../docs/ASSETS.md). Missing raw imagery or weights prevents startup. New named volumes inherit intended results permissions; separately verify existing volume permissions for UID 10001. Keep completed results backed up; do not use `down -v` to update an installation.

Supplied Compose exposes localhost by default. Public production needs a deliberate reverse-proxy/TLS/access-control configuration. Do not assume these controls exist on EC2 or Oracle without inspection. The current root configuration has no registry update automation, deployment script or rollback mechanism.

Future Oracle ARM64 work belongs on the branches in [branch strategy](../docs/BRANCHING.md). Keep production image selection separate from local `build: .`; preserve stable mounts/results identity. Test health plus a small real inference before accepting a release, then exercise rollback and backup restore with isolated volumes.

Portable pull-only configuration: `compose.production.yaml`, with `deployment/production.env.example`. No platform is forced. The default registry reference is deliberately unpublished until an approved release exists.

Release target packages best.pth and model config, with hash checks before and inside Docker. Production no longer mounts host weights; only imagery and results are external. Local development Compose remains unchanged. Checkpoint redistribution is a publication gate, not an assumed right.

Manual Phase 4 CD: see [EC2 deployment and rollback](../docs/CD.md). The workflow requires a verified digest, pinned SSH host key and existing production state; it does not deploy during local validation.
