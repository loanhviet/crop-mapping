# Oracle A1 ARM64 deployment

This guide prepares a separate Crop Mapping service on an Ubuntu 24.04
VM.Standard.A1.Flex (4 OCPU, 24 GB RAM, approximately 200 GB boot volume).
It does not authorize deployment. See [the handoff](DEPLOYMENT_HANDOFF.md) for
actual verification.

> **Update (CD):** routine updates no longer build on the VM. [`cd.yml`](CD.md)
> builds `runtime` on a native ARM64 GitHub runner, pushes it to
> `ghcr.io/loanhviet/crop-mapping` and deploys the digest with health check and
> rollback. Use this runbook for preflight, asset provisioning, Caddy and the
> one-time bootstrap ([CD.md › Bootstrap](CD.md#bootstrap-the-vm-manual-once-needs-approval));
> the VM build commands below are an emergency fallback only.
> DNS: `crop.loanhviet.dev` A → `140.245.121.130` already exists (same VM as
> OpenDubber); HTTPS answers only after the Caddy site block is merged.

## Architecture and audit findings

Host Caddy terminates HTTPS for `crop.loanhviet.dev` and forwards the UI and
same-origin `/api/*` requests to `127.0.0.1:18080`. One unprivileged Uvicorn worker
serves FastAPI and static `web/` files; there is no Node frontend build or second
API port. Inference uses one bounded background worker and CPU PyTorch. The
container has its own Compose project/network, read-only imagery/weights binds,
and a writable results volume. OpenDubber and Caddy are managed separately.

The old Dockerfile explicitly rejected ARM64 and installed only the AMD64 lock.
It now selects a hash-locked binary-only dependency set using BuildKit TARGETARCH.
Both locks retain Python 3.13, torch 2.14.1+cpu and the same 35 package versions.
The pinned Python 3.13.18 Bookworm index contains both architectures. Ubuntu's
host Python is irrelevant to container execution. Rasterio/PROJ native libraries
must be validated on ARM64; they come from wheels, with libexpat1 installed by APT.
There is no CUDA dependency or GPU device mapping. The build asserts
`torch.version.cuda is None`. PyTorch documents CPU installation at its
[official installation page](https://pytorch.org/get-started/locally/); actual
artifact compatibility must still be checked for the exact Python/platform lock.

The legacy `release` target bundles a 6.7 MB verified checkpoint for existing
EC2 releases. OCI builds `runtime`, excludes weights/data/results/secrets from
the build context and mounts weights externally. The old Docker Hub publish and
EC2 deploy workflows were removed in favour of `cd.yml`. `scripts/build_image.sh`
still builds the legacy AMD64 release target locally; do not use it for OCI.
CI includes an ARM64 runner build and native library/tensor smoke;
it does not provision private model assets or prove full model inference.

The prepared source mode needs local raw time series, catalog metadata and
quality masks. Prediction-only bundles are rejected. GEODES acquisition is not
needed in production; no API key is required. Browser basemap tiles still need
external network access. Model loading uses CPU map_location, weights_only=True
and strict state dict matching. Startup now fails with a clear integrity error
before torch.load if checkpoint bytes or tracked configuration differ.

## Prerequisites and isolation review

Use a reviewed checkout on the VM, Docker Engine with Compose >= 2.24.4
(`!override` is used), and an ARM64-capable Buildx builder. Review the host's
existing container names, ports, volume names, free disk/RAM and Caddy topology
before starting anything. The commands below run on the target **only after
separate deployment authorization**. Do not stop/recreate OpenDubber, install a
second proxy, prune shared Docker resources or change the daemon configuration.
Builds are not covered by service resource limits: build during a quiet window
or on a separate native ARM64 builder if OpenDubber has insufficient headroom.

```bash
uname -m  # expected aarch64
docker version
docker compose version
docker buildx ls
docker ps --format 'table {{.Names}}\t{{.Ports}}\t{{.Status}}'
ss -ltn | rg ':18080\b'  # must be unused; choose another port if occupied
free -h
df -h
docker system df
```

## Configuration

From the repository root, create the ignored deployment environment once:

```bash
test ! -e .env.oracle && cp deployment/oracle.env.example .env.oracle
chmod 600 .env.oracle
```

Edit it with absolute data/weights paths, a unique local candidate image tag and
the chosen port. Never overwrite the environment during an update.

| Key | OCI purpose/default |
| --- | --- |
| CROP_IMAGE | `ghcr.io/loanhviet/crop-mapping@sha256:…` (CD rewrites it). Emergency VM build only: a unique local tag such as crop-mapping:oracle-local-001 |
| CROP_PORT | Host loopback port 18080; match the Caddy upstream |
| CROP_DATA_DIR | Existing host imagery directory; mounted read-only at /app/data |
| CROP_WEIGHTS_DIR | Existing host weights directory; mounted read-only at /app/weights |
| CROP_RESULTS_VOLUME | Fresh default in template: crop-mapping-oracle-results |
| CROP_THREADS | 2 PyTorch/OpenMP/BLAS threads |
| CROP_CPUS | 2 CPU quota, leaving shared capacity |
| CROP_MEMORY_LIMIT | 2g service ceiling; measure before increasing |

The overlay forces `CROP_DEVICE=cpu`, `CROP_SOURCE=prepared` (inherited), and
loopback binding even if unrelated shell settings specify CUDA/public binding.
Compose shell exports override env-file values: review the rendered config.
Container data/weights/results paths remain fixed. There are no credentials or
server IPs in the templates. CPU/memory limits do not reserve capacity for
OpenDubber. The inherited PID limit is 256; logs rotate at 10 MB × 3 files.
The container has read-only root, a 64 MB temporary filesystem, dropped
capabilities, UID/GID 10001 and no-new-privileges.

On migrations, preserve the actual results volume name. The provisioned local
workspace uses `crop-map_results`; do not change its ignored `.env` or replace
its data with a new volume. A fresh OCI installation uses a separate volume.
Never run two instances against the same writable results volume.

## Model and imagery preparation

The manifest has **no verified direct download URL**. Obtain the exact file from
the trusted maintainer or authorized versioned artifact store; record the object
version and compare it to `assets/model-manifest.json`. Do not guess a URL,
retrain or accept substituted weights. Existing GitHub publication uses a private
release asset ID and read token; do not trigger that pipeline for this deployment.

Provision host `weights/best.pth`, matching `weights/config.yaml` and license.
The checkpoint must be 6,665,903 bytes with SHA256
`92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733`.
Preserve manifests unchanged. See [ASSETS.md](ASSETS.md) for PASTIS/Normandy
preparation and required dataset layout. Transfer catalogs, raw arrays and masks
together and retain their provenance/hashes. Approximately 8.1 GiB imagery is
present in the local workspace; the VM has not been checked or provisioned.
Do not copy `.venv` from AMD64 to ARM64.

With a provisioned native environment, verification uses:

```bash
.venv/bin/python scripts/verify_assets.py --profile ci
```

Without a native environment, the runtime image can perform the model check
without starting a service (after the build below):

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml run --rm --no-deps crop-map python scripts/verify_assets.py --profile ci
```

The CI profile requires demo fixtures 10000/10003; use `--profile model` for a
production imagery bundle without those fixtures, then validate its catalog and
run smoke inference with an installed raw-data patch. Check host directory
traversal/read permissions for UID 10001. Fresh named results volumes inherit
image ownership; existing volumes must already be writable by UID/GID 10001.
Inspect and back up an existing volume before adjusting its ownership.

## Build and start on the VM (emergency fallback; normal path is CD)

Always supply both Compose files and the explicit env-file. The OCI project
name is `crop-mapping-oracle`; do not override it with OpenDubber's project name.
On the native ARM64 VM no QEMU is needed. Docker selects ARM64 automatically.

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml config --quiet
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml build --pull crop-map
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml run --rm --no-deps crop-map python scripts/verify_assets.py --profile model
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml up -d --no-build --wait --wait-timeout 180 crop-map
```

No image is pulled by `up` or published; the overlay uses `pull_policy: never`.
The build downloads the pinned base and hash-checked wheels. Images contain no
checkpoint. A missing bind source fails immediately, and missing/corrupt model
files prevent readiness. `unless-stopped` restarts after daemon/VM reboot if
Docker is enabled and host assets are mounted before Docker starts. For external
filesystems, arrange mount ordering before enabling automatic startup. The boot
volume paths need no network artifact download. An unhealthy container is not
automatically restarted by Docker: diagnose the failure instead of restart loops.

Cross-platform build on a separately configured builder (never publish):

```bash
docker buildx build --platform linux/arm64 --target runtime --load -t crop-mapping:arm64-candidate .
docker buildx build --platform linux/amd64 --target runtime --load -t crop-mapping:amd64-candidate .
```

An AMD64 builder requires QEMU/binfmt or a native ARM node to execute ARM64 RUN
steps. Do not install privileged emulation into the shared production daemon as
part of this guide. A multi-platform OCI layout can be exported to a local OCI
archive on a docker-container builder with `--platform linux/amd64,linux/arm64
--output type=oci,dest=...`; a successful build still needs native runtime tests.

## Health and real inference

```bash
curl --fail --silent --show-error http://127.0.0.1:18080/api/health
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml ps
```

Expect status `ok`, device `cpu`, the manifest checkpoint SHA256, prepared source
and available regions. Confirm the UI and `/api/catalog`. Health proves startup,
not model prediction. With the repository's provisioned native environment:

```bash
.venv/bin/python scripts/container_smoke.py --url http://127.0.0.1:18080 --patch-id 10003 --timeout 300 --output .validation/oracle-smoke-001
```

Or run the existing smoke script inside the running container without installing
host Python dependencies:

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml exec -T crop-map python -c 'import sys; exec(compile(sys.stdin.read(), "/app/scripts/container_smoke.py", "exec"), {"__name__": "__main__", "__file__": "/app/scripts/container_smoke.py"})' --url http://127.0.0.1:8000 --patch-id 10003 --timeout 300 --output /tmp/oracle-smoke-001 < scripts/container_smoke.py
```

Use a new output directory each run. It submits two fresh small inferences,
checks checkpoint identity, class counts, a pixel and TIFF/CSV/PNG/GeoJSON/ZIP
exports. Pick an installed patch instead of 10003 where necessary. Retain
native ARM64 smoke evidence, peak memory and timing before declaring readiness.
After a controlled restart, recheck health and an existing result download;
interrupted jobs are marked as errors by startup recovery.

## DNS and Caddy (separate reviewed production change)

`deployment/Caddyfile.oracle.example` is an example for **host-installed Caddy**.
Review the active Caddyfile/import structure, merge only this site block, validate
the complete candidate configuration and reload only after approval. Never
replace the active configuration with the example or start another Caddy.

If Caddy is containerized, its `127.0.0.1` is not the VM loopback: this upstream
will not work unless it already uses host networking. Review its existing network
arrangement before deployment; a shared private Docker network and service-name
upstream would require a separate reviewed configuration change. Do not expose
port 18080 publicly to work around this.

After approval, create the DNS A record to the VM's public IPv4. Add AAAA only
if IPv6 is configured and reachable. OCI NSG/security-list and Ubuntu firewall
must already permit HTTP/HTTPS to Caddy; keep the application port private.
[Automatic HTTPS](https://caddyserver.com/docs/automatic-https) requires correct
DNS and reachability. Validate the complete Caddy config using its existing
installation and paths, e.g. `caddy validate --config /path/to/candidate/Caddyfile
--adapter caddyfile`. Reload using the existing service management procedure;
verify both OpenDubber and `https://crop.loanhviet.dev/api/health` afterward.
No DNS, firewall or live proxy changes were performed in this preparation.

## Operations and rollback

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml logs --tail=100 -f crop-map
docker stats --no-stream
free -h
df -h
docker system df
```

Monitor inference latency, OOMKilled state, PIDs, disk growth in results and
shared host pressure. Results currently have no automatic retention policy:
back up and manage them deliberately. Do not run global Docker prune or
`compose down -v`. A quota limits service pressure but cannot guarantee
OpenDubber performance under simultaneous builds or inference workloads.

Before updating, save `.env.oracle` privately, record the image ID/tag and actual
mount/volume names, and back up results consistently while writes are stopped.
Keep previous image tags; do not rebuild a previous tag. Keep the prior matching
asset bundle if changing assets. To roll back, restore the previous CROP_IMAGE
in `.env.oracle` and, if changed, its matching host asset paths. Then:

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml up -d --no-build --force-recreate --wait --wait-timeout 180 crop-map
curl --fail http://127.0.0.1:18080/api/health
```

Re-run the inference smoke and verify earlier result downloads. Never remove
results to make rollback pass. Caddy/DNS generally need no change for application
rollback. Rehearse on an isolated project/volume before a production update.

## Troubleshooting

- `exec format error`: inspect image architecture and builder platforms; build
  natively on A1 or use a configured ARM64 builder. Renaming an AMD64 tag does not
  convert it. Do not force `platform: linux/amd64` on A1.
- No matching distribution/hash mismatch: retain Python 3.13 and the correct
  architecture lock; check official wheel availability/proxy caches. Never
  disable hashes or fall back to unreviewed source builds on the shared VM.
- Illegal instruction/import errors: capture `uname -m`, image architecture,
  torch/rasterio/pyproj versions and native CPU smoke. Wheel resolution/build
  success alone does not establish native kernel compatibility.
- Integrity errors: provision the exact manifest-pinned weights/config, check
  the mount path and permissions. Do not edit the expected hash to bypass errors.
- No prepared imagery/prediction-only error: transfer the complete live imagery
  bundle, including catalog-referenced children and masks; do not symlink outside
  the data root. The application intentionally fails startup without usable data.
- OOM/unhealthy: inspect logs and `docker inspect` state, test a small AOI, measure
  memory before raising limits on the shared host. Keep one Uvicorn worker.
- Bind failure: select an unused loopback port and update the Caddy example.
- HTTPS 502 with containerized Caddy: review network topology as above.
- Restart errors: inspect persistent status files, writable results permissions
  and mount ordering. Restart policy cannot repair missing assets.
