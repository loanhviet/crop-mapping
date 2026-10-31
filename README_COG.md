# Prepared Sentinel-2 COG data

Prepare a single continuous region with `python prepare_cog.py --config preparation/cog_config.json`. Use the corresponding standalone notebook in `preparation/` if needed. The builder embeds `cog_data.py`; keep paths unchanged and regenerate notebooks only when preparation code changes.

See [asset contracts](docs/ASSETS.md) and [architecture](docs/ARCHITECTURE.md). Preparation reads public STAC/COG assets, applies scale/offset and quality rules, records provenance and publishes completed cubes atomically. Exact network availability and fresh full-dataset reproduction were not tested in this migration.

Interactive Analyze always runs TSViT. Do not use old saved-prediction/cache timing reports as measurements of current inference. `validate_cog.py` is a separate ground-truth overlap evaluation, not part of inference; it requires reference TARGET files and does not establish full-region accuracy.
