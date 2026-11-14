# 02 — Test Plan: 20 test case

Thiết kế (mục tiêu, input, expected, steps) được viết trước khi chạy; cột kết quả được điền tự động từ `evidence/<ID>/result.json`.

| ID | Tên | Loại | Môi trường | Trạng thái |
|---|---|---|---|---|
| TC01 | API Health & Availability | Automation | Local + Production | **PASS** |
| TC02 | API Input Validation | Automation | Local + Production | **PASS** |
| TC03 | End-to-End Inference Workflow | Automation | Local + Production | **PASS** |
| TC04 | Output Format & Data Integrity | Automation | Local + Production (artifacts TC03) | **PASS** |
| TC05 | Model Prediction Quality | AI Test | Local | **PASS** |
| TC06 | Model Robustness to Noise | AI Test | Local | **PASS** |
| TC07 | Temporal Data Consistency | AI Test | Local | **PASS** |
| TC08 | Out-of-Distribution Behavior | AI Test | Local | **FAIL** |
| TC09 | External Service Failure | Mock Test | Local (mock) | **PASS** |
| TC10 | Model Inference Failure | Mock Test | Local (mock) | **PASS** |
| AT01 | Tấn công đầu vào sai cấu trúc | Security attack (tầng API) | Local | **FAIL** |
| AT02 | Tấn công payload quá lớn | Security attack (tầng API / tài nguyên) | Local | **FAIL** |
| AT03 | Dồn yêu cầu API có giới hạn | Security / availability (flooding có giới hạn) | Local | **PASS** |
| AT04 | Nhiễu đối kháng FGSM và PGD | Adversarial attack (white-box, cấp mô hình) | Local | **FAIL** |
| AT05 | Thao túng chuỗi thời gian và ngày quan sát | Adversarial / robustness (thao túng chuỗi thời gian) | Local | **FAIL** |
| AT06 | Đầu vào ngoài phân bố | Robustness (dữ liệu tổng hợp ngoài phân phối) | Local | **FAIL** |
| AT07 | Tấn công GeoJSON không hợp lệ | Security attack (tầng API) | Local | **FAIL** |
| AT08 | Can thiệp tham số và định danh tài nguyên | Security attack (phân quyền / tham số) | Local | **FAIL** |
| AT09 | Tiêu thụ tài nguyên vùng Normandy có giới hạn | Security / availability (resource exhaustion có giới hạn) | Local | **PASS** |
| AT10 | Giá trị số và kích thước tensor không hợp lệ | Security / robustness (giá trị số không hợp lệ) | Local | **FAIL** |

## TC01 — API Health & Availability

1. **ID:** TC01
2. **Tên:** API Health & Availability
3. **Loại:** Automation
4. **Mục tiêu:** Xác nhận dịch vụ đang hoạt động và sẵn sàng phục vụ: các endpoint public (/api/health, /api/catalog, giao diện web, OpenAPI, Swagger UI) trả HTTP 200; health báo đúng mô hình TSViT và đúng checkpoint (SHA-256 khớp manifest của repository); catalog đủ 19 lớp. Đây là phép kiểm tra "smoke test" đầu tiên trước mọi kiểm thử khác.
5. **Thành phần:** FastAPI: health(), catalog(), StaticFiles (web/), OpenAPI/Swagger; Engine.sha256; Caddy reverse proxy (production).
6. **Môi trường:** Local + Production
7. **Điều kiện tiên quyết:** Local: checkpoint weights/best.pth + dữ liệu đã chuẩn bị (data/), Python 3.13 venv của dự án.; Production: truy cập Internet tới https://crop.loanhviet.dev; không cần xác thực.
8. **Input:** 15 GET mỗi môi trường: 3 lượt × 5 endpoint {/api/health, /api/catalog, /, /openapi.json, /docs}; giãn cách 0,3 s ở production.
9. **Expected:** Mọi endpoint public trả 200; health báo ok/TSViT với checkpoint đúng manifest; catalog đủ 19 lớp; median /api/health < 3 s; Local và Production cùng checkpoint.
10. **Steps:** (1) Khởi tạo ứng dụng local bằng FastAPI TestClient (chạy lifespan thật: nạp checkpoint, kiểm tra SHA-256). (2) Gửi lần lượt 15 GET tới local, ghi status, thời gian phản hồi, nội dung. (3) Lặp lại 15 GET tuần tự tới production qua HTTPS (timeout 60 s). (4) So sánh checkpoint_sha256 giữa hai môi trường và với assets/model-manifest.json. (5) Chụp màn hình trang chủ và Swagger UI production bằng Chrome headless. (6) Đánh giá theo tiêu chí đặt trước (tất cả 200, median /api/health < 3 s). — lệnh: `cd testing_report && $PY -m scripts.tc01_health_availability`
11. **Actual:** Local median health=4.7 ms; Production median health=105.9 ms, max=5536.1 ms; số request production=15.
12. **Status:** PASS (11/11 assertion)
13. **Evidence:** `testing_report/evidence/TC01/`
14. **Nhận xét:** Request đầu tiên của client Python tới production mất khoảng 5,5 s, các request sau chỉ khoảng 105 ms. Phép đo bổ sung bằng curl (evidence/TC01/curl_timing_breakdown.txt) cho thấy toàn bộ request đầu chỉ mất 0,80 s (IPv4: 0,29 s). Vì vậy độ trễ này nằm ở phía client (thiết lập kết nối/phân giải địa chỉ của httpx trên máy kiểm thử), không phải do máy chủ. Production trả header "server: uvicorn" và "via: 1.1 Caddy"; trong lần HEAD duy nhất không thấy các header bảo mật như HSTS hay X-Content-Type-Options (chỉ là quan sát, không tính vào kết quả).

## TC02 — API Input Validation

1. **ID:** TC02
2. **Tên:** API Input Validation
3. **Loại:** Automation
4. **Mục tiêu:** Kiểm tra lớp kiểm tra dữ liệu đầu vào của API: yêu cầu hợp lệ được chấp nhận, mọi yêu cầu sai (thiếu trường, sai kiểu hình học, ring không khép kín, tọa độ ngoài WGS84, mùa không có dữ liệu, vùng ngoài khu vực có ảnh, patch không tồn tại, sai kiểu) bị từ chối bằng 422 với thông báo rõ ràng; đồng thời xác nhận Local và Production hành xử giống nhau.
5. **Thành phần:** AnalysisRequest + validate_polygon (Pydantic), PreparedProvider.resolve, selection_mask, endpoint POST /api/imagery-plan.
6. **Môi trường:** Local + Production
7. **Điều kiện tiên quyết:** Như TC01. Dùng /api/imagery-plan vì endpoint này dùng cùng model AnalysisRequest với /api/analyses nhưng KHÔNG tạo job, nên an toàn khi chạy trên production.
8. **Input:** 10 payload (1 hợp lệ + 9 không hợp lệ), xem bảng kiểm tra bên dưới và evidence/TC02/request.json. Polygon hợp lệ là ô 24×24 pixel (240 m × 240 m) ở góc trên-trái patch PASTIS 10003.
9. **Expected:** Input hợp lệ → 200 kèm kế hoạch phân tích; mọi input sai → 422 với thông báo rõ ràng, không có 500/stack trace; hành vi Local và Production giống nhau.
10. **Steps:** (1) Sinh polygon hợp lệ từ metadata patch 10003 (origin UTM → WGS84). (2) Gửi 10 POST /api/imagery-plan tới local, ghi mã trạng thái và thông báo lỗi. (3) Gửi đúng 10 payload đó, tuần tự, tới production. (4) So sánh mã trạng thái và thông báo giữa hai môi trường; kiểm tra không có HTTP 500 hay stack trace. — lệnh: `cd testing_report && $PY -m scripts.tc02_input_validation`
11. **Actual:** 20/20 lượt đúng mã kỳ vọng; Local/Production nhất quán: True.
12. **Status:** PASS (21/21 assertion)
13. **Evidence:** `testing_report/evidence/TC02/`
14. **Nhận xét:** Tất cả trường hợp sai đều nhận 422 kèm thông báo dễ hiểu cho người dùng, và local/production trả kết quả giống hệt nhau. Các payload tấn công nặng hơn (NaN, JSON lồng sâu, polygon tự cắt) chỉ được thử ở local, xem AT01, AT02 và AT07.

## TC03 — End-to-End Inference Workflow

1. **ID:** TC03
2. **Tên:** End-to-End Inference Workflow
3. **Loại:** Automation
4. **Mục tiêu:** Kiểm thử luồng nghiệp vụ hoàn chỉnh như người dùng thật: lập kế hoạch → gửi phân tích (202) → theo dõi trạng thái → nhận kết quả → tải GeoTIFF/CSV/GeoJSON/PNG/ZIP; đồng thời kiểm thử tích hợp frontend–backend bằng trình duyệt thật (Playwright điều khiển Chrome) trên cả local và production, rồi so sánh kết quả hai môi trường.
5. **Thành phần:** Toàn hệ thống: Leaflet UI (web/app.js) → FastAPI → hàng đợi 1 worker → TSViT → export_result → endpoint tải về.
6. **Môi trường:** Local + Production
7. **Điều kiện tiên quyết:** Như TC01. Production: chỉ 1 phân tích qua API (5,76 ha) và 1 phân tích qua giao diện (vùng mặc định 368,64 ha), chạy tuần tự.; Playwright 1.65 (cài riêng trong testing_report/.pydeps-pw) dùng Chrome hệ thống; UI local chạy bằng uvicorn tại 127.0.0.1:8765.
8. **Input:** API: {"season":"2018–2019","geometry": Polygon 24×24 px trong patch 10003} (evidence/TC03/input_request.json). UI: vùng chọn mặc định do giao diện đề xuất trong vùng Normandy (368,64 ha).
9. **Expected:** Cả hai môi trường: kế hoạch → job 202 → trạng thái queued/running → done; diện tích 5.76 ha; tải được GeoTIFF, CSV, GeoJSON, PNG, ZIP; kết quả Local và Production trùng nhau.
10. **Steps:** (1) API: POST /api/imagery-plan rồi POST /api/analyses, nhận id job. (2) Polling GET /api/analyses/{id} (local 0,3 s; production 2 s) đến khi status=done (timeout 300 s). (3) Tải tif, csv, geojson, png, overlay.png và zip; lưu vào evidence/TC03/<env>/. (4) So sánh phân bố lớp giữa Local và Production. (5) UI: chạy python -m scripts.tc03_frontend_ui <url> <nhãn>; script mở trang, chờ trạng thái "Ready to analyze", chụp ảnh, bấm "Analyze selected area", chụp ảnh lúc đang chạy, chờ bảng kết quả, chụp ảnh, mở hộp thoại tải về. (6) So sánh bảng kết quả UI giữa local và production. — lệnh: `cd testing_report && $PY -m scripts.tc03_e2e_workflow`
11. **Actual:** Local: 3.69 s (suy luận 3.05 s); Production: 6.46 s (suy luận 2.11 s); phân bố lớp giống nhau: True.
12. **Status:** PASS (9/9 assertion)
13. **Evidence:** `testing_report/evidence/TC03/`
14. **Nhận xét:** Luồng đầy đủ hoạt động trên cả hai môi trường. Kết quả local và production trùng nhau ở cả job API (576 pixel) lẫn job UI (368,59 ha, bảng 14 lớp giống hệt). Thời gian từ lúc bấm nút đến khi có kết quả trên production lớn hơn local (máy ARM64, 2 CPU so với laptop i5-12500H), xem bảng chỉ số.

## TC04 — Output Format & Data Integrity

1. **ID:** TC04
2. **Tên:** Output Format & Data Integrity
3. **Loại:** Automation
4. **Mục tiêu:** Đảm bảo dữ liệu đầu ra đúng định dạng và nhất quán nội tại: GeoTIFF (uint8, nodata 255, pixel 10 m, CRS đúng, metadata checkpoint), CSV khớp từng pixel với GeoTIFF, GeoJSON hợp lệ và diện tích trắc địa khớp diện tích báo cáo, ZIP đủ thành phần; đồng thời xác nhận kết quả Local và Production trùng từng pixel.
5. **Thành phần:** inference.export_result, endpoint download/{tif,csv,geojson,png,zip}.
6. **Môi trường:** Local + Production (artifacts TC03)
7. **Điều kiện tiên quyết:** Đã chạy TC03 (TC04 chỉ đọc file đã tải về, không gửi request mới tới production).
8. **Input:** Các file trong evidence/TC03/local/ và evidence/TC03/production/.
9. **Expected:** GeoTIFF đúng kiểu/CRS/nodata/độ phân giải và có metadata checkpoint; CSV khớp GeoTIFF; GeoJSON hợp lệ và diện tích khớp; ZIP đủ file; Local và Production trùng từng pixel.
10. **Steps:** (1) Đọc GeoTIFF bằng rasterio: kiểu dữ liệu, nodata, CRS, kích thước pixel, tag. (2) Đếm pixel theo lớp từ GeoTIFF và so với summary.csv; kiểm tra tổng diện tích và tổng phần trăm. (3) Đọc GeoJSON: kiểm tra FeatureCollection, class_id, ring khép kín; tính diện tích trắc địa (pyproj.Geod, WGS84) và so với area_ha. (4) Kiểm tra danh sách file trong ZIP. (5) So sánh GeoTIFF Local và Production từng pixel; so sánh tọa độ GeoJSON. — lệnh: `cd testing_report && $PY -m scripts.tc04_output_integrity`
11. **Actual:** Mọi kiểm tra định dạng đạt ở cả hai môi trường; GeoTIFF khác 0 pixel; toạ độ GeoJSON lệch tối đa 7.105427357601002e-15 độ.
12. **Status:** PASS (20/20 assertion)
13. **Evidence:** `testing_report/evidence/TC04/`
14. **Nhận xét:** Mọi kiểm tra định dạng đều đạt. File GeoJSON của production dài hơn 4 byte do cách in số thực khác nhau trên ARM64, nhưng tọa độ chỉ lệch tối đa khoảng 7·10⁻¹⁵ độ, coi như giống hệt.

## TC05 — Model Prediction Quality

1. **ID:** TC05
2. **Tên:** Model Prediction Quality
3. **Loại:** AI Test
4. **Mục tiêu:** Đánh giá chất lượng dự đoán của mô hình TSViT (checkpoint thật) so với ground truth chính thức của PASTIS bằng Overall Accuracy, mIoU, macro-F1, IoU theo lớp và confusion matrix.
5. **Thành phần:** inference.preprocess + Engine.predict (TSViT), PreparedProvider.window/window_doy.
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Có S2_10003.npy + TARGET_10003.npy (Fold 5, tập test, không dùng để huấn luyện) và S2_10000.npy + TARGET_10000.npy (Fold 1, tập huấn luyện, chỉ để tham khảo).
8. **Input:** Patch 10003: 43 ảnh Sentinel-2 × 10 band × 120×120 px, chia 25 cửa sổ 24×24; nhãn = kênh 0 của TARGET (cắt 120×120 góc trên-trái giống prepare_data.py); bỏ nhãn void (19).
9. **Expected:** Trên patch held-out 10003: OA >= 0.70 và mIoU >= 0.40; nhãn hợp lệ 0..18.
10. **Steps:** (1) Nạp Engine (xác minh SHA-256 checkpoint). (2) Với mỗi cửa sổ 24×24: lấy chuỗi ảnh và DOY từ provider, chạy predict. (3) Ghép 25 cửa sổ thành bản đồ 120×120, so với ground truth, bỏ pixel void. (4) Tính OA, mIoU (các lớp xuất hiện), macro-F1, IoU theo lớp, confusion matrix. (5) Đối chiếu với ngưỡng đặt trước: OA ≥ 0,70 và mIoU ≥ 0,40. — lệnh: `cd testing_report && $PY -m scripts.tc05_prediction_quality`
11. **Actual:** 10003: OA=0.8734, mIoU=0.7089, macro-F1=0.7835; 10000 (training, tham khảo): OA=0.9166, mIoU=0.6581
12. **Status:** PASS (3/3 assertion)
13. **Evidence:** `testing_report/evidence/TC05/`
14. **Nhận xét:** Trên patch held-out, mô hình đạt kết quả vượt ngưỡng. Chỉ số trên patch 10000 không được dùng để kết luận vì patch này thuộc tập huấn luyện. Hạn chế chính: tại local chỉ có MỘT patch test có ground truth (12.941 pixel hợp lệ), nên đây là đánh giá mang tính chỉ báo và không thay thế đánh giá trên toàn bộ fold test PASTIS.

## TC06 — Model Robustness to Noise

1. **ID:** TC06
2. **Tên:** Model Robustness to Noise
3. **Loại:** AI Test
4. **Mục tiêu:** Đánh giá độ bền của mô hình trước nhiễu ngẫu nhiên tự nhiên (sai số cảm biến/khí quyển) bằng cách cộng nhiễu Gauss vào phản xạ phổ ở nhiều mức và đo mức suy giảm chất lượng.
5. **Thành phần:** Engine.predict / preprocess (chuẩn hóa MEAN/STD theo band).
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Như TC05.
8. **Input:** Patch 10003; σ ∈ {0; 0,05; 0,1; 0,2; 0,5; 1,0} × STD của từng band; 3 seed cho mỗi mức (riêng σ = 0 chỉ chạy 1 lần).
9. **Expected:** Nhiễu nhỏ (σ=0.1·STD) làm OA giảm không quá 5 điểm %, σ=0.2·STD không quá 10 điểm %; mô hình không lỗi ở mọi mức nhiễu.
10. **Steps:** (1) Dự đoán trên dữ liệu gốc làm mốc. (2) Với mỗi mức σ và seed: x' = x + N(0, (σ·STD_band)²) trên phản xạ thô, rồi đưa qua pipeline chuẩn. (3) Tính OA, mIoU, tỉ lệ trùng với dự đoán sạch và confidence trung bình. (4) So với tiêu chí đặt trước: σ=0,1 làm OA giảm ≤ 0,05; σ=0,2 làm OA giảm ≤ 0,10. — lệnh: `cd testing_report && $PY -m scripts.tc06_noise_robustness`
11. **Actual:** OA sạch=0.8734; σ=0.1 → 0.8779 (giảm -0.0045); σ=0.2 → 0.8567 (giảm 0.0167); σ=1.0 → 0.2287.
12. **Status:** PASS (3/3 assertion)
13. **Evidence:** `testing_report/evidence/TC06/`
14. **Nhận xét:** Mô hình bền với nhiễu nhỏ và vừa. Ở mức nhiễu lớn (σ ≥ 0,5·STD), OA sụp xuống khoảng 0,23–0,26 nhưng confidence trung bình vẫn ở mức 0,83–0,94: mô hình quá tự tin trên dữ liệu đã hỏng. Điểm này có cùng nguyên nhân với TC08 và AT06. Lưu ý thêm: mIoU dao động mạnh giữa các seed vì một số lớp chỉ có vài pixel.

## TC07 — Temporal Data Consistency

1. **ID:** TC07
2. **Tên:** Temporal Data Consistency
3. **Loại:** AI Test
4. **Mục tiêu:** Đánh giá tính nhất quán theo thời gian: (1) suy luận có tất định không; (2) mô hình chịu được việc thiếu mốc ảnh (mây che, mất ảnh) đến mức nào, kể cả khi mất cả một mùa.
5. **Thành phần:** Engine.predict; preprocess (CutOrPad về 60 mốc, mã hóa DOY).
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Như TC05.
8. **Input:** Patch 10003 (43 mốc). Kịch bản: bỏ ngẫu nhiên 10/25/50/75% mốc (3 seed), bỏ theo mùa (hè DOY 152–243, xuân 60–151, đông, nửa cuối năm). Mốc bị bỏ được loại cùng DOY tương ứng.
9. **Expected:** Kết quả tất định; mất 25% mốc thời gian làm OA giảm <= 5 điểm %, mất 50% giảm <= 15 điểm %.
10. **Steps:** (1) Chạy suy luận 2 lần trên dữ liệu gốc và so sánh từng pixel (tính tất định). (2) Với mỗi kịch bản: chọn chỉ số mốc giữ lại (giữ thứ tự), cắt ảnh và DOY tương ứng, chạy dự đoán. (3) Tính OA/mIoU và tỉ lệ trùng với dự đoán đầy đủ. (4) So với tiêu chí: mất 25% → OA giảm ≤ 0,05; mất 50% → OA giảm ≤ 0,15. — lệnh: `cd testing_report && $PY -m scripts.tc07_temporal_consistency`
11. **Actual:** Tất định: True; OA đầy đủ=0.8734, mất 25% → 0.8826, 50% → 0.8439, 75% → 0.763. mất mùa hè (DOY 152–243): 0.6231; mất mùa xuân (DOY 60–151): 0.8628; mất mùa đông (DOY 1–59 & 335–365): 0.8752; chỉ giữ nửa đầu năm (DOY <= 182): 0.7456
12. **Status:** PASS (3/3 assertion)
13. **Evidence:** `testing_report/evidence/TC07/`
14. **Nhận xét:** Suy luận hoàn toàn tất định. Mô hình chịu tốt việc mất ngẫu nhiên tới 50% số mốc. Mất theo mùa thì có tác động khác nhau tùy mùa (xem bảng chỉ số), cho thấy giai đoạn sinh trưởng nào mang nhiều thông tin nhất. Trường hợp thao túng có chủ đích như đảo thứ tự hay sai DOY được kiểm thử riêng ở AT05.

## TC08 — Out-of-Distribution Behavior

1. **ID:** TC08
2. **Tên:** Out-of-Distribution Behavior
3. **Loại:** AI Test
4. **Mục tiêu:** Quan sát hành vi của mô hình trên dữ liệu khác phân phối huấn luyện (domain shift): vùng Normandy 23 × 23 km do hệ thống tự chuẩn bị từ THEIA L2A COG (pipeline khác PASTIS), so với 8 patch test PASTIS (in-distribution). Kỳ vọng mô hình thể hiện độ bất định cao hơn (confidence thấp hơn) khi gặp dữ liệu lạ.
5. **Thành phần:** Engine.predict (softmax confidence), PreparedProvider (mosaic COG).
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Dữ liệu data/cog/ (vùng 900010) và 8 patch test PASTIS.
8. **Input:** In-distribution: 8 patch test × 25 cửa sổ = 115.200 pixel. Domain shift: 100 cửa sổ 24×24 chọn ngẫu nhiên (seed 0) trong các cửa sổ hợp lệ của vùng 900010 = 57.600 pixel.
9. **Expected:** Mô hình chạy ổn định trên dữ liệu ngoài phân phối huấn luyện và thể hiện độ bất định cao hơn (mean confidence thấp hơn ít nhất 0.05 so với in-distribution).
10. **Steps:** (1) Chạy dự đoán trên mọi cửa sổ của 8 patch test. (2) Chọn ngẫu nhiên 100 cửa sổ hợp lệ của vùng Normandy, chạy dự đoán. (3) So sánh phân bố confidence, tỉ lệ pixel confidence < 0,5 / < 0,7 và phân bố lớp. (4) Đối chiếu tiêu chí: confidence trung bình trên domain shift thấp hơn ít nhất 0,05. — lệnh: `cd testing_report && $PY -m scripts.tc08_ood_behavior`
11. **Actual:** Mean confidence ID=0.8782, Normandy=0.9417; tỉ lệ pixel confidence<0.5: ID=0.0289, Normandy=0.0115.
12. **Status:** FAIL (1/2 assertion)
13. **Evidence:** `testing_report/evidence/TC08/`
14. **Nhận xét:** FAIL theo tiêu chí đã đặt trước: trên dữ liệu Normandy, mô hình còn tự tin HƠN so với dữ liệu in-distribution. Có hai cách giải thích mà thực nghiệm này chưa phân biệt được: (a) dữ liệu Normandy thực chất gần phân phối huấn luyện (cùng Sentinel-2, cùng nước Pháp) nên dự đoán có thể đúng; (b) softmax confidence không phải thước đo độ bất định đáng tin cậy. Vì không có ground truth cho Normandy, báo cáo không kết luận về độ chính xác. Kết hợp với TC06 và AT06 (confidence ≈ 1 trên ảnh rác), có thể kết luận rằng hệ thống chưa có cơ chế phát hiện dữ liệu ngoài phân phối.

## TC09 — External Service Failure

1. **ID:** TC09
2. **Tên:** External Service Failure
3. **Loại:** Mock Test
4. **Mục tiêu:** Kiểm tra hệ thống xử lý đúng khi dịch vụ dữ liệu vệ tinh bên ngoài (GEODES/THEIA của CNES) gặp sự cố: mất kết nối, timeout, HTTP 503, thiếu khóa API, lỗi giữa chừng khi tải ảnh.
5. **Thành phần:** imagery.GeodesProvider (plan/search/prepare), app.imagery_plan, app.analyze, app.run_analysis.
6. **Môi trường:** Local (mock)
7. **Điều kiện tiên quyết:** Không cần mạng. Chế độ geodes được bật cho app trong test (app.state.source_mode = "geodes"), dùng khóa API giả.
8. **Input:** S1–S3: mã GeodesProvider chạy thật, nhưng httpx.Client tạo bên trong imagery.py nhận MockTransport trả ConnectError/ReadTimeout/HTTP 503. S4: GEODES_API_KEY rỗng. S5–S6: GeodesProvider.prepare ném ImageryError / RemoteProtocolError chứa tên host nội bộ giả.
9. **Expected:** Khi dịch vụ ảnh vệ tinh lỗi (mất kết nối, timeout, HTTP 503, thiếu khóa API, lỗi giữa job), API trả mã lỗi phù hợp (502/503) hoặc job chuyển status=error, không có HTTP 500, không lộ chi tiết nội bộ, dịch vụ vẫn hoạt động.
10. **Steps:** (1) Khởi động app thật bằng TestClient, chuyển sang chế độ geodes. (2) Với từng kịch bản, áp mock bằng unittest.mock.patch, gửi request, ghi lại response/trạng thái job. (3) Kiểm tra mã lỗi (502/503), trạng thái job (error), không lộ chi tiết nội bộ. (4) Kiểm tra /api/health và hàng đợi sau các lỗi. — lệnh: `cd testing_report && $PY -m scripts.tc09_external_service_failure`
11. **Actual:** S1 Mất kết nối GEODES=OK; S1 Request thực sự đi qua lớp mạng (mock được gọi)=OK; S2 GEODES timeout=OK; S3 GEODES trả HTTP 503=OK; S4 Thiếu GEODES_API_KEY=OK; S5 Lỗi ImageryError giữa chừng=OK; S6 Lỗi mạng bất ngờ=OK; S7 Sau các lỗi, /api/health vẫn 200 và hàng đợi rỗng=OK
12. **Status:** PASS (8/8 assertion)
13. **Evidence:** `testing_report/evidence/TC09/`
14. **Nhận xét:** Hệ thống xử lý lỗi dịch vụ ngoài tốt: trả 502/503 có thông báo thân thiện, job lỗi chuyển sang status=error, chi tiết nội bộ chỉ ghi vào log máy chủ. Đây là MOCK TEST: không có dữ liệu GEODES thật nào được tải. Production đang chạy chế độ prepared (offline) nên không phụ thuộc GEODES khi vận hành.

## TC10 — Model Inference Failure

1. **ID:** TC10
2. **Tên:** Model Inference Failure
3. **Loại:** Mock Test
4. **Mục tiêu:** Kiểm tra khả năng chịu lỗi của khâu suy luận: mô hình ném exception giữa chừng, trả output hỏng, lỗi đọc dữ liệu ảnh; worker phải phục hồi để xử lý job tiếp theo; checkpoint bị sửa đổi phải bị từ chối ngay khi khởi động.
5. **Thành phần:** app.run_analysis (xử lý ngoại lệ), Engine.__init__ + verify_model (kiểm tra toàn vẹn checkpoint), lifespan.
6. **Môi trường:** Local (mock)
7. **Điều kiện tiên quyết:** Như TC05. S5 dùng bản sao checkpoint trong thư mục tạm (checkpoint gốc không bị chỉnh sửa).
8. **Input:** Job phân tích ô 48×48 px (4 cửa sổ) của patch 10003. S1: predict ném RuntimeError ở cửa sổ thứ 2 (thông điệp chứa đường dẫn nội bộ giả). S2: predict trả (None, None). S3: provider.window ném OSError. S5: checkpoint bị lật 1 byte (cùng kích thước).
9. **Expected:** Lỗi suy luận/đọc dữ liệu làm job chuyển status=error với thông báo chung, không lộ chi tiết nội bộ, không ghi kết quả dở dang; worker phục hồi để chạy job kế tiếp; checkpoint bị sửa đổi bị từ chối ngay khi khởi động.
10. **Steps:** (1) Khởi động app thật, áp mock lên engine.predict hoặc provider.window, gửi job và chờ kết thúc. (2) Kiểm tra status, thông báo, file kết quả dở dang, mã 409 khi tải kết quả của job lỗi. (3) Gửi một job thật không mock để kiểm tra khả năng phục hồi. (4) Tạo bản sao checkpoint bị sửa, khởi tạo Engine và khởi động app với bản sao đó. — lệnh: `cd testing_report && $PY -m scripts.tc10_inference_failure`
11. **Actual:** S1=OK; S1=OK; S1=OK; S2=OK; S3=OK; S4=OK; S4=OK; S5=OK; S5=OK
12. **Status:** PASS (9/9 assertion)
13. **Evidence:** `testing_report/evidence/TC10/`
14. **Nhận xét:** Lỗi suy luận được cô lập trong từng job: job chuyển sang error với thông báo chung, không để lại kết quả dở dang, worker vẫn xử lý job tiếp theo, và checkpoint bị giả mạo bị từ chối nhờ kiểm tra SHA-256. Đây là MOCK TEST (lỗi được tiêm có chủ đích); riêng S4 là suy luận thật.

## AT01 — Tấn công đầu vào sai cấu trúc

1. **ID:** AT01
2. **Tên:** Tấn công đầu vào sai cấu trúc
3. **Loại:** Security attack (tầng API)
4. **Mục tiêu:** Đánh giá ranh giới kiểm tra kiểu và cấu trúc yêu cầu.
5. **Thành phần:** AnalysisRequest và POST /api/analyses
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 60, "max_concurrency": 1, "max_seconds": 60}
8. **Input:** JSON hỏng, content-type sai, sai kiểu, thiếu trường, trường thừa.
9. **Expected:** Mọi đầu vào sai trả 422, không lộ stack trace và không tạo thư mục job.
10. **Steps:** (1) Khởi động app thật bằng FastAPI TestClient (lệnh ở cuối bảng). (2) Gửi lần lượt 12 payload sai tới POST /api/analyses: JSON hỏng (bị cắt cụt), Content-Type text/plain, body {} và thiếu trường, geometry là chuỗi/mảng/số, season là số nguyên, patch_id là chuỗi "10003", số thực 10003.0, số rất lớn 2^70, và payload có thêm trường lạ. (3) Với mỗi lượt: ghi mã HTTP, kiểm tra body không chứa "Traceback", đếm thư mục job mới trong RESULTS. (4) Hủy (DELETE) mọi job ngoài dự kiến để không chiếm worker. (5) So sánh với kỳ vọng: 422, không có 500, không tạo job. — lệnh: `cd testing_report && $PY -m scripts.at01_malformed_input`
11. **Actual:** Có 3 / 12 payload sai được chấp nhận hoặc xử lý khác 422.
12. **Status:** FAIL (30/36 assertion)
13. **Evidence:** `testing_report/evidence/AT01/`
14. **Nhận xét:** Không có HTTP 500, không lộ stack trace. Ba trường hợp "FAIL" đến từ chế độ ép kiểu mặc định (lax mode) của Pydantic: patch_id dạng chuỗi "10003" hoặc số thực 10003.0 được ép về số nguyên, còn trường thừa thì bị bỏ qua. Cả ba vẫn tạo job hợp lệ trên dữ liệu được phép. Đây là điểm cần làm chặt (strict schema) chứ chưa phải lỗ hổng khai thác được.

## AT02 — Tấn công payload quá lớn

1. **ID:** AT02
2. **Tên:** Tấn công payload quá lớn
3. **Loại:** Security attack (tầng API / tài nguyên)
4. **Mục tiêu:** Đo khả năng chặn tiêu thụ tài nguyên ở tầng body và cấu trúc.
5. **Thành phần:** HTTP parser, Pydantic, imagery-plan
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 5, "max_concurrency": 1, "max_body_bytes": 20971520, "max_seconds": 60}
8. **Input:** 101 đỉnh, 100000 đỉnh, trường thừa chứa 6 MiB ký tự, JSON lồng sâu 1100.
9. **Expected:** Payload 101/100000 đỉnh, JSON 6 MiB và JSON sâu 1100 mức bị từ chối bằng 422/413; dịch vụ còn phản hồi.
10. **Steps:** (1) Đo RSS của tiến trình trước khi tấn công. (2) Gửi polygon 101 đỉnh (vượt giới hạn 100) và polygon 100.000 đỉnh tới /api/imagery-plan, ghi mã HTTP và độ trễ. (3) Gửi body JSON hợp lệ kèm một trường thừa chứa chuỗi 6 MiB. (4) Gửi JSON lồng sâu 1.100 mức mảng. (5) Gọi /api/health để xác nhận dịch vụ còn sống; đo lại RSS. (6) Đối chiếu: mong đợi 413/422, không có 500. — lệnh: `cd testing_report && $PY -m scripts.at02_oversized_payload`
11. **Actual:** HTTP từng payload: [422, 422, 200, 500].
12. **Status:** FAIL (3/5 assertion)
13. **Evidence:** `testing_report/evidence/AT02/`
14. **Nhận xét:** Polygon 101 đỉnh và 100.000 đỉnh bị từ chối đúng (422). Có hai phát hiện thật: (1) ứng dụng nhận body 6 MiB vì không có giới hạn kích thước body ở tầng ứng dụng; (2) JSON lồng sâu 1.100 mức gây HTTP 500 do RecursionError (đã tái hiện, xem evidence/AT07/root_cause_reproduction.txt). Trên production, file Caddy mẫu của repo đặt request_body max_size 1MB, nhưng cấu hình thực tế trên máy chủ CHƯA được xác minh và không được kiểm thử trên production theo nguyên tắc an toàn.

## AT03 — Dồn yêu cầu API có giới hạn

1. **ID:** AT03
2. **Tên:** Dồn yêu cầu API có giới hạn
3. **Loại:** Security / availability (flooding có giới hạn)
4. **Mục tiêu:** Kiểm tra tính sẵn sàng và giới hạn hàng đợi khi có đợt tải ngắn.
5. **Thành phần:** health, analyses, hàng đợi ThreadPoolExecutor
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 310, "max_concurrency": 8, "max_seconds": 120, "health_requests": 200, "analysis_requests": 12}
8. **Input:** Đợt tải health và yêu cầu suy luận 24x24 px hợp lệ.
9. **Expected:** 200 GET health đều 200 với p95 dưới 1000 ms; đợt 12 POST có 429 khi hàng đợi đủ 4; mọi job được hủy và dịch vụ còn sống.
10. **Steps:** (1) Bước tải đọc: 200 GET /api/health bằng 8 luồng song song (ThreadPoolExecutor), ghi độ trễ từng request và tính p50/p95. (2) Bước tải ghi: gửi nhanh 12 POST /api/analyses hợp lệ (ô 24×24 px) liên tiếp. (3) Đếm số yêu cầu nhận 202 và số yêu cầu bị từ chối 429 (hàng đợi đầy khi có ≥ 4 job chờ). (4) Hủy tất cả job đã tạo bằng DELETE /api/analyses/{id}. (5) Đối chiếu: không có lỗi ở health, hàng đợi bị chặn ở 4 job. — lệnh: `cd testing_report && $PY -m scripts.at03_api_flooding`
11. **Actual:** Health lỗi=0; POST nhận=4, từ chối 429=8.
12. **Status:** PASS (6/6 assertion)
13. **Evidence:** `testing_report/evidence/AT03/`
14. **Nhận xét:** Cơ chế giới hạn hàng đợi (tối đa 4 job chờ, vượt thì trả 429) hoạt động đúng, và /api/health vẫn nhanh dưới tải 8 luồng song song. Tuy vậy hệ thống chưa có rate limit theo IP hay xác thực, nên một client vẫn có thể chiếm cả 4 vị trí trong hàng đợi.

## AT04 — Nhiễu đối kháng FGSM và PGD

1. **ID:** AT04
2. **Tên:** Nhiễu đối kháng FGSM và PGD
3. **Loại:** Adversarial attack (white-box, cấp mô hình)
4. **Mục tiêu:** Định lượng độ nhạy white-box của checkpoint với nhiễu nhỏ và đối chứng ngẫu nhiên cùng chuẩn.
5. **Thành phần:** TSViT thật; kênh ảnh chuẩn hóa, giữ nguyên DOY và padding
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_windows": 3, "max_model_forwards": 100, "max_seconds": 540, "pgd_steps": 3, "seed": 20261114}
8. **Input:** Gradient cross-entropy theo GT, bỏ void=19; chỉ thay 10 kênh phổ của frame thật.
9. **Expected:** Ở epsilon <=0.05 trong không gian chuẩn hóa, accuracy và mIoU không giảm quá 5 điểm phần trăm so với ảnh sạch trên cùng pixel hợp lệ.
10. **Steps:** (1) Nạp checkpoint thật; lấy 3 cửa sổ 24×24 của patch 10003 tại vị trí (0,0), (48,48), (96,96) cùng ground truth. (2) Tính gradient của hàm loss theo đầu vào đã chuẩn hóa (white-box). (3) FGSM: x' = x + ε·sign(∇x), với ε ∈ {0,01; 0,05; 0,1}. (4) PGD: 3 bước lặp, chiếu lại vào quả cầu ε sau mỗi bước. (5) Nhiễu ngẫu nhiên có cùng chuẩn để so sánh. (6) Tính accuracy/mIoU từng trường hợp và vẽ biểu đồ theo ε; đối chiếu với tiêu chí giảm ≤ 5 điểm %. — lệnh: `cd testing_report && $PY -m scripts.at04_adversarial_noise`
11. **Actual:** Accuracy sạch 0.8378; giảm lớn nhất 0.6923 tại PGD, epsilon=0.1.
12. **Status:** FAIL (0/8 assertion)
13. **Evidence:** `testing_report/evidence/AT04/`
14. **Nhận xét:** Đây là điểm yếu của MÔ HÌNH, không phải lỗ hổng API. Người dùng API không gửi được ảnh vệ tinh tùy ý, vì ảnh do máy chủ đọc từ dữ liệu đã chuẩn bị. Muốn khai thác, kẻ tấn công cần chiếm được chuỗi cung cấp dữ liệu. Thực nghiệm dùng FGSM/PGD trong không gian đã chuẩn hóa trên 3 cửa sổ của patch 10003, nên accuracy gốc (0,8378) khác với TC05 (25 cửa sổ). Nhiễu có hướng gradient làm giảm accuracy mạnh hơn nhiều so với nhiễu ngẫu nhiên cùng độ lớn.

## AT05 — Thao túng chuỗi thời gian và ngày quan sát

1. **ID:** AT05
2. **Tên:** Thao túng chuỗi thời gian và ngày quan sát
3. **Loại:** Adversarial / robustness (thao túng chuỗi thời gian)
4. **Mục tiêu:** Đánh giá ảnh hưởng việc ghép sai ảnh-ngày và thiếu đa dạng thời gian trên toàn patch test.
5. **Thành phần:** PreparedProvider, preprocess, TSViT
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_windows": 25, "max_model_forwards": 225, "max_seconds": 540, "seed": 20261114}
8. **Input:** Ảnh thật cùng GT, thay đổi trật tự hoặc ngày; seed 20261114.
9. **Expected:** Accuracy mỗi biến thể thay thời gian không giảm quá 5 điểm phần trăm; đảo cả ảnh và DOY là đối chứng bất biến; DOY 0/366 bị ValueError.
10. **Steps:** (1) Với cả 25 cửa sổ của patch 10003, lấy chuỗi ảnh và DOY gốc. (2) Tạo các biến thể: đảo thứ tự ảnh (giữ DOY), xáo trộn ảnh (giữ DOY), đảo đồng thời ảnh + DOY, lệch DOY −60/−30/+30/+60 ngày (giới hạn trong 1–365), lặp frame đầu cho mọi mốc. (3) Chạy dự đoán từng biến thể và tính accuracy so với ground truth. (4) Kiểm tra thêm: DOY ngoài 1–365 phải bị preprocess từ chối. (5) Đối chiếu với tiêu chí giảm ≤ 5 điểm %. — lệnh: `cd testing_report && $PY -m scripts.at05_temporal_manipulation`
11. **Actual:** Accuracy theo biến thể: clean=0.8734, reverse_images=0.2739, shuffle_images=0.4822, reverse_pairs=0.8734, doy_-60=0.5573, doy_-30=0.6905, doy_30=0.7153, doy_60=0.3819, duplicate_first=0.1593.
12. **Status:** FAIL (3/10 assertion)
13. **Evidence:** `testing_report/evidence/AT05/`
14. **Nhận xét:** Mô hình phụ thuộc mạnh vào việc ảnh và DOY khớp nhau đúng thứ tự: đảo ảnh, xáo trộn ảnh, lệch DOY ±30–60 ngày hoặc lặp một frame đều làm accuracy giảm mạnh. Ngược lại, khi đảo ĐỒNG THỜI cả ảnh và DOY (reverse_pairs) thì kết quả không đổi, tức mô hình dựa vào DOY chứ không vào vị trí trong chuỗi. Đây là robustness của mô hình; người dùng API không gửi được chuỗi thời gian tùy ý. Nó cho thấy cần kiểm tra lịch thu nhận (DOY tăng dần, không trùng lặp) trong pipeline chuẩn bị dữ liệu.

## AT06 — Đầu vào ngoài phân bố

1. **ID:** AT06
2. **Tên:** Đầu vào ngoài phân bố
3. **Loại:** Robustness (dữ liệu tổng hợp ngoài phân phối)
4. **Mục tiêu:** Kiểm tra mô hình có đưa dự đoán tự tin trên ảnh vô nghĩa khi không có cổng OOD.
5. **Thành phần:** preprocess và Engine.predict
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_windows": 3, "max_model_forwards": 18, "max_seconds": 120, "seed": 20261114}
8. **Input:** Tensor ảnh tổng hợp cùng hình dạng và lịch thật; seed 20261114.
9. **Expected:** Ba đầu vào rác zero/cloud/noise có confidence softmax trung bình <=0.60 và tỷ lệ pixel confidence >=0.90 <=10%; ghi nhận riêng ảnh scale và đổi band.
10. **Steps:** (1) Lấy 3 cửa sổ thật của patch 10003 làm mốc so sánh. (2) Tạo đầu vào tổng hợp cùng kích thước: toàn 0; hằng số 10000 (giống mây dày); nhiễu đều [0, 10000]; ảnh thật nhân 3; ảnh thật đảo thứ tự band. (3) Chạy dự đoán, ghi confidence trung bình, tỉ lệ pixel confidence ≥ 0,9 và phân bố lớp. (4) Đối chiếu: dữ liệu rác phải có confidence thấp (≤ 0,60) và ít pixel quá tự tin (≤ 10%). — lệnh: `cd testing_report && $PY -m scripts.at06_ood_input`
11. **Actual:** Confidence trung bình: real=0.936, zeros=1.000, cloud10000=1.000, uniform_noise=0.997, scaled_x3=0.795, band_reversed=1.000.
12. **Status:** FAIL (0/6 assertion)
13. **Evidence:** `testing_report/evidence/AT06/`
14. **Nhận xét:** Mô hình gán nhãn cây trồng với confidence ≈ 1,0 cho ảnh toàn 0, ảnh "mây" bão hòa và nhiễu đều. Điều này xác nhận phát hiện ở TC06/TC08: softmax confidence không thể dùng để phát hiện dữ liệu hỏng. Dữ liệu ở đây là dữ liệu tổng hợp, không phải ground truth, nên test chỉ đánh giá hành vi chứ không đo độ chính xác.

## AT07 — Tấn công GeoJSON không hợp lệ

1. **ID:** AT07
2. **Tên:** Tấn công GeoJSON không hợp lệ
3. **Loại:** Security attack (tầng API)
4. **Mục tiêu:** Kiểm tra cấu trúc, tính hữu hạn, topology và giới hạn phủ của polygon.
5. **Thành phần:** AnalysisRequest.validate_polygon và selection_mask
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 60, "max_concurrency": 1, "max_seconds": 90}
8. **Input:** Ring hở/3 điểm, MultiPolygon, lỗ, NaN/±Infinity, tọa độ ngoài miền/3D, bow-tie, diện tích 0, ngoài phủ, nửa địa cầu.
9. **Expected:** Mọi hình học sai hoặc không hỗ trợ bị 422 trên cả imagery-plan và analyses, không 500, không tạo job.
10. **Steps:** (1) Sinh 13 biến thể GeoJSON: ring hở, 3 điểm, MultiPolygon, Polygon có lỗ, NaN, +Infinity, −Infinity (gửi dạng JSON thô), kinh độ 181/vĩ độ 91, tọa độ 3D, bow-tie tự cắt, diện tích 0, ngoài vùng phủ, nửa địa cầu. (2) Gửi mỗi biến thể tới cả /api/imagery-plan và /api/analyses (26 lượt). (3) Ghi mã HTTP, kiểm tra không có 500, đếm job mới. (4) Hủy job ngoài dự kiến; tái hiện các ca 500 với raise_server_exceptions=True để lấy nguyên nhân gốc (root_cause_reproduction.txt). — lệnh: `cd testing_report && $PY -m scripts.at07_malformed_geojson`
11. **Actual:** Có 8 / 26 trường hợp không trả 422.
12. **Status:** FAIL (44/53 assertion)
13. **Evidence:** `testing_report/evidence/AT07/`
14. **Nhận xét:** Đã tái hiện và xác định nguyên nhân gốc của các lỗi 500 với NaN/±Infinity. Validator VẪN bắt được lỗi, nhưng khi FastAPI dựng thân response 422, nó chép lại giá trị đầu vào chứa NaN và json.dumps từ chối giá trị này ("Out of range float values are not JSON compliant"), nên kết quả thành 500. Không có dữ liệu nào bị ghi. Polygon tự cắt (bow-tie) được chấp nhận vì không có kiểm tra topology. Các ca khác (ring hở, MultiPolygon, tọa độ ngoài miền, ngoài vùng phủ, nửa địa cầu) đều bị chặn đúng.

## AT08 — Can thiệp tham số và định danh tài nguyên

1. **ID:** AT08
2. **Tên:** Can thiệp tham số và định danh tài nguyên
3. **Loại:** Security attack (phân quyền / tham số)
4. **Mục tiêu:** Đánh giá kiểm tra định danh, truy cập dữ liệu ẩn và ranh giới quyền sở hữu job.
5. **Thành phần:** resolve, job_directory, download, pixel, DELETE analyses
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 120, "max_concurrency": 1, "max_seconds": 120}
8. **Input:** ID training/nonexistent/negative, season giả, traversal, UUID viết hoa, format/include giả, lat/lng sai.
9. **Expected:** Patch training ẩn bị từ chối 422 theo chính sách cách ly tập test; patch sai/season sai bị 422; traversal/UUID không chuẩn bị 404; include sai 422; tọa độ sai 422; client khác không được hủy job (401/403).
10. **Steps:** (1) Gửi phân tích với patch_id 10000 (tập huấn luyện, bị ẩn khỏi catalog), patch_id không tồn tại và âm, season giả. (2) Gọi GET /api/analyses/{id} với id dạng ../../weights/best.pth, URL-encoded và UUID viết hoa. (3) Gọi /download/{format} với format giả hoặc traversal; include= chứa định dạng lạ. (4) Gọi /pixel với lat/lng ngoài miền. (5) Client A tạo job, client B (phiên khác) gửi DELETE job đó. (6) Ghi mã HTTP từng trường hợp và đối chiếu với kỳ vọng (404/409/422, hủy chéo bị chặn). — lệnh: `cd testing_report && $PY -m scripts.at08_parameter_tampering`
11. **Actual:** Training explicit ID và DELETE từ client B: [{'case': 'training 10000', 'status': 202}, {'case': 'DELETE client B', 'status': 200, 'response': {'id': '7e5ac0f3-076d-49c2-a4ed-3134ae86109a', 'cancellation_requested': True}}].
12. **Status:** FAIL (15/17 assertion)
13. **Evidence:** `testing_report/evidence/AT08/`
14. **Nhận xét:** Các tham số đường dẫn đều được bảo vệ tốt: path traversal, UUID không chuẩn và format/include giả đều bị chặn. Có hai quan sát thiết kế: (1) patch 10000 thuộc tập huấn luyện không xuất hiện trong catalog nhưng vẫn phân tích được nếu chỉ định patch_id; hệ quả là người dùng có thể "đánh giá" mô hình trên dữ liệu đã huấn luyện, chứ không lộ dữ liệu bí mật; (2) API không có xác thực hay chủ sở hữu job, nên ai biết UUID của job thì có thể xem hoặc hủy job đó. UUIDv4 có 122 bit ngẫu nhiên nên không thể đoán được, rủi ro chỉ xảy ra khi URL bị lộ.

## AT09 — Tiêu thụ tài nguyên vùng Normandy có giới hạn

1. **ID:** AT09
2. **Tên:** Tiêu thụ tài nguyên vùng Normandy có giới hạn
3. **Loại:** Security / availability (resource exhaustion có giới hạn)
4. **Mục tiêu:** Đo chi phí một job lớn và khả năng phản hồi/hủy trong lúc CPU suy luận.
5. **Thành phần:** imagery-plan, worker TSViT, health và DELETE analyses
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_requests": 65, "max_concurrency": 1, "job_run_seconds": 60, "max_seconds": 110, "max_jobs": 1}
8. **Input:** Polygon 2304x2304 px từ catalog thật; một job duy nhất, không gọi production.
9. **Expected:** Kế hoạch vùng Normandy có >1000 cửa sổ; job được nhận; trong 60 giây health luôn 200 và p95 <1000 ms, RSS tăng <1024 MiB; hủy chuyển cancelled trong 15 giây.
10. **Steps:** (1) Gọi /api/imagery-plan cho polygon phủ toàn vùng Normandy 900010 để biết số cửa sổ (9.216). (2) Gửi POST /api/analyses cho polygon đó (1 job duy nhất). (3) Trong 60 s: cứ khoảng 1 s lấy mẫu RSS/CPU của tiến trình, độ trễ /api/health và tiến độ job. (4) Gửi DELETE để hủy, đo thời gian đến khi status=cancelled. (5) Ngoại suy thời gian chạy toàn vùng từ tốc độ cửa sổ/giây (ghi rõ là ngoại suy). (6) Đối chiếu: health vẫn nhanh, hủy có hiệu lực, không tràn bộ nhớ. — lệnh: `cd testing_report && $PY -m scripts.at09_resource_exhaustion`
11. **Actual:** 9216 cửa sổ; đã xử lý 218 trong 60.0s; trạng thái cuối cancelled; hủy 0.511s.
12. **Status:** PASS (8/8 assertion)
13. **Evidence:** `testing_report/evidence/AT09/`
14. **Nhận xét:** Trong thời gian thử 60 s, API vẫn phản hồi và lệnh hủy có hiệu lực ngay, nên test PASS theo tiêu chí. Tuy nhiên kết quả cho thấy một rủi ro khả dụng thật: một yêu cầu HỢP LỆ "Whole region" (9.216 cửa sổ) chiếm worker duy nhất khoảng 42 phút trên máy local (con số NGOẠI SUY từ tốc độ đo được, không chạy hết). Trong thời gian đó, các người dùng khác phải xếp hàng. Production có ít CPU hơn nên thời gian có thể còn dài hơn (lý thuyết, không thử trên production).

## AT10 — Giá trị số và kích thước tensor không hợp lệ

1. **ID:** AT10
2. **Tên:** Giá trị số và kích thước tensor không hợp lệ
3. **Loại:** Security / robustness (giá trị số không hợp lệ)
4. **Mục tiêu:** Kiểm tra ranh giới số học từ preprocess đến job API và hành vi cắt chuỗi.
5. **Thành phần:** preprocess, Engine.predict, run_analysis exception handler
6. **Môi trường:** Local
7. **Điều kiện tiên quyết:** Checkpoint + dữ liệu thật tại local; giới hạn {"max_model_calls": 24, "max_api_requests": 65, "max_concurrency": 1, "max_seconds": 120}
8. **Input:** NaN, +Inf, -Inf, -32768/32767, -1; 23x24, 0/200 frame, DOY lệch độ dài.
9. **Expected:** NaN/±Inf, int16 cực trị, reflectance âm, kích thước sai, T=0 và DOY lệch độ dài bị ValueError sạch; T=200 được cắt đúng 60; job chứa NaN kết thúc error với thông báo chung.
10. **Steps:** (1) Lấy cửa sổ (0,0) của patch 10003 (43 mốc). (2) Thay giá trị bằng NaN, +Inf, −Inf, −32768, 32767, giá trị âm; tạo tensor sai kích thước [T,10,23,24], T = 0, T = 200, độ dài DOY lệch. (3) Gọi trực tiếp preprocess và Engine.predict, ghi lại: có ValueError hay không, output có hữu hạn không. (4) Kiểm tra T = 200 bị cắt về 60. (5) Tiêm NaN vào provider.window trong một job API (unittest.mock) và kiểm tra job kết thúc error với thông báo chung. — lệnh: `cd testing_report && $PY -m scripts.at10_invalid_numerics`
11. **Actual:** 10/18 phép thử tensor bị ValueError; T=200 cắt đúng=True; job NaN=error.
12. **Status:** FAIL (24/32 assertion)
13. **Evidence:** `testing_report/evidence/AT10/`
14. **Nhận xét:** NaN/±Inf, sai kích thước tensor và DOY lệch độ dài đều bị preprocess từ chối; T > 60 được cắt đúng về 60; NaN chèn vào job API làm job kết thúc error. Các ca "FAIL" gồm: chuỗi rỗng (T = 0) vẫn trả dự đoán, và các giá trị phản xạ hữu hạn nhưng bất thường (−32768, 32767, âm) không bị chặn. Theo nhận định của người viết báo cáo, tiêu chí "phải ValueError" cho giá trị âm hoặc bão hòa là khá chặt, vì dữ liệu L2A thực tế có thể chứa các giá trị này. Tuy vậy tiêu chí đã được đặt trước khi chạy nên được giữ nguyên. Riêng việc chấp nhận T = 0 là lỗi kiểm tra đầu vào đáng sửa.
