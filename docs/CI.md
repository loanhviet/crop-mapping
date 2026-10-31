# GitHub Actions CI and AMD64 publishing

`ci.yml` runs on pushes and pull requests and is reusable by the publish workflow. On Ubuntu AMD64 it installs the hash-locked runtime wheels and pytest, runs the suite excluding `external_assets`, validates both Compose files, and checks the development Dockerfile. This gate does not have the checkpoint or satellite fixtures: it does not run the asset-dependent tests or real inference. See [TESTING.md](TESTING.md) for the full asset-provisioned suite.

`publish.yml` is manually dispatched and runs only for `main`. It calls the same CI workflow for that exact revision and proceeds only if it succeeds. It provisions and verifies the checkpoint, builds the release target for AMD64 and loads the image locally, checks its architecture and initializes the real model on CPU. The tested image is then pushed as `loanhviet070105/crop-mapping:sha-<full-commit>-amd64`; the digest returned by Docker Hub is written to the workflow summary. These checks do not exercise HTTP startup or real satellite inference; the latter requires trusted satellite fixtures and an additional gate before claiming an inference release has passed.

## Required owner setup

1. Choose a trusted private artifact store holding the exact checkpoint in `assets/model-manifest.json`. No source URL is assumed by the repository. Options include a private object store with a short-lived HTTPS signed URL, or another private artifact service. The current implementation accepts a direct HTTPS download URL in the repository Actions secret `CHECKPOINT_URL`; refresh short-lived URLs before the manual run. A service requiring custom authentication or OIDC needs a reviewed provisioning step before use. Do not expose URLs or checkpoints in public storage, logs, workflow artifacts, or Git.
2. Set Actions secrets `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`. The username must be `loanhviet070105`; use a scoped Docker Hub token. Never post credentials in issues or chat.
3. Configure Docker Hub to prevent overwriting commit tags where the account supports immutable-tag enforcement. The workflow also rejects an existing public tag, but that preflight check alone is not atomic and cannot guarantee registry immutability under concurrent external publishers. Restrict registry write access. Publishing requires permission to redistribute the model and application.
4. Merge the reviewed workflow to `main` using the normal PR process. Run **Publish AMD64 image** from `main` only after completing these prerequisites. This change does not itself push a commit or image.

The checkpoint URL is passed to curl through a temporary private config file and the download is removed after the context is prepared. `scripts/prepare_release_checkpoint.py` checks source size and SHA256, config hash, and the copied checkpoint before creating the minimal named build context; the release Dockerfile checks again. The runner and BuildKit cache contain the checkpoint during the job and must be trusted; do not export its layers to a public cache without redistribution approval.

A release failure blocks subsequent steps. A public tag lookup that fails for reasons other than HTTP 404 also fails closed. No mutable `latest` tag is created. If a previous run already published the commit tag, verify the existing registry digest and investigate rather than overwrite it. Deploy by the registry digest recorded in the workflow summary and independently verify the pull. This workflow does not deploy to a VPS or build ARM64.

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
