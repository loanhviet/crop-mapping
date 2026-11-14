#!/usr/bin/env bash
# LOCAL ONLY: ten sequential bounded scripts; no production requests.
set -u
cd "$(dirname "$0")/.."
AT_PYTHON="${AT_PYTHON:-/home/viet/projects/TLU/TSViT/crop-mapping/.venv/bin/python}"
failed=0
for module in at01_malformed_input at02_oversized_payload at03_api_flooding at04_adversarial_noise at05_temporal_manipulation at06_ood_input at07_malformed_geojson at08_parameter_tampering at09_resource_exhaustion at10_invalid_numerics; do
    "$AT_PYTHON" -m "scripts.$module" || failed=1
done
exit "$failed"
