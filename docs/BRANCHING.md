# Branching and release plan

Use Conventional Commits for coherent, actual changes. Imported baseline lives on `main`; cleanup is developed on `refactor/project-structure`. This migration does not merge, push, create a remote or open a PR. Baseline verification is limited to static checks and lightweight tests, not complete inference/container validation.

Review the cleanup diff, provision assets and run full regression before merging by PR. Keep individual commits through a merge commit when useful. Future branches start from the latest accepted `main`.

| Future branch (not created) | Scope |
| --- | --- |
| `feat/container-registry` | Native ARM64 dependency/build/inference verification, image tags/digests, Docker Hub and image-based Compose |
| `ci/automated-testing` | Asset fixtures, pytest, container smoke, image build/publish |
| `cd/cloud-deployment` | Oracle Cloud ARM64, production Compose, deployment/health/rollback |
| `docs/deployment-guide` | Verified end-to-end setup, screenshots, recovery and troubleshooting |

Target: GitHub → GitHub Actions → Docker Hub → Oracle Cloud ARM64 → Compose → app. None of these external integrations was implemented by this migration.

Recommended release identity: git commit, image digest, model/config hashes, dataset version and Compose configuration hash. Build once, test that artifact, then deploy it. Do not rebuild source on the VPS. Keep deployment serialized and rollback to a compatible image/model/dataset set. Never expose deployment credentials to untrusted PR events.

ARM64 acceptance must check Python 3.13 wheels (especially the CPU torch pin), clean dependency installation, native build, real inference and geospatial exports. Source portability alone is insufficient evidence. Do not change the model to work around packaging issues.

## Current phase

Phase 1 was merged via PR #1. Phase 2 uses `feat/container-registry` from synchronized `main` (`2f1bbc3`); this phase does not push/merge or create Actions workflows. Scope was narrowed to a reliable CPU AMD64 image; ARM64 and multi-platform work are deferred. Registry publication still requires explicit approval. See [container workflow](CONTAINERS.md).
