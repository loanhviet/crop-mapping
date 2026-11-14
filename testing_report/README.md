# testing_report — Bộ kiểm thử AI cho Satellite Crop Mapping

## Cấu trúc
- 01_SYSTEM_AUDIT.md        : audit hệ thống (kiến trúc, API, validation, giới hạn)
- 02_TEST_PLAN.md           : kế hoạch 20 test case + kết quả
- scripts/                  : tc01..tc10, at01..at10, run_all.sh, collect_summary.py, build_report.py
- evidence/<ID>/            : result.json, execution.log, request/response hoặc input/output, ảnh
- evidence/_baseline/       : log bộ pytest có sẵn của dự án (53 passed)
- summary.json              : tổng hợp PASS/FAIL/BLOCKED (sinh tự động)
- Satellite_Crop_Mapping_AI_Testing_Report.pdf

## Chạy lại
  export PY=/duong/dan/.venv/bin/python        # venv của dự án (PyTorch CPU)
  export CROP_ASSETS_ROOT=/thu/muc/co/weights_va_data   # mặc định: checkout chính
  uv pip install --python $PY --target testing_report/.pydeps matplotlib
  uv pip install --python $PY --target testing_report/.pydeps-pw playwright
  bash testing_report/scripts/run_all.sh            # toàn bộ (có ~110 request production)
  PROD=0 bash testing_report/scripts/run_all.sh     # chỉ local, không gọi production
  cd testing_report && $PY -m scripts.tc05_prediction_quality   # chạy một test
  cd testing_report && $PY -m scripts.collect_summary && $PY -m scripts.build_report
  cd testing_report && $PY -m scripts.log_excerpt && $PY -m scripts.build_final_report   # báo cáo thực hành (bản Final)

## Quy tắc an toàn đã áp dụng
- Production: chỉ GET, POST /api/imagery-plan (không tạo job), 1 job API 5,76 ha,
  1 job qua UI; tuần tự, timeout 60 s, giãn cách 0,3 s, tối đa 80 request/script.
- Tấn công, tải, cạn kiệt tài nguyên, mock: chỉ local, có giới hạn số request/thời gian.
- Kết quả job local ghi vào testing_report/.runtime/ (không đụng data/ của dự án).
