"""Explicit external-asset gates; existing regression assertions remain unchanged."""
from pathlib import Path
import os

import pytest

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("CROP_DATA_DIR", ROOT / "data"))
WEIGHTS = Path(os.getenv("CROP_WEIGHTS_DIR", ROOT / "weights"))
PASTIS = (DATA / "catalog.json", DATA / "S2_10000.npy", DATA / "S2_10003.npy")
MODEL = (WEIGHTS / "best.pth", WEIGHTS / "config.yaml")
REQUIREMENTS = {
    "test_metadata_preserves_native_grid": PASTIS,
    "test_preprocessing_dates_padding_and_validation": PASTIS,
    "test_selection_outside_coverage_rejected": PASTIS,
    "test_exports_keep_background_and_mask_consistent": PASTIS,
    "test_real_checkpoint_api_download_and_pixel": PASTIS + MODEL,
    "test_live_api_requires_key_without_creating_a_job": MODEL,
    "test_live_acquisition_to_real_model_and_exports": MODEL,
    "test_local_catalog_plan_preview_and_real_prediction": PASTIS + MODEL,
    "test_prepare_other_tile_polygon_and_doy_order": (DATA / "metadata.geojson",),
    "test_prepared_api_limits_mask_cache_and_restart": MODEL,
    "test_precompute_real_model_and_cross_block_exports": MODEL,
}
INFERENCE = {
    "test_real_checkpoint_api_download_and_pixel",
    "test_live_acquisition_to_real_model_and_exports",
    "test_local_catalog_plan_preview_and_real_prediction",
    "test_prepared_api_limits_mask_cache_and_restart",
    "test_precompute_real_model_and_cross_block_exports",
}


def pytest_addoption(parser):
    parser.addoption("--require-assets", action="store_true", help="Fail collection if selected asset-dependent tests lack assets.")


def pytest_collection_modifyitems(config, items):
    unavailable = []
    for item in items:
        required = REQUIREMENTS.get(item.originalname, ())
        if required:
            item.add_marker(pytest.mark.external_assets)
        if item.originalname in INFERENCE:
            item.add_marker(pytest.mark.inference)
        missing = [p for p in required if not p.is_file()]
        if missing:
            reason = "External assets not provisioned; see docs/ASSETS.md: " + ", ".join(p.name for p in missing)
            if config.getoption("--require-assets"):
                unavailable.append(item.nodeid + ": " + reason)
            else:
                item.add_marker(pytest.mark.skip(reason=reason))
    if unavailable:
        raise pytest.UsageError("Required assets missing for selected tests:\n" + "\n".join(unavailable))
