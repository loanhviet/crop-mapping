# OCI ARM64 deployment handoff

Prepared locally on 2026-11-04. **Ready for native ARM64 acceptance testing;
not yet accepted for production deployment.** No SSH, OCI deployment, production
service changes, DNS changes, registry pushes or Git commits were performed.

## Scope and files

- `Dockerfile`: selects hash-locked CPU wheels for AMD64/ARM64; runtime includes
  the shared asset verifier, model manifest and tracked configuration. The OCI
  runtime target excludes checkpoint binaries; legacy EC2 release target remains.
- `requirements/locks/linux-arm64.txt`: generated with uv 0.12.2, Python 3.13,
  aarch64 manylinux_2_28, constrained to the existing AMD64 versions. All 35
  package versions are identical to AMD64. AMD64 lock is unchanged.
- `.dockerignore`: permits ARM lock and only the required verifier script;
  data, secrets, local environments and checkpoints remain excluded.
- `inference.py`: verifies model bytes/hash and configuration hash before
  deserialization; missing/corrupt assets now produce a clear startup error.
- `compose.oracle.yaml`: overlay on existing production Compose, separate OCI
  project, local runtime build, read-only external weights, forced CPU,
  loopback-only port 18080, bounded BLAS threads/GDAL cache. Inherits restart,
  security, health, PID/log/CPU/memory limits and persistent results.
- `deployment/oracle.env.example`, `.env.example`: documented OCI variables;
  the ignored local `.env` and its actual results-volume setting are untouched.
- `deployment/Caddyfile.oracle.example`: proposed host-Caddy site only; no live
  proxy configuration was accessed or modified.
- `.github/workflows/ci.yml`: validates OCI Compose and adds native ARM64
  runtime build/library/tensor smoke. Added job has not run on GitHub.
- `tests/test_oracle_deployment.py`: isolation/volume override and pre-load
  rejection regressions. Synthetic assets make these tests independent of weights.
- `requirements/README.md`, `deployment/README.md`, `docs/ASSETS.md`, and
  `docs/ORACLE_ARM64_DEPLOYMENT.md`: compatibility, asset lifecycle and runbook.

The checkout already contained modified README, development Compose, container
notes and production Compose tests, plus untracked local-transition/report
files. Those pre-existing changes were preserved; they are not part of the
OCI preparation. No model manifest, configuration, dataset or model weights
were modified. No compatibility aliases in `../crop-map` were changed.

## Executed verification

| Check | Actual result |
| --- | --- |
| Native host | Linux x86_64; Docker default builder advertises AMD64 only |
| Provisioned environment | `uv pip check --python .venv/bin/python` passed, 40 installed packages |
| Asset verification | `.venv/bin/python scripts/verify_assets.py --profile ci` passed |
| Existing suite before edits | 46 passed, 1 Starlette/httpx deprecation warning |
| Final full suite | `.venv/bin/python -m pytest --require-assets -q`: 50 passed, 1 warning, 8.73 seconds |
| Suite without external assets | 39 passed, 11 deselected, 1 warning, 1.56 seconds |
| Compose parsing | Development, legacy production and combined OCI configuration passed |
| Dockerfile check | Buildx `--check --platform linux/amd64,linux/arm64 --target runtime` passed without warnings; static check only |
| Python base identity | Pinned index inspected; linux/amd64 and linux/arm64/v8 descriptors present |
| ARM dependencies | Cross-platform uv resolution and installation into ignored `.validation/oracle-arm64-dependencies` passed with binary-only and hash enforcement; 35 packages downloaded/installed without executing them |
| ARM native library identity | torch, Rasterio, pyproj, NumPy ELF headers report e_machine 183 (AArch64); no imports executed |
| AMD64 runtime build | Buildx runtime build/load passed; local tag `crop-mapping:oracle-validation`, inspect size 1,719,148,501 bytes (Docker-reported uncompressed size) |
| AMD64 libraries | CPU-only torch 2.14.1+cpu, Rasterio 1.5.2, pyproj 3.8.0 imports and tensor multiplication passed |
| AMD64 OCI startup | Started with read-only mounts/root, UID 10001, 2 CPU/2 GiB limit, private port 18089 and a new isolated test volume; Docker health became healthy |
| Health | cpu, expected checkpoint SHA256, 19 patches and 9 available regions |
| Real HTTP inference | Existing container_smoke.py passed: two fresh small patch-10003 inferences; pixel, class totals and TIFF/CSV/PNG/GeoJSON/ZIP exports verified |
| Documented container smoke wrapper | Also executed successfully without host runtime dependencies; two more fresh inferences |
| Container restart | Restart succeeded; existing completed job remained done and ZIP bytes matched before restart |
| Missing checkpoint | Image with no model mount rejected Engine initialization with `Model asset verification failed: Missing checkpoint...`; nonzero exit expected |
| Runtime resource sample | About 406 MiB / 2 GiB during smoke, 7 PIDs, no OOMKilled; a sample, not peak-load evidence |
| Actual ARM64 build attempt | Failed at first RUN with `exec /bin/sh: exec format error`; local builder has no ARM64 emulation/native node |
| Git whitespace check | `git diff --check` passed |

**Verified working:** local AMD64 dependency imports, container startup/health,
real inference/exports, checksum failure handling and results after restart.

**Build-verified but not runtime-tested:** no ARM64 application image belongs in
this category. ARM64 was only dependency-artifact/static-config verified; its
full build did not complete. The new native CI job has not run.

**Not yet verified:** full ARM64 image build, native A1 imports/model inference,
performance and larger-AOI memory; actual VM asset provisioning and reboot;
Caddy configuration validation/reload, DNS/TLS, rollback rehearsal, results
backup/restore and OpenDubber coexistence under realistic concurrent load.
No Caddy binary was available locally for configuration validation.

Ignored evidence includes `.validation/oracle-container-smoke-20261104/` and
`.validation/oracle-preparation-20261104/`. The latter stores build/test logs,
rendered OCI config, resource notes and restart verification. The isolated test
container/network were removed after validation; production and original local
results volumes were not touched. The local validation image is retained.

## Remaining blockers and risks for Claude Code

1. Obtain separate authorization before server access or deployment. This task
   did not authorize SSH, DNS or production changes.
2. Review the complete diff alongside the pre-existing worktree changes. Select
   a reviewed source revision and unique image tag; no commit was created here.
3. On a native A1 or separate native ARM64 runner, build runtime, execute CPU
   library checks, provision the manifest-exact checkpoint/raw imagery and run
   health plus fresh inference/export smoke. A passing build alone is insufficient.
   Confirm the GitHub ARM64 runner is available to this repository before relying
   on the added CI job; do not trigger the old publish/EC2 deploy workflows.
4. Inspect OpenDubber usage, existing ports, Docker capacity, Compose version,
   actual volume names and Caddy topology. The example requires host-installed
   Caddy (or existing host networking); containerized Caddy needs network review.
   Build-time CPU/RAM are not bounded by service limits.
5. Provision model/data on the VM. There is no verified public checkpoint URL;
   use a trusted artifact/version and unchanged manifest checksums. Model/data
   are present locally only. Check UID 10001 readability and results writability.
6. Review full Caddy candidate config, DNS A/AAAA and existing OCI/host rules,
   then separately authorize changes. No public application-port rule is needed.
7. Measure representative ARM inference and shared-host load, rehearse rollback
   and backup/restore, confirm Docker boot enablement and asset mount ordering.
   Restart recovery passed locally, but a VM reboot was not performed.
8. The 2 GiB cap and small-AOI resource sample are conservative starting points.
   Results have no automatic retention. Manage disk growth, preserve image tags
   for rollback, and do not globally prune the shared Docker daemon.

## Exact final deployment sequence (after authorization)

See [the full runbook](ORACLE_ARM64_DEPLOYMENT.md) for preflight, provisioning,
proxy, DNS, rollback and troubleshooting. From the reviewed checkout on the VM:

```bash
# Create only once; then edit paths, unique candidate tag, port and volume identity.
test ! -e .env.oracle && cp deployment/oracle.env.example .env.oracle
chmod 600 .env.oracle
# Provision weights/data and review .env.oracle before continuing.
uname -m  # must be aarch64

docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml config --quiet
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml build --pull crop-map
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml run --rm --no-deps crop-map python -c 'import platform,torch,rasterio,pyproj; assert platform.machine()=="aarch64"; assert torch.version.cuda is None; assert (torch.ones(2,2) @ torch.ones(2,2)).sum().item()==8; print(torch.__version__,rasterio.__version__,pyproj.__version__)'
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml run --rm --no-deps crop-map python scripts/verify_assets.py --profile model
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml up -d --no-build --wait --wait-timeout 180 crop-map
curl --fail --silent --show-error http://127.0.0.1:18080/api/health

docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml exec -T crop-map python -c 'import sys; exec(compile(sys.stdin.read(), "/app/scripts/container_smoke.py", "exec"), {"__name__": "__main__", "__file__": "/app/scripts/container_smoke.py"})' --url http://127.0.0.1:8000 --patch-id 10003 --timeout 300 --output /tmp/oracle-smoke-001 < scripts/container_smoke.py

docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml logs --tail=100 crop-map
docker stats --no-stream
```

If port/patch differ, substitute the reviewed configured values. Record native
ARM64 results before accepting the deployment. Merge the example site block into
the existing Caddy configuration only under separate approval; validate the
complete candidate before using the existing Caddy reload procedure. The exact
live Caddy path/topology remains unknown, so no guessed reload command is given.
After approved DNS/proxy changes, verify both OpenDubber and:

```bash
curl --fail --silent --show-error https://crop.loanhviet.dev/api/health
```

Retain the previous environment and image tag. For rollback, restore the previous
`CROP_IMAGE`/asset paths in `.env.oracle` and run:

```bash
docker compose --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml up -d --no-build --force-recreate --wait --wait-timeout 180 crop-map
curl --fail http://127.0.0.1:18080/api/health
```

Re-run inference and check preserved result downloads. Do not run `down -v`.
