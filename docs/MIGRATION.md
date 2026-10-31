# Migration scope and preservation report

Date: 2026-10-31. Original: `/home/viet/projects/TLU/TSViT/crop-map`. New independent local Git repository: `/home/viet/projects/TLU/TSViT/crop-mapping`.

The destination did not exist and was created exclusively. The original project and separate research repository were not modified. No assets were linked back into the original, and no original virtual environment was copied. Validation reused the existing Python interpreter/dependencies read-only, with bytecode disabled and all test artifacts under the new checkout.

## Imported baseline

90 curated files, 2,593,551 bytes: all 17 root Python files, four original regression modules included; five root README files; Dockerfile/Compose/requirements/run script/templates; frontend/assets; model config/license; six preparation config/builder/notebook files; Postman source/collection/request/docs; editable diagram sources/config/metadata, renderer/packager and twelve SVGs.

Runtime modules stay at root. `scripts/benchmark_cog.py` is imported by an original regression; `precompute_regions.py` is also a regression dependency. `package_deploy.py` has a fixed allowlist requiring the retained root README names and preparation notebooks. `regions_config.json` reuses `preparation/cog_config.json`. The two standalone COG notebooks contain source/config matching the imported modules and have no execution outputs.

## Classification and exclusions

| Class | Decision |
| --- | --- |
| Runtime/API/inference/preprocessing/model | Imported unchanged |
| Frontend/Leaflet/fonts/icons/licenses | Imported unchanged |
| Geospatial/preparation/precompute/evaluation utilities | Retained at root for imports/CLI compatibility |
| Original automated tests | Retained unchanged; asset gates added separately |
| External CI fixtures | Not copied: checkpoint, patches 10000/10003 and metadata must be provisioned |
| Model YAML/license | Tracked; full config preserved including historical training metadata |
| Dockerfile/Compose | Imported unchanged |
| Data notebooks/config/builders | Retained at existing paths |
| Documentation | Curated sources; setup prose updated in cleanup branch |
| `data_collection/` | Excluded optional collection workstream; no runtime import dependency |
| `experiments/live_fetch/` | Excluded independent prototype, logs/results and research-specific fixtures |
| `preparation/dinov3/` | Excluded unrelated research/downloads/models/wheelhouse |
| `data/` arrays/catalog/metadata/targets/cubes | Excluded; replaced only by a tracked provisioning README |
| `weights/best.pth` | Excluded; pinned hash/size manifest provided |
| `data/results`, predictions, caches, benchmarks | Excluded generated state |
| `web/benchmarks/` | Excluded generated previews/reports; already omitted from original Docker context |
| `deployment/bundles/`, `deployment/qa/` | Excluded archives, screenshots, results and local execution evidence |
| Old deployment validation reports | Left in original; not presented as current test results |
| Diagram PDF/DOCX/PNG/ZIP/generated HTML | Left in original; retain sources/SVGs only |
| Original audit Markdown | Reviewed in original, not copied as an up-to-date validation report |
| `.venv`, bytecode, pytest caches | Excluded machine state |
| `.env` and private configuration | Not copied or staged |

## Intentional changes after baseline

- Expanded ignore rules and documented safe environment configuration.
- Added a model identity manifest and a read-only asset verifier (no download/inference).
- Added explicit pytest external-asset/inference markers and strict `--require-assets` collection failure.
- Added six integrity regressions covering substituted models, changed config/fixtures and catalog containment.
- Preserved vendor line endings with attributes; imported third-party CSS has CRLF and was not reformatted.
- Added Docker context exclusions for nested private files in the allowed web tree. The original application COPY list remains unchanged.
- Replaced stale setup claims with English documentation; documented current constraints and future Oracle ARM64 branches.
- Extended only the packaging documentation allowlist so bundles include newly referenced setup material. Original model/data payload rules remain unchanged.

No runtime, model, preprocessing, original test assertion, UI, dependency pin or application endpoint change was made. No module relocation, Python packaging framework, model training, inference, GitHub workflow, remote, PR, merge, image build, deployment or cloud access was performed.

## Preservation evidence and limits

Before copying, metadata for 24,014 original entries was recorded (path, mode, size, mtime and symlink target). Hashes of all 90 imported files were recorded and compared against originals. Final validation repeats these checks and compares every unchanged imported runtime/frontend/config/preparation/test file to the new checkout.

The snapshot metadata and test/JUnit logs are local ignored evidence in `.validation/`. Large original datasets were not rehashed in full; unchanged metadata and the fact that no migration writes targeted the original are the preservation evidence for excluded binary data. Results are in [validation report](VALIDATION.md).

## Publishing blockers

No remote was configured. The owner still needs to choose a project-wide license and confirm rights for application/UI/data distribution; existing third-party notices remain. No verified direct checkpoint download URL or hosted data store was established. Full inference regression, actual Docker build/container smoke, clean-install reproducibility and native ARM64 compatibility remain unverified.
