# Deployment compatibility and future work

The supplied root Dockerfile and Compose are unchanged from the working application's source. Local image tag: `crop-map:prepared`; build context: repository root. CPU inference only in the supplied image. Health calls `/api/health`; no image or container was built/run during migration.

Before using an existing EC2 installation, record its actual image/digest, architecture, Compose project name, data/weights bind sources, results volume, port overrides and asset versions. EC2 was previously deployed according to the owner; this migration did not contact it. A renamed checkout can select a different Compose project/volume. Do not infer the existing volume name from the new directory name.

For local setup see [README](../README.md) and [external assets](../docs/ASSETS.md). Missing raw imagery or weights prevents startup. New named volumes inherit intended results permissions; separately verify existing volume permissions for UID 10001. Keep completed results backed up; do not use `down -v` to update an installation.

Supplied Compose exposes localhost by default. Public production needs a deliberate reverse-proxy/TLS/access-control configuration. Do not assume these controls exist on EC2 or Oracle without inspection. The current root configuration has no registry update automation, deployment script or rollback mechanism.

Future Oracle ARM64 work belongs on the branches in [branch strategy](../docs/BRANCHING.md). Keep production image selection separate from local `build: .`; preserve stable mounts/results identity. Test health plus a small real inference before accepting a release, then exercise rollback and backup restore with isolated volumes.
