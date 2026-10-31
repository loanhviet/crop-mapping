# Continuous multi-block regions

`python prepare_regions.py --config preparation/regions_config.json` prepares nine aligned 768×768 blocks and publishes a virtual 2304×2304 region. The configuration reuses `preparation/cog_config.json`; keep that relative path intact.

Each block retains its acquisition calendar. Runtime maps 24×24 windows to a block rather than storing a second full image mosaic. Raw arrays occupy approximately 8.28 GB before caches. See [external assets](docs/ASSETS.md).

Whole region selects the footprint; Analyze still performs sequential real inference. There is no active prepared-window limit in the imported API. The legacy precompute tool remains for reproducibility/tests; the interactive API does not serve its saved classifications. Prediction-only bundles are rejected at startup.
