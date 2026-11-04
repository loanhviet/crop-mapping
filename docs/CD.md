# CD: automatic update of the Oracle A1 deployment

`.github/workflows/cd.yml` turns every push to `main` into:

```text
push main ─► CI (ci.yml: pytest, Compose, Dockerfile, native ARM64 build+smoke)
          ─► build: native ubuntu-24.04-arm runner, Dockerfile target `runtime`
                     push ghcr.io/loanhviet/crop-mapping:sha-<commit>  (deployed by @sha256 digest)
          ─► deploy: SSH (pinned host key) → deployment/deploy.py on the VM
                     pull digest → verify arm64 + revision label → compose up --wait
                     → container healthy + /api/health checkpoint SHA256 + mounts unchanged
                     → on any failure: restore previous digest and verify it
```

The VM never builds anything, so OpenDubber only sees a layer pull and a
single-container recreate. The image contains no checkpoint, imagery, results
or secrets: weights and data stay on the VM as read-only binds.

**Auto-deploy is off by default.** The `deploy` job runs only when the
repository variable `ORACLE_AUTO_DEPLOY` is `true`, or for a manual
*Run workflow* with **deploy** ticked. Until then a push to `main` runs CI and
publishes the GHCR image only. Docs-only pushes (`docs/**`, `*.md`) skip CD.

## What was removed and why

| Removed | Reason |
| --- | --- |
| `publish.yml` (Docker Hub AMD64 release with baked checkpoint) | Publishing is now one step inside CD; Oracle is ARM64 and mounts weights |
| `deploy.yml` (manual EC2 deploy, manual Security Group /32 per run) | Replaced by `cd.yml`; the manual allowlist step made unattended CD impossible |
| CI on `push` to `main` | `cd.yml` calls `ci.yml` itself; avoids running CI twice per push |

`deployment/deploy.py` keeps its tested transaction (lock, pull-before-swap,
pending/last-success state, rollback) and was retargeted to Oracle:
GHCR digest, `arm64`, project `crop-mapping-oracle`, `.env.oracle`, both
Compose files, read-only data **and** weights binds, loopback port from Compose.
The Dockerfile `release` target and `scripts/build_image.sh` remain for local
AMD64 builds; no workflow uses them.

## Safety properties

- **Concurrency:** one workflow-level group, `cancel-in-progress: false`.
  Runs execute in push order; a newer pending run replaces older pending ones;
  a running deployment is never cancelled. On the VM, `deploy.py` also takes an
  exclusive `flock` and refuses to overlap a deployment already in progress.
- **No old-over-new:** right before SSH, the deploy job refuses (skips with a
  warning) if `main` has moved on with newer *deployable* changes, or if the commit
  is no longer an ancestor of `main`. This covers re-runs of old runs. Newer
  docs-only commits do not count, because they never trigger CD.
- **Only after CI passes:** `build` needs the reusable `ci` job and `deploy` needs
  `build`; both have the implicit `success()` condition, so any CI failure stops CD.
- **Immutability:** deploy uses the digest returned by the build job, never a tag.
- **Fail closed before changing anything:** Compose files on the VM must hash to
  the commit's `compose.production.yaml` + `compose.oracle.yaml`; mounts, results
  volume name and loopback port must match the running container; candidate must
  be `linux/arm64` with the commit's `org.opencontainers.image.revision` label.
- **Rollback:** if `up --wait` (180 s), health, image identity, mounts or the
  checkpoint SHA256 check fails, the previous digest is restarted and verified.
  If rollback itself fails the job reports `ROLLBACK FAILED` and leaves
  `.deployment/pending.json` with the previous digest for manual recovery.
  Rollback runs even if the SSH session dropped (the job was cancelled or timed out):
  output happens only after the restore.
  *Rehearsed with real Docker/Compose (local AMD64, separate project/volume):*
  v0→v1 succeeded in 8 s; a release whose container exits was detected by
  `up --wait` and v1 was restored and re-verified (`.env.oracle` unchanged);
  a wrong-architecture image was refused before any change.
- **Secrets:** SSH material lives only in the `oracle` environment (restricted to
  `main`); the key file is mode 600 in `$RUNNER_TEMP` and deleted on exit. GHCR
  push uses the job's short-lived `GITHUB_TOKEN` (`packages: write` only on the
  build job). No registry credential exists on the VM if the package is public.
- **Supply chain:** third-party Docker actions are pinned to commit SHAs.
- **Isolation from OpenDubber:** separate Compose project/network/volume; only
  service `crop-map` of project `crop-mapping-oracle` is touched; no `prune`,
  no `down -v`, no daemon or Caddy change; loopback-only port; 2 CPU / 2 GiB /
  256 PID caps; no build on the VM; pull refused if the Docker filesystem has
  < 5 GiB free.

Known limits: a deploy recreates the single container, so the site is briefly
down while it starts (8 s in the local rehearsal; not yet measured on A1).
The first pull and any dependency-lock change download ~1–2 GB once, which
briefly uses VM bandwidth/IO next to OpenDubber. Two instances must
not share the results volume, so no blue/green. Old images are kept for
rollback; delete only `ghcr.io/loanhviet/crop-mapping` images you no longer need.

## One-time setup (owner)

### 1. GitHub environment `oracle`

Settings → Environments → **New environment** `oracle`. Create it *before* the
first deploy: if a deploy job runs first, GitHub auto-creates the environment
without any branch restriction.

- Deployment branches and tags → **Selected branches** → `main`.
- Optional: *Required reviewers* = yourself, if every deploy should wait for a click.
- **Environment secrets:**

| Secret | Value |
| --- | --- |
| `ORACLE_HOST` | VM public IPv4 or DNS name used for SSH (not behind a proxy) |
| `ORACLE_USER` | `ubuntu` |
| `ORACLE_SSH_PRIVATE_KEY` | The *dedicated* CD private key (full text incl. header/footer, no passphrase) |
| `ORACLE_KNOWN_HOSTS` | Verified known_hosts line(s) for the VM, e.g. from your existing `~/.ssh/known_hosts` |

- **Environment variables (optional):** `ORACLE_SSH_PORT` (default `22`),
  `ORACLE_APP_DIR` (default `/home/ubuntu/crop-mapping`).

Create the key locally, never reuse your personal Oracle key:

```bash
ssh-keygen -t ed25519 -N '' -C crop-mapping-oracle-cd -f ~/.ssh/crop-mapping-oracle-cd
# On the VM, append the PUBLIC key to ~ubuntu/.ssh/authorized_keys with restrictions:
#   restrict ssh-ed25519 AAAA... crop-mapping-oracle-cd
# Known hosts (verify the fingerprint against the OCI console / your trusted session):
ssh-keygen -F <VM_IP> -f ~/.ssh/known_hosts      # copy the matching line(s)
```

`restrict` disables forwarding/PTY. The key can still run commands as `ubuntu`,
which has `sudo -n docker` (root-equivalent): treat it as a production root key,
rotate it if leaked, and review workflow changes on `main`.

### 2. Repository variable (activation switch)

Settings → Secrets and variables → Actions → **Variables** →
`ORACLE_AUTO_DEPLOY` = `true` **only after the bootstrap below is verified.**
Delete it (or set `false`) to pause auto-deploy instantly.

### 3. Network

GitHub-hosted runner IPs change, so OCI must allow TCP 22 from the internet for
unattended deploys (the default OCI security list does). Keep SSH key-only
(`PasswordAuthentication no`, default on Oracle Ubuntu images); app port 18080
stays loopback-only behind Caddy. If you want SSH closed to the internet later,
put the runner on a private network (e.g. Tailscale action) — not needed now.

### 4. Old secrets no longer used by any workflow

`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN`, `CHECKPOINT_READ_TOKEN`,
`CHECKPOINT_REPOSITORY`, `CHECKPOINT_ASSET_ID` and the `production`
environment's `EC2_*` secrets. Remove them once the EC2 host is retired.

## Bootstrap the VM (manual, once, needs approval)

CD updates an existing deployment; it refuses to create the first container.

1. On the VM, create `/home/ubuntu/crop-mapping/` containing the commit's
   `compose.production.yaml` and `compose.oracle.yaml`, `.env.oracle` (from
   `deployment/oracle.env.example`, `chmod 600`, absolute `CROP_DATA_DIR` /
   `CROP_WEIGHTS_DIR`), `data/` and `weights/` (`best.pth`, `config.yaml`,
   `LICENSE.txt`). See [ORACLE_ARM64_DEPLOYMENT.md](ORACLE_ARM64_DEPLOYMENT.md)
   for asset checks, port/volume preflight and Caddy.
2. Actions → **CD Oracle** → Run workflow on `main`, *deploy* unticked. The
   summary shows `ghcr.io/loanhviet/crop-mapping@sha256:…`.
3. GitHub → Packages → `crop-mapping` → Package settings → **Change visibility →
   Public** (contains no checkpoint/data/secret), so the VM pulls anonymously.
4. On the VM:

   ```bash
   cd /home/ubuntu/crop-mapping
   C="sudo docker compose -p crop-mapping-oracle --env-file .env.oracle -f compose.production.yaml -f compose.oracle.yaml"
   sudo docker pull ghcr.io/loanhviet/crop-mapping@sha256:<digest>
   sed -i 's#^CROP_IMAGE=.*#CROP_IMAGE=ghcr.io/loanhviet/crop-mapping@sha256:<digest>#' .env.oracle
   $C run --rm --no-deps crop-map python scripts/verify_assets.py --profile model
   $C up -d --no-build --wait --wait-timeout 180 crop-map
   curl -fsS http://127.0.0.1:18080/api/health
   ```

5. Test CD without auto-deploy: Run workflow with *deploy* ticked. Same digest is
   an idempotent verify; a new commit exercises the full swap.
6. Set `ORACLE_AUTO_DEPLOY=true`.

## Operating

- **Compose change in a commit:** deploy fails closed (`Remote Compose differs`)
  until you copy both Compose files from that commit to the VM. Intentional:
  infrastructure changes are applied by a human.
- **Manual rollback to an older version:** `git revert` the bad commit on `main`
  (goes through CI and CD like any change). Re-running an old run does **not**
  deploy it (freshness guard). Emergency on the VM: set `CROP_IMAGE` in
  `.env.oracle` to the previous digest from `.deployment/last-success.json` and
  run `$C up -d --no-build --wait crop-map`.
- **State on the VM:** `.deployment/last-success.json`, `.deployment/pending.json`
  (present only during or after a failed rollback), `.deployment/lock`.
- **Logs:** `$C logs --tail=100 crop-map`.
