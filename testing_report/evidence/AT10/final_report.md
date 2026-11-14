**Kết quả AT01–AT10 — cục bộ, checkpoint thật, dữ liệu thật**

Đã tạo và chạy 10 script cùng runner tuần tự `scripts/run_at_all.sh`; 2 PASS, 8 FAIL, 0 BLOCKED. FAIL là phát hiện theo tiêu chí định trước, không phải kịch bản chưa chạy. Không gửi bất kỳ yêu cầu nào đến production, không sửa app/data/weights/tests/common.py và không commit/push.

| AT | Trạng thái | Kết quả thực tế | Chỉ số chính |
|---|---|---|---|
| [AT01](../AT01/result.json) | FAIL | Chuỗi/số thực patch_id bị ép kiểu; bỏ qua trường thừa | 3/12 payload nhận 202 |
| [AT02](../AT02/result.json) | FAIL | 6 MiB được nhận; JSON sâu trả 500 | 100000 đỉnh: 422, 462 ms |
| [AT03](../AT03/result.json) | PASS | Health ổn định; hàng đợi chặn đủ mức | 200 GET, p95 23.32 ms; POST 4×202 + 8×429 |
| [AT04](../AT04/result.json) | FAIL | PGD làm suy giảm mạnh so với nhiễu ngẫu nhiên cùng chuẩn | accuracy 0.8378 → 0.1455 (ε=0.1) |
| [AT05](../AT05/result.json) | FAIL | Ghép sai thời gian/lặp frame làm accuracy giảm; đảo cả cặp bất biến | 25 cửa sổ: sạch 0.8734 → lặp frame 0.1593 |
| [AT06](../AT06/result.json) | FAIL | Ảnh zero/cloud/noise vẫn có confidence gần 1 | noise mean=0.9972, 100% pixel ≥0.9 |
| [AT07](../AT07/result.json) | FAIL | NaN/±Inf trả 500; bow-tie được nhận | 6 lỗi 500; bow-tie plan 200 / job 202 |
| [AT08](../AT08/result.json) | FAIL | ID training ẩn và hủy job từ client B đều được nhận | training 202; DELETE khác client 200 |
| [AT09](../AT09/result.json) | PASS | Job lớn vẫn cho health và hủy phản hồi tốt trong 60 giây | 9216 cửa sổ; 218 đã chạy; hủy 0.511s; p95 3.939 ms |
| [AT10](../AT10/result.json) | FAIL | Chặn NaN/Inf/shape sai; chấp nhận chuỗi rỗng, âm/cực trị | 10/18 ValueError; T=200 cắt 60; NaN job=error |

Phát hiện và ý nghĩa:

- Kiểm tra schema chưa strict: chuỗi/số thực patch_id được ép kiểu và trường thừa bị bỏ qua; đây là khoảng trống so với tiêu chí kiểm thử, không tự động chứng minh khai thác bảo mật.
- Không thấy chặn body 6 MiB tại ứng dụng; payload 1100 tầng gây HTTP 500. Polygon 101/100000 đỉnh bị 422. Không kiểm thử proxy/Caddy nên không suy ra giới hạn production.
- NaN/±Infinity trong raw JSON dẫn tới HTTP 500 ở cả hai endpoint; polygon tự cắt được chấp nhận và tạo job. Các lỗi này nên được chuẩn hóa thành 422 với kiểm tra topology/hữu hạn an toàn.
- Explicit ID vẫn truy cập patch training bị catalog ẩn; client không có token/cookie có thể hủy job nếu biết UUID. Đây là quan sát thiết kế/chính sách cách ly và quyền sở hữu, không chứng minh đoán được UUIDv4.
- Mô hình dễ bị nhiễu white-box: tại ε=0.01, PGD accuracy 0.5897 so với sạch 0.8378 và random cùng chuẩn 0.8396; tại ε=0.1, PGD còn 0.1455. Đây là lỗ hổng độ bền mô hình, không phải lỗi bảo mật API.
- Trên đủ 25 cửa sổ, đảo riêng ảnh làm accuracy 0.8734 → 0.2739; đảo cả ảnh-ngày giữ nguyên nhãn; DOY ngoài miền bị ValueError. Cần bảo vệ cặp ảnh-ngày và dữ liệu lịch thu nhận.
- Ảnh tổng hợp zero/cloud/noise đều có 100% pixel confidence ≥0.9. Dữ liệu tổng hợp không có GT; các chỉ số này là confidence/phân bố lớp, tuyệt đối không phải accuracy.
- T=0 và reflectance âm/cực trị hữu hạn được nhận; NaN/Inf, shape sai và DOY lệch độ dài bị chặn. T=200 được cắt đúng 60 frame; mock NaN provider kết thúc job error với thông báo chung, không lộ stack trace.
- Một job Normandy có 9216 cửa sổ và không có quota theo số cửa sổ; trong 60 giây health p95 3.939 ms, RSS tăng 160.95 MiB, hủy 0.511s. Thời gian toàn vùng 2536.8s (~42.3 phút) là NGOẠI SUY từ tiến độ, không phải một lần chạy hoàn chỉnh.

Giới hạn và tính tái lập:

- Mỗi expected.json được ghi trước khi gửi payload/chạy model; không thay tiêu chí để chuyển FAIL thành PASS. Mỗi result.json có checks, giới hạn tải, bước tái lập tiếng Việt, impact và remediation. Các đồ thị PNG lấy trực tiếp số liệu thực đo; execution.log và log.png được tạo bởi helper chung.
- Lệnh: `cd testing_report && ./scripts/run_at_all.sh`; Python mặc định là môi trường đã cấp. Mỗi script có thể chạy riêng bằng `python -m scripts.atNN_<name>` từ testing_report. Tất cả dùng TestClient, không có đường gọi production.
- AT09 lần đầu bị nhiễu vì tiến trình khác dùng chung RESULTS và startup đánh dấu job là interrupted; coordinator đã cập nhật common.py sang thư mục kết quả theo tiến trình. AT09 được chạy lại nguyên tiêu chí, đối chiếu expected.json bằng byte; các bản ghi không hợp lệ được giữ ở `../AT09/invalid_shared_runtime_result.json`, `invalid_shared_runtime_execution.log`, `invalid_shared_runtime_expected.json` và `rerun_reason.txt`.
- RSS/CPU gồm cả client và server trong cùng tiến trình; CPU 100% là một lõi. AT04/AT06 dùng 3 cửa sổ của một patch; AT05 dùng đủ 25 cửa sổ. GT là TARGET_10003.npy kênh 0 cắt top-left 120×120, bỏ void=19, giữ background=0; mIoU trung bình các lớp có hợp GT/pred khác 0.

Không còn hạng mục thực thi nào bị chặn; các thay đổi khắc phục mã hệ thống nằm ngoài phạm vi nhiệm vụ này.
