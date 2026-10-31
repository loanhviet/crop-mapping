# Actual migration validation

Date: 2026-10-31. All checks ran with the new checkout as working directory. No model inference, training, image build, container start, registry publishing or cloud access was performed.

| Check | Actual result |
| --- | --- |
| Imported Python syntax | Passed before baseline commit |
| Original lightweight regressions, before cleanup | 13 passed, 0 skipped, 0 failed (1.733 s) |
| Candidate default suite | 19 passed, 11 skipped, 0 failed (1.12 s) |
| External fixture/model tests | 11 explicitly skipped because assets were intentionally absent |
| Strict asset gate | Expected collection failure, exit 4, when assets absent |
| Checkpoint verifier without checkpoint | Expected diagnostic failure, exit 1 |
| Application/tool module resolution | 13 imports resolved inside the new checkout |
| Compose configuration | `docker compose config --quiet` passed |
| Docker build/run/context transfer | Not performed; Dockerfile/COPY/ignore rules inspected statically |
| Real model/API/browser smoke | Not performed; requires provisioned assets and explicit execution |
| Full source/data hashing | Imported files hashed; excluded large datasets metadata checked only |
| Oracle ARM64 | Not verified |

The candidate adds six asset-integrity tests; the original four regression modules and assertions are byte-identical. The 11 skipped regressions are not counted as passed inference tests. One Starlette/httpx TestClient deprecation warning was observed and was not suppressed or treated as a runtime failure.

The existing Python 3.13 virtual-environment interpreter/dependencies were reused read-only, without installing packages or copying that environment. `PYTHONDONTWRITEBYTECODE=1` prevented dependency bytecode writes. JUnit, temporary arrays and process logs were confined to ignored `.validation/` under the new repository.

Additional static validation checks all curated Python syntax, JSON and notebook code cells, local Markdown links, declared Docker COPY sources, packaging allowlist sources (with the intentionally absent checkpoint separated), unchanged source hashes and Git exclusions. The final local summary is `.validation/static-results.json`; original preservation is checked again before completing migration.

Before GitHub publication: provision assets using [ASSETS.md](ASSETS.md), run `python scripts/verify_assets.py --profile ci`, then `python -m pytest --require-assets`. Actual container smoke belongs to the next authorized container phase. A passing health endpoint alone does not prove inference or scientific quality.
