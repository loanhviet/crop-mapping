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
### SSH access for this academic project

The verified Security Group currently permits only the laptop IP. A standard
GitHub-hosted runner has a different outbound IP, so the existing rule will block
it. For the initial manual CD runs, the simplest option is a temporary rule for
**only the current runner IPv4 /32**. This requires an owner action for each run;
it is not unattended network automation. Keep the laptop rule in place.

The workflow prints its IPv4 via `https://checkip.amazonaws.com` in the step log
and summary, then waits up to seven minutes for TCP SSH reachability. While that
step waits, use the AWS console: EC2 → instance → Security → attached Security
Group → Edit inbound rules → Add rule: SSH (or the configured TCP port), source
**Custom**, copy the exact runner IPv4 followed by `/32`, description identifying
this workflow run. Save. Do not select My IP (that is the laptop) or Anywhere.
After success, failure or cancellation, delete only this temporary runner rule
and retain the laptop rule. Removal is manual; do not leave stale entries behind.
If the wait expires, remove the rule and rerun with the new runner IP.

The workflow has no AWS credentials and makes no Security Group changes. TCP
reachability does not establish identity: SSH still requires the pinned host key
and dedicated private key. Port 8000 stays localhost. Do not allow 0.0.0.0/0 or
whole GitHub runner IP ranges. [GitHub documents the large changing runner IP
ranges](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#ip-addresses).
For repeated unattended deployments, use a static-egress runner or a separately
reviewed private access design later; neither is needed for this manual exercise.

On EC2, use `/home/ubuntu/crop-mapping` with:

- Existing Docker Engine/Compose v2 supporting `--wait` and multiple `--env-file`.
- Python 3, readable Compose file, writable `.env` and repository directory.
- `compose.production.yaml` byte-for-byte matching the reviewed workflow revision.
  The workflow checks its hash and refuses drift; reconcile a deliberate difference
  before deploying. It does not run git pull or replace server configuration.
- `.env` containing the actual current deployment settings. Set
  `CROP_DATA_DIR=/home/ubuntu/crop-map/data`, `CROP_BIND=127.0.0.1`,
  `CROP_PORT=8000`, and `CROP_RESULTS_VOLUME` to the **existing actual volume name**.
  Preserve CPU/thread/memory settings and pin the current CROP_IMAGE by digest.
  Confirm project `crop-mapping-production`, service `crop-map`, and its mount IDs.

Read-only preflight examples in your existing SSH session:

```bash
cd /home/ubuntu/crop-mapping
sudo -n docker compose version
sudo -n docker compose -p crop-mapping-production --env-file .env \
  -f compose.production.yaml ps
sudo -n docker inspect "$(sudo -n docker compose -p crop-mapping-production \
  --env-file .env -f compose.production.yaml ps -q crop-map)" \
  --format '{{json .Mounts}}'
curl --fail http://127.0.0.1:8000/api/health
```

Do not guess a new results-volume name. Script preflight compares resolved Compose
mounts to the running container, including the volume name and imagery path. It
refuses first-time bootstrap, missing imagery, unhealthy baseline, absent previous
registry digest, changed mounts or changed localhost binding. This protects the
existing project rather than creating a parallel deployment accidentally.

## Verified baseline supplied by the owner

The owner verified Ubuntu 24.04 AMD64, working `sudo -n docker`, and healthy
`crop-mapping-production-crop-map-1` under `/home/ubuntu/crop-mapping` using `.env`.
The baseline image is:

```text
loanhviet070105/crop-mapping@sha256:e4001dc8787c610981c08e1cd52bd14a9afd5e8606dc6aaacf9eaa56b6945d71
```

Imagery is `/home/ubuntu/crop-map/data`; the persistent results volume is
`crop-mapping-results`. API is `127.0.0.1:8000/api/health`, with checkpoint SHA256
`92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733`.
These are owner-provided observations, not a connection made during this change.
Do not create or migrate to `.env.production`. The helper reads/updates `.env`.
For a same-digest deployment it verifies identity and health and skips Compose up,
so the current container is not recreated. Other env settings and mount identities
remain intact; successful writes normalize only CROP_IMAGE to the pinned digest.

## First workflow test

After review/merge, select Actions → Deploy production digest → Run workflow →
**main**. Use the full `sha256:...` digest and full 40-character source revision
from a successful Phase 3 publishing run. Start with the currently running verified
digest for a low-impact idempotency check, then test a new verified release.
For the owner-verified baseline, image_digest is
`sha256:e4001dc8787c610981c08e1cd52bd14a9afd5e8606dc6aaacf9eaa56b6945d71`.
Obtain its full source revision from the successful publishing run or, in your
existing trusted EC2 SSH session, inspect the current container label:

```bash
sudo -n docker inspect crop-mapping-production-crop-map-1 \
  --format '{{index .Config.Labels "org.opencontainers.image.revision"}}'
```

The workflow verifies this source revision against its immutable published tag;
do not use the CD workflow's own commit as the image source unless it was built
and published. Watch the runner-IP step and add the temporary /32 rule as above.

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
CROP_IMAGE in `.env` and writes `.deployment/last-success.json`.

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
sudo -n docker compose -p crop-mapping-production --env-file .env \
  --env-file .deployment/recovery.env -f compose.production.yaml \
  up -d --no-build --pull never --wait --wait-timeout 180 crop-map
curl --fail http://127.0.0.1:8000/api/health
```

Verify the pending file's previous checkpoint and running image/mounts, then pin
CROP_IMAGE in `.env` to that restored digest. Remove recovery.env only
after verification. Do not remove lock/state during an active deployment. Host
lock plus Actions concurrency serialize updates. Signal handling attempts rollback
on interruption, but host power loss, SIGKILL or network loss can prevent completion;
pending.json supports manual recovery. There is no zero-downtime guarantee for this
single-container service, and no background auto-deployment trigger is enabled.
