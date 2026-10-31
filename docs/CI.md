# GitHub Actions CI and AMD64 publishing

`ci.yml` runs on pushes and pull requests and is reusable by the publish workflow. On Ubuntu AMD64 it installs the hash-locked runtime wheels and pytest, runs the suite excluding `external_assets`, validates both Compose files, and checks the development Dockerfile. This gate does not have the checkpoint or satellite fixtures: it does not run the asset-dependent tests or real inference. See [TESTING.md](TESTING.md) for the full asset-provisioned suite.

`publish.yml` is manually dispatched and runs only for `main`. It calls the same CI workflow for that exact revision and proceeds only if it succeeds. It provisions and verifies the checkpoint, builds the release target for AMD64 and loads the image locally, checks its architecture and initializes the real model on CPU. The tested image is then pushed as `loanhviet070105/crop-mapping:sha-<full-commit>-amd64`; the digest returned by Docker Hub is written to the workflow summary. These checks do not exercise HTTP startup or real satellite inference; the latter requires trusted satellite fixtures and an additional gate before claiming an inference release has passed.

## Required owner setup

1. Create a **private** GitHub repository for model artifacts (for example `loanhviet/crop-mapping-models`; this name is a suggestion, not a provisioned repository). Initialize its default branch. Create a release, for example `tsvit-v1`, and **manually attach** the trusted `best.pth` as a Release asset. Do not add the binary to that repository's Git history. Verify its local SHA256 against `assets/model-manifest.json` before uploading. This task uploads nothing.
2. Obtain its numeric asset ID from the authenticated owner's terminal:

   ```bash
   gh api repos/OWNER/PRIVATE_REPOSITORY/releases/tags/tsvit-v1 \
     --jq '.assets[] | select(.name == "best.pth") | .id'
   ```

   Replace OWNER/PRIVATE_REPOSITORY with the actual private artifact repository. The token used for this read must have access to it.
3. Create a fine-grained personal access token: select only that private repository and grant **Contents: read**. In `loanhviet/crop-mapping` → Settings → Secrets and variables → Actions, configure:

   | Kind | Name | Value |
   | --- | --- | --- |
   | Variable | `CHECKPOINT_REPOSITORY` | Actual `owner/private-repository` |
   | Variable | `CHECKPOINT_ASSET_ID` | Numeric asset ID from step 2 |
   | Secret | `CHECKPOINT_READ_TOKEN` | Fine-grained read-only artifact token |
   | Secret | `DOCKERHUB_USERNAME` | `loanhviet070105` (existing) |
   | Secret | `DOCKERHUB_TOKEN` | Scoped Docker Hub write token (existing) |

   `CHECKPOINT_URL` is no longer used. A runner obtains a fresh download redirect via the GitHub API each run, so signed URLs need no manual renewal. Tokens can expire or be revoked: set a suitable lifetime under your policy and rotate the secret before expiry. The public repository's default `GITHUB_TOKEN` cannot read an unrelated private repository. Do not put credentials in variables or chat. A GitHub App installation token is a later option if PAT rotation becomes burdensome; it is not required here.
4. Docker Hub → `loanhviet070105/crop-mapping` → Settings → General → Tag mutability settings: choose **Specific tags are immutable**, regex `^sha-[0-9a-f]{40}-amd64$`, then Save (or choose all tags immutable if appropriate). This registry policy is required to prevent overwrite races with other publishers. Verify the policy before the first run; the workflow cannot establish that policy from the public tag lookup. The workflow also checks tag absence before building and immediately before push; non-404 lookup errors fail closed. Keep registry write access restricted.
5. Review and merge this follow-up via a PR, then Actions → **Publish AMD64 image** → Run workflow → select **main**. It waits for CI, downloads/verifies the pinned asset, builds and tests the AMD64 release, and pushes only a new commit tag. Inspect the workflow summary for the tag and digest. If the tag already exists, verify that release rather than rerun an overwrite. No `latest` tag is written.

The downloader uses the documented [GitHub release asset API](https://docs.github.com/en/rest/releases/assets#get-a-release-asset), authenticated with Contents: read, requesting binary content. Repository/asset identifiers are validated before forming a fixed `api.github.com` URL. Credentials are in a mode-restricted temporary curl config; download is HTTPS-only, bounded to 7 MB and 180 seconds, and curl does not forward Authorization across redirect hosts. The download/config are removed after provisioning. The prepared context and Docker layers still contain the model on the ephemeral runner; do not export them as public caches or workflow artifacts.

`scripts/prepare_release_checkpoint.py` checks byte count, SHA256, config hash and copied bytes before the existing named-context release build. The Dockerfile verifies again. No host weights mount is needed. Missing/unauthorized assets, wrong hashes, CI/build/model checks, or registry errors stop publication. After pushing, the workflow independently inspects the remote manifest and compares its digest to Docker's push result, then writes the exact `image@sha256:...` identity into the step summary. If that verification fails after a successful push, the release may already exist: investigate it without overwriting.

Public release rights must cover the checkpoint and application. HTTP startup and real satellite inference still require external imagery and are not claimed by the model-initialization gate. Deploy by digest after independently checking the release. This phase does not deploy infrastructure.

## Local verification of this follow-up

PR #3 was confirmed merged at `c214999cc4ae34d06c49a9209f4937d85193e555`. Local regression, workflow lint/shell syntax, Compose, and Dockerfile checks are recorded in the task report. No new image was built or published. The existing public Phase 2 tag `sha-8a90dfd9b4b6-amd64` was inspected read-only and reported registry digest `sha256:5042c7f742c240531711ef9b86cf59373295ed67e1131b43b33c9a71fcca1372`. This is not evidence of a successful run of the new publishing workflow. Private artifact download and the first Actions publication remain unverified until owner setup and execution.

## Compose JSON compatibility

The production mount test checks `read_only: true` in Compose's resolved config
and requires explicit `bind.create_host_path: false` in the source YAML.
Compose v2.39.4 omits this false boolean from `config --format json` (`bind: {}`),
whereas v5.5.1 retains it. The compose-go field uses JSON `omitempty` in v2;
missing serialized fields must not be treated as proof of the source setting.
The original PR #3 KeyError was reproduced with v2.39.4; the exact runner Compose
version has not been verified.

Local daemon probes with both versions verified that an absent bind source fails
with `bind source path does not exist` and remains absent when the option is false.
A true-option control created the source directory. The probes used temporary
paths and an existing local image, cleaned up their own containers, and did not
build images or touch satellite data. Production Compose remains unchanged.
