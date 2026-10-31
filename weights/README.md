# TSViT checkpoint

Tracked files are `config.yaml` and `LICENSE.txt`. `best.pth` is deliberately excluded. Obtain the exact checkpoint from an authorized source, keep it alongside the matching config, then run `python3 scripts/verify_assets.py`.

Expected identity is pinned in [model-manifest.json](../assets/model-manifest.json). Full instructions: [external assets](../docs/ASSETS.md). Do not substitute DINOv3 weights, retrain the model or change preprocessing to bypass a checkpoint mismatch.

Release builds include the verified binary via a separate minimal named context, never via Git or a blanket weights-directory COPY. Production uses packaged weights without a host mount; default development builds retain the original external weights contract. See [release build](../docs/CONTAINERS.md).
