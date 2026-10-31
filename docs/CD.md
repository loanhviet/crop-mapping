# Manual production CD to EC2

`deploy.yml` deploys a verified public Docker Hub AMD64 digest to the existing
EC2 Compose project. It is manually triggered from `main` and uses the existing
GitHub `production` environment. No SSH/deployment was executed while implementing
this workflow. Local tests use simulated Docker/SSH-independent transactions.

## One-time setup by the owner

In GitHub Settings → Environments → production, restrict deployment branches to
**main**; review any environment approval rules. The workflow also checks the Git
ref. Give this environment the following secrets (not repository variables):

| Secret | Meaning |
| --- | --- |
| `EC2_HOST` | Reachable EC2 public DNS name or IPv4 address |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_PRIVATE_KEY` | Dedicated deployment SSH private key, including its multiline header/footer |
| `EC2_KNOWN_HOSTS` | Verified OpenSSH known_hosts entry for this server/port |

Optional environment variable: `EC2_SSH_PORT` (default `22`). Verify the SSH host
key fingerprint through your existing trusted SSH session or AWS console before
saving known_hosts. Do not trust a key solely because ssh-keyscan returned it.
For a non-default port use `[host]:port` known_hosts syntax. Password-protected
interactive keys are not supported by this noninteractive workflow.

Install the public key in ubuntu's authorized_keys yourself. A dedicated key can
use `restrict` to disable forwarding and PTY while retaining command/SFTP access.
The account must have noninteractive `sudo -n docker ...` permission. Docker sudo
access is effectively root access: protect the production environment/key and
review workflow changes. No sudo password is requested or stored by this workflow.
SSH must be reachable from the GitHub-hosted runner; if current Security Group
rules only admit your own IP, decide an approved connectivity policy before
running. This change does not alter Security Groups. Port 8000 remains localhost.

On EC2, use `/home/ubuntu/crop-mapping` with:

- Existing Docker Engine/Compose v2 supporting `--wait` and multiple `--env-file`.
- Python 3, readable Compose file, writable `.env.production` and repository directory.
- `compose.production.yaml` byte-for-byte matching the reviewed workflow revision.
  The workflow checks its hash and refuses drift; reconcile a deliberate difference
  before deploying. It does not run git pull or replace server configuration.
- `.env.production` containing the actual current deployment settings. Set
  `CROP_DATA_DIR=/home/ubuntu/crop-map/data`, `CROP_BIND=127.0.0.1`,
  `CROP_PORT=8000`, and `CROP_RESULTS_VOLUME` to the **existing actual volume name**.
  Preserve CPU/thread/memory settings and pin the current CROP_IMAGE by digest.
  Confirm project `crop-mapping-production`, service `crop-map`, and its mount IDs.

Read-only preflight examples in your existing SSH session:

```bash
cd /home/ubuntu/crop-mapping
sudo -n docker compose version
sudo -n docker compose -p crop-mapping-production --env-file .env.production \
  -f compose.production.yaml ps
sudo -n docker inspect "$(sudo -n docker compose -p crop-mapping-production \
  --env-file .env.production -f compose.production.yaml ps -q crop-map)" \
  --format '{{json .Mounts}}'
curl --fail http://127.0.0.1:8000/api/health
```

Do not guess a new results-volume name. Script preflight compares resolved Compose
mounts to the running container, including the volume name and imagery path. It
refuses first-time bootstrap, missing imagery, unhealthy baseline, absent previous
registry digest, changed mounts or changed localhost binding. This protects the
existing project rather than creating a parallel deployment accidentally.

## First workflow test

After review/merge, select Actions → Deploy production digest → Run workflow →
**main**. Use the full `sha256:...` digest and full 40-character source revision
from a successful Phase 3 publishing run. Start with the currently running verified
digest for a low-impact idempotency check, then test a new verified release.

The workflow verifies that the source commit is an ancestor of checked-out main and
that its public `sha-<full-commit>-amd64` tag resolves to the exact supplied digest.
The digest must come from the successful publishing run; tag association is not a
cryptographic CI attestation. SSH uses a pinned known_hosts file, strict checking,
a noninteractive key, and no agent forwarding. Only the reviewed deployment helper
is copied into a private temporary directory; model/data/credentials are not copied.

The helper takes a nonblocking host lock, validates current service/volume/bind
identities, and saves the old image digest/checkpoint. It pulls the new digest
before changing containers and confirms linux/amd64 plus the image's source label.
It updates only `crop-map` using Compose `up --no-build --pull never --wait` with a
180-second health timeout. It then checks the running image ID, unchanged mounts,
healthy state, and localhost `/api/health` for `status=ok`, `model=TSViT`, `device=cpu`
and the SHA256 in the checked-out model manifest. Success atomically updates only
CROP_IMAGE in `.env.production` and writes `.deployment/last-success.json`.

Evidence: keep the successful workflow summary (digest/checkpoint), service `ps`,
health JSON, and existing SSH-tunnel API confirmation. This is a health/model
identity deployment gate, not a new real-satellite inference or accuracy test.

## Rollback and recovery

If update/verification fails after switching, the helper runs the same Compose
update with the previous **cached digest**, waits for health and verifies the old
checkpoint/mounts. It restores the original env file and leaves the job failed even
when rollback succeeds. It never runs down, removes volumes, prunes images, rebuilds
images or modifies imagery. Old/new containers use the same writable results
volume; rollback does not undo application writes. Back up important results using
your established procedure and review format compatibility before future changes.

A pull or preflight failure leaves the running deployment alone. If automatic
rollback fails, inspect `.deployment/pending.json` for the exact previous digest
and checkpoint, plus `docker compose logs`. For an interrupted/failed transaction,
use a temporary image override, retaining the original project/env/volume:

```bash
cd /home/ubuntu/crop-mapping
# Read previous from pending.json; do not guess or substitute a mutable tag.
python3 -c 'import json; print("CROP_IMAGE=" + json.load(open(".deployment/pending.json"))["previous"])' \
  > .deployment/recovery.env
sudo -n docker compose -p crop-mapping-production --env-file .env.production \
  --env-file .deployment/recovery.env -f compose.production.yaml \
  up -d --no-build --pull never --wait --wait-timeout 180 crop-map
curl --fail http://127.0.0.1:8000/api/health
```

Verify the pending file's previous checkpoint and running image/mounts, then pin
CROP_IMAGE in `.env.production` to that restored digest. Remove recovery.env only
after verification. Do not remove lock/state during an active deployment. Host
lock plus Actions concurrency serialize updates. Signal handling attempts rollback
on interruption, but host power loss, SIGKILL or network loss can prevent completion;
pending.json supports manual recovery. There is no zero-downtime guarantee for this
single-container service, and no background auto-deployment trigger is enabled.
