#!/usr/bin/env bash
# Re-run the whole suite. Order matters: TC04 inspects TC03 artifacts.
#   PROD=0 scripts/run_all.sh   -> skip TC01–TC04 and the UI run (the only scripts that contact production)
# Production scripts send ~110 sequential requests in total (incl. 1 small analysis + 1 UI analysis).
set -u
cd "$(dirname "$0")/.."
PY="${AT_PYTHON:-/home/viet/projects/TLU/TSViT/crop-mapping/.venv/bin/python}"
mkdir -p evidence/_console
run() { echo "=== $1"; "$PY" -m "scripts.$1" "${@:2}" 2>&1 | tee "evidence/_console/$1.log"; }

if [ "${PROD:-1}" = "1" ]; then
  run tc01_health_availability
  run tc02_input_validation
  run tc03_e2e_workflow
  run tc04_output_integrity
  run tc03_frontend_ui https://crop.loanhviet.dev production
fi
for t in tc05_prediction_quality tc06_noise_robustness tc07_temporal_consistency tc08_ood_behavior \
         tc09_external_service_failure tc10_inference_failure; do run "$t"; done
AT_PYTHON="$PY" bash scripts/run_at_all.sh 2>&1 | tee evidence/_console/run_at_all.log
"$PY" -m scripts.collect_summary && "$PY" -m scripts.make_test_plan && "$PY" -m scripts.build_report && "$PY" -m scripts.log_excerpt && "$PY" -m scripts.build_final_report
