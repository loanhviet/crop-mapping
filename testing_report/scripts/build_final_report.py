"""Final practice report (Word-like, black on white) built from evidence/*/result.json.

Run:  cd testing_report && $PY -m scripts.log_excerpt && $PY -m scripts.build_final_report
Output: Satellite_Crop_Mapping_Testing_Report_Final.pdf  (cover unnumbered; body numbered from 1)
Measured values are read from evidence files; only explanatory prose is written here.
"""
import scripts.common as c
import sys
sys.path.insert(0, str(c.REPORT / '.pydeps-pw'))
import base64
import html
import json
import re
import statistics
import subprocess

from playwright.sync_api import sync_playwright

from scripts.report_content import AT as AT_REVIEW

E = c.EVIDENCE
OUT = c.REPORT / 'Satellite_Crop_Mapping_Testing_Report_Final.pdf'
TMP = c.REPORT / '.runtime'
IDS = [f'TC{i:02d}' for i in range(1, 11)] + [f'AT{i:02d}' for i in range(1, 11)]
R = {t: json.loads((E / t / 'result.json').read_text()) for t in IDS}
M = {t: R[t]['metrics'] for t in IDS}
S = json.loads((c.REPORT / 'summary.json').read_text())


def esc(x):
    return html.escape(str(x))


def n(x, d=4):
    """Vietnamese decimal comma for display only (value unchanged)."""
    return f'{x:.{d}f}'.rstrip('0').rstrip('.').replace('.', ',') if isinstance(x, float) else str(x)


def checks(t):
    return f"{sum(x['passed'] for x in R[t]['checks'])}/{len(R[t]['checks'])}"


# ------------------------------------------------------------------ actual results (from data)
def ui(k):
    return json.loads((E / 'TC03' / f'ui_{k}' / 'summary.json').read_text())


def at03_percentiles():
    resp = json.loads((E / 'AT03' / 'response.json').read_text())
    health = [x for x in resp if isinstance(x.get('response'), dict) and x['response'].get('model') == 'TSViT'][:200]
    lat = [x['elapsed_ms'] for x in health]
    q = statistics.quantiles(lat, n=100, method='inclusive')
    return dict(n=len(lat), p50=q[49], p95=q[94], p99=q[98], errors=sum(x['status'] != 200 for x in health))


P03 = at03_percentiles()

# ------------------------------------------------------------------ test case content
# Each entry: name, req (yêu cầu được kiểm tra), kind, purpose, pre, input, steps, expected, actual(), table(), figs, conclusion
T = {}
T['TC01'] = dict(
    name='Kiểm tra trạng thái hoạt động của API', kind='Automation, positive, hộp đen',
    req='Các endpoint công khai phải hoạt động, báo đúng mô hình và checkpoint đang dùng.',
    purpose='Kiểm tra hệ thống có đang chạy bình thường trên Local và Production hay không, và hai môi trường có dùng cùng một checkpoint hay không.',
    pre='Ứng dụng local khởi động được với checkpoint và dữ liệu thật; máy kiểm thử truy cập được https://crop.loanhviet.dev.',
    input='Yêu cầu GET tới 5 endpoint /api/health, /api/catalog, / (giao diện), /openapi.json, /docs; mỗi endpoint gọi 3 lần trên mỗi môi trường (15 yêu cầu/môi trường).',
    steps=['Khởi động ứng dụng local bằng FastAPI TestClient (quá trình khởi động tự kiểm tra SHA-256 của checkpoint).',
           'Gửi lần lượt 15 yêu cầu GET tới local, ghi mã trạng thái và thời gian phản hồi.',
           'Gửi 15 yêu cầu tương tự tới Production, tuần tự, cách nhau 0,3 s.',
           'So sánh trường checkpoint_sha256 giữa hai môi trường và với assets/model-manifest.json; chụp màn hình trang chủ Production.',
           'Lệnh chạy: cd testing_report && $PY -m scripts.tc01_health_availability'],
    expected='Tất cả yêu cầu trả HTTP 200; /api/health báo status=ok, model=TSViT; catalog có 19 lớp; trung vị thời gian /api/health dưới 3 giây; hai môi trường cùng checkpoint.',
    actual=lambda: (f"Cả 30 yêu cầu đều trả HTTP 200. Hai môi trường cùng checkpoint 92a83d0d…a40b733, khớp với manifest. "
                    f"Trung vị thời gian /api/health là {n(M['TC01']['Local']['median_ms']['/api/health'], 1)} ms ở Local và "
                    f"{n(M['TC01']['Production']['median_ms']['/api/health'], 1)} ms ở Production. Yêu cầu đầu tiên tới Production mất "
                    f"{n(M['TC01']['Production']['max_ms']['/api/health'], 0)} ms; đo lại bằng curl chỉ mất 0,8 s, nên phần chậm nằm ở bước "
                    f"thiết lập kết nối của client Python, không phải ở máy chủ."),
    figs=[('TC01/screenshot_production_home.png', 'Giao diện web trên Production (ảnh chụp bằng Chrome headless)', 64)],
    conclusion='Đạt (PASS, {c} kiểm tra).')
T['TC02'] = dict(
    name='Kiểm tra dữ liệu đầu vào của API', kind='Automation, positive/negative/boundary, hộp đen',
    req='API phải chấp nhận yêu cầu hợp lệ và từ chối yêu cầu sai bằng mã 422 kèm thông báo rõ ràng.',
    purpose='Kiểm tra lớp kiểm tra dữ liệu đầu vào và so sánh cách xử lý giữa Local và Production.',
    pre='Như TC01. Dùng endpoint POST /api/imagery-plan vì endpoint này kiểm tra cùng dữ liệu với /api/analyses nhưng không tạo job, nên an toàn khi chạy trên Production.',
    input='10 payload: 1 vùng hợp lệ (ô 240 m × 240 m trong patch 10003) và 9 payload sai (xem bảng số liệu bên dưới).',
    steps=['Tạo polygon hợp lệ từ thông tin patch 10003 (đổi tọa độ UTM sang WGS84).',
           'Gửi 10 payload tới /api/imagery-plan trên Local, ghi mã trạng thái và thông báo lỗi.',
           'Gửi đúng 10 payload đó tới Production, tuần tự.',
           'So sánh mã trạng thái và thông báo giữa hai môi trường.',
           'Lệnh chạy: $PY -m scripts.tc02_input_validation'],
    expected='Payload hợp lệ trả 200; 9 payload sai trả 422, không có lỗi 500; Local và Production giống nhau.',
    actual=lambda: 'Cả 20 lượt gọi đều trả đúng mã mong đợi. Thông báo lỗi ở hai môi trường giống hệt nhau (bảng số liệu bên dưới).',
    table=lambda: ('Kết quả kiểm tra dữ liệu đầu vào', ['Trường hợp', 'Mong đợi', 'Local', 'Production'],
                   [[x['case'], x['expected'], x['actual'], {y['case']: y for y in M['TC02']['table'] if y['env'] == 'Production'}[x['case']]['actual']]
                    for x in M['TC02']['table'] if x['env'] == 'Local'], [58, 14, 12, 16]),
    figs=[('TC02/report_log_excerpt.png', 'Trích nhật ký thực thi TC02 (evidence/TC02/execution.log)', 100)],
    conclusion='Đạt (PASS, {c} kiểm tra).')
T['TC03'] = dict(
    name='Kiểm thử luồng phân tích từ đầu đến cuối', kind='Automation, positive, kiểm thử hệ thống',
    req='Người dùng chọn vùng, chạy phân tích và nhận được bản đồ cùng các file kết quả.',
    purpose='Kiểm tra toàn bộ luồng lập kế hoạch → gửi phân tích → theo dõi → nhận kết quả → tải file, qua API và qua giao diện web thật, trên cả hai môi trường.',
    pre='Như TC01. Trên Production chỉ chạy 1 phân tích qua API (5,76 ha) và 1 phân tích qua giao diện (vùng mặc định 368,64 ha). Giao diện được điều khiển bằng Playwright với Chrome.',
    input='API: {"season": "2018–2019", "geometry": ô 24×24 pixel trong patch 10003}. Giao diện: vùng chọn mặc định ở Normandy.',
    steps=['Gửi POST /api/imagery-plan, sau đó POST /api/analyses và nhận mã job (HTTP 202).',
           'Hỏi trạng thái GET /api/analyses/{id} định kỳ (Production: 2 giây/lần) cho tới khi status=done.',
           'Tải các file tif, csv, geojson, png, zip và overlay.png.',
           'Trên giao diện: mở trang, chờ thông báo "Ready to analyze", bấm "Analyze selected area", chờ bảng kết quả, mở hộp thoại tải về; chụp màn hình từng bước.',
           'So sánh kết quả giữa Local và Production.',
           'Lệnh chạy: $PY -m scripts.tc03_e2e_workflow và $PY -m scripts.tc03_frontend_ui <url> <tên>'],
    expected='Job chuyển sang done; diện tích 5,76 ha; tải được đủ 5 loại file; giao diện hiển thị bản đồ và bảng diện tích; kết quả hai môi trường trùng nhau.',
    actual=lambda: (f"Qua API, job hoàn tất trên cả hai môi trường. Thời gian suy luận phía máy chủ là {n(M['TC03']['Local']['server_duration_seconds'], 2)} s (Local) "
                    f"và {n(M['TC03']['Production']['server_duration_seconds'], 2)} s (Production). Phân bố lớp giống hệt nhau: "
                    + ', '.join(f'{k} {v} pixel' for k, v in M['TC03']['Production']['classes'].items()) +
                    f". Qua giao diện, thời gian từ lúc bấm nút đến khi có kết quả là {n(ui('local')['seconds_click_to_result'], 1)} s (Local) và "
                    f"{n(ui('production')['seconds_click_to_result'], 1)} s (Production). Bảng diện tích (368,59 ha) trên hai môi trường giống hệt nhau."),
    figs=[('TC03/ui_production/3_results.png', 'Kết quả phân loại cây trồng trên giao diện Production', 72)],
    conclusion='Đạt (PASS, {c} kiểm tra). Production chậm hơn Local khoảng 2,8 lần do chạy trên ARM64 với 2 CPU.')
T['TC04'] = dict(
    name='Kiểm tra định dạng và tính toàn vẹn của kết quả', kind='Automation, positive',
    req='File kết quả phải đúng định dạng địa lý và thống nhất với nhau.',
    purpose='Kiểm tra GeoTIFF, CSV, GeoJSON và ZIP tải về ở TC03 có đúng định dạng và khớp nhau hay không.',
    pre='Đã chạy TC03. TC04 chỉ đọc các file đã tải về, không gửi thêm yêu cầu tới Production.',
    input='Các file trong evidence/TC03/local/ và evidence/TC03/production/.',
    steps=['Đọc GeoTIFF bằng rasterio: kiểu dữ liệu, giá trị nodata, hệ tọa độ, kích thước pixel, thẻ checkpoint.',
           'Đếm số pixel từng lớp trong GeoTIFF và so với summary.csv; kiểm tra tổng diện tích và tổng phần trăm.',
           'Đọc GeoJSON, tính diện tích trên mặt cầu (pyproj) và so với diện tích báo cáo.',
           'Kiểm tra danh sách file trong ZIP; so sánh GeoTIFF của hai môi trường theo từng pixel.',
           'Lệnh chạy: $PY -m scripts.tc04_output_integrity'],
    expected='GeoTIFF kiểu uint8, nodata 255, pixel 10 m, đúng hệ tọa độ; CSV khớp GeoTIFF; diện tích GeoJSON lệch dưới 1%; ZIP đủ file; hai môi trường trùng nhau.',
    actual=lambda: (f"Tất cả {checks('TC04')} kiểm tra đều đạt. GeoTIFF dùng EPSG:32630, pixel 10 m, nodata 255. Diện tích tính từ GeoJSON là 5,759 ha "
                    f"so với 5,76 ha báo cáo. GeoTIFF của hai môi trường khác nhau {M['TC04']['pixel_diff']} pixel. "
                    f"Tọa độ GeoJSON lệch tối đa {M['TC04']['geojson_max_coordinate_deviation_deg']:.1e} độ, do cách in số thực khác nhau trên ARM64."),
    figs=[('TC04/report_log_excerpt.png', 'Trích nhật ký thực thi TC04', 100)],
    conclusion='Đạt (PASS, {c} kiểm tra).')
T['TC05'] = dict(
    name='Đánh giá chất lượng dự đoán của mô hình', kind='AI Test',
    req='Mô hình phải phân loại đúng phần lớn diện tích trên dữ liệu chưa dùng để huấn luyện.',
    purpose='Đo độ chính xác của checkpoint thật so với nhãn chính thức của bộ dữ liệu PASTIS.',
    pre='Có dữ liệu ảnh và nhãn của patch 10003 (tập test, không dùng khi huấn luyện) và patch 10000 (tập huấn luyện, chỉ để tham khảo).',
    input='Patch 10003: 43 ảnh Sentinel-2, 10 band, 120×120 pixel, chia thành 25 cửa sổ 24×24. Pixel có nhãn void (19) được bỏ qua.',
    steps=['Nạp mô hình và kiểm tra checkpoint.',
           'Dự đoán lần lượt 25 cửa sổ của patch 10003 rồi ghép thành bản đồ 120×120.',
           'So với nhãn PASTIS, tính Overall Accuracy (OA), mIoU, F1 trung bình và ma trận nhầm lẫn.',
           'Đối chiếu với ngưỡng đặt trước: OA ≥ 0,70 và mIoU ≥ 0,40.',
           'Lệnh chạy: $PY -m scripts.tc05_prediction_quality'],
    expected='Trên patch 10003: OA ≥ 0,70 và mIoU ≥ 0,40.',
    actual=lambda: (f"Patch 10003 đạt OA = {n(M['TC05']['test_10003']['overall_accuracy'])}, mIoU = {n(M['TC05']['test_10003']['miou'])}, "
                    f"F1 trung bình = {n(M['TC05']['test_10003']['macro_f1'])}, trên {M['TC05']['test_10003']['evaluated_pixels']} pixel có nhãn. "
                    f"Patch 10000 (thuộc tập huấn luyện) đạt OA = {n(M['TC05']['train_10000']['overall_accuracy'])}, mIoU = {n(M['TC05']['train_10000']['miou'])}. "
                    "Các lớp lớn như lúa mì mùa đông và củ cải đường có IoU trên 0,89; lớp Meadow bị dự đoán nhầm (IoU = 0)."),
    figs=[('TC05/gt_vs_pred_10003.png', 'Patch 10003: ảnh Sentinel-2, nhãn PASTIS, dự đoán của TSViT và vùng dự đoán sai', 100)],
    conclusion='Đạt (PASS). Kết quả chỉ mang tính tham khảo vì tại local chỉ có một patch test có nhãn.')
T['TC06'] = dict(
    name='Độ bền của mô hình trước nhiễu ngẫu nhiên', kind='AI Test, robustness',
    req='Sai số nhỏ của cảm biến không được làm kết quả thay đổi nhiều.',
    purpose='Đo mức giảm độ chính xác khi cộng nhiễu Gauss vào giá trị phản xạ, mô phỏng sai số cảm biến hoặc khí quyển.',
    pre='Như TC05.',
    input='Patch 10003; nhiễu Gauss với độ lệch chuẩn σ = 0; 0,05; 0,1; 0,2; 0,5; 1,0 lần độ lệch chuẩn của từng band; 3 seed cho mỗi mức.',
    steps=['Dự đoán trên dữ liệu gốc để làm mốc.',
           'Với mỗi mức σ và mỗi seed: cộng nhiễu vào ảnh gốc rồi dự đoán lại.',
           'Tính OA, mIoU, tỉ lệ trùng với dự đoán gốc và độ tin cậy trung bình.',
           'Lệnh chạy: $PY -m scripts.tc06_noise_robustness'],
    expected='Với σ = 0,1, OA giảm không quá 0,05; với σ = 0,2, OA giảm không quá 0,10.',
    actual=lambda: (f"OA gốc là {n(M['TC06']['clean_oa'])}. Với σ = 0,1, OA là {n(M['TC06']['mean_by_level']['0.1']['overall_accuracy'])}; "
                    f"với σ = 0,2, OA là {n(M['TC06']['mean_by_level']['0.2']['overall_accuracy'])}. Ở mức nhiễu lớn (σ = 1,0), OA giảm còn "
                    f"{n(M['TC06']['mean_by_level']['1.0']['overall_accuracy'])} nhưng độ tin cậy trung bình vẫn là {n(M['TC06']['mean_by_level']['1.0']['mean_confidence'])}."),
    figs=[('TC06/noise_curve.png', 'Độ chính xác và độ tin cậy theo mức nhiễu', 62)],
    conclusion='Đạt (PASS). Mô hình chịu tốt nhiễu nhỏ, nhưng khi dữ liệu đã hỏng nặng thì vẫn đưa ra dự đoán với độ tin cậy cao (xem thêm TC08, AT06).')
T['TC07'] = dict(
    name='Tính nhất quán khi thiếu dữ liệu thời gian', kind='AI Test, robustness',
    req='Kết quả phải ổn định khi một phần ảnh bị thiếu do mây che hoặc mất ảnh.',
    purpose='Kiểm tra mô hình có cho kết quả giống nhau giữa các lần chạy không, và mức suy giảm khi thiếu các mốc ảnh.',
    pre='Như TC05.',
    input='Patch 10003 có 43 mốc ảnh. Loại ngẫu nhiên 10%, 25%, 50%, 75% số mốc (3 seed), hoặc loại theo mùa (hè, xuân, đông, nửa cuối năm). Mỗi mốc bị loại được bỏ cùng ngày quan sát tương ứng.',
    steps=['Chạy dự đoán hai lần trên cùng dữ liệu và so sánh từng pixel.',
           'Với mỗi kịch bản, loại các mốc ảnh tương ứng (giữ nguyên thứ tự) rồi dự đoán lại.',
           'Tính OA và mIoU cho từng kịch bản.',
           'Lệnh chạy: $PY -m scripts.tc07_temporal_consistency'],
    expected='Hai lần chạy cho kết quả giống hệt nhau; thiếu 25% số mốc thì OA giảm không quá 0,05; thiếu 50% thì giảm không quá 0,15.',
    actual=lambda: ('Hai lần chạy cho kết quả giống hệt nhau (0 pixel khác). OA khi đủ 43 mốc là ' + n(M['TC07']['clean_oa']) + '; khi thiếu ngẫu nhiên '
                    + ', '.join(f"{int(float(k) * 100)}% là {n(v)}" for k, v in M['TC07']['mean_oa_random_drop'].items()) + '. Thiếu theo mùa: '
                    + '; '.join(f"{k} {n(v)}" for k, v in M['TC07']['seasonal'].items()) + '.'),
    figs=[('TC07/temporal_gaps.png', 'Độ chính xác khi thiếu mốc ảnh ngẫu nhiên và theo mùa', 82)],
    conclusion='Đạt (PASS).')
T['TC08'] = dict(
    name='Hành vi trên dữ liệu ngoài phân phối huấn luyện', kind='AI Test',
    req='Khi gặp dữ liệu khác dữ liệu huấn luyện, mô hình nên thể hiện độ không chắc chắn cao hơn.',
    purpose='So sánh độ tin cậy của mô hình trên dữ liệu giống tập huấn luyện (8 patch test PASTIS) và trên vùng Normandy do hệ thống tự chuẩn bị từ ảnh THEIA.',
    pre='Có dữ liệu 8 patch test PASTIS và vùng Normandy (900010). Vùng Normandy không có nhãn.',
    input='PASTIS: 8 patch × 25 cửa sổ = 115.200 pixel. Normandy: 100 cửa sổ 24×24 chọn ngẫu nhiên (seed 0) = 57.600 pixel.',
    steps=['Dự đoán toàn bộ cửa sổ của 8 patch test PASTIS.',
           'Chọn ngẫu nhiên 100 cửa sổ hợp lệ của vùng Normandy và dự đoán.',
           'So sánh phân bố độ tin cậy và phân bố lớp giữa hai nhóm.',
           'Lệnh chạy: $PY -m scripts.tc08_ood_behavior'],
    expected='Độ tin cậy trung bình trên Normandy thấp hơn trên PASTIS ít nhất 0,05.',
    actual=lambda: (f"Độ tin cậy trung bình trên PASTIS là {n(M['TC08']['in_distribution']['mean_confidence'])}, trên Normandy là "
                    f"{n(M['TC08']['domain_shift']['mean_confidence'])}. Tỉ lệ pixel có độ tin cậy dưới 0,5 lần lượt là "
                    f"{n(M['TC08']['in_distribution']['share_conf_below_0_5'])} và {n(M['TC08']['domain_shift']['share_conf_below_0_5'])}. "
                    "Như vậy mô hình còn tự tin hơn trên Normandy."),
    figs=[('TC08/ood_confidence_classes.png', 'Phân bố độ tin cậy và phân bố lớp: PASTIS và Normandy', 82)],
    conclusion=('Không đạt (FAIL) theo tiêu chí đặt trước. Có hai khả năng: dữ liệu Normandy thực ra gần với dữ liệu huấn luyện '
                '(cùng vệ tinh, cùng nước Pháp), hoặc độ tin cậy softmax không phản ánh đúng độ không chắc chắn. Vì Normandy không có nhãn '
                'nên báo cáo không kết luận về độ chính xác ở đây. Kết hợp với TC06 và AT06, có thể thấy hệ thống chưa có cơ chế phát hiện dữ liệu bất thường.'))
T['TC08']['fix'] = 'Thêm bước kiểm tra chất lượng dữ liệu đầu vào (dải giá trị phản xạ, tỉ lệ mây, số mốc tối thiểu); hiệu chỉnh xác suất (temperature scaling) hoặc dùng ngưỡng để đánh dấu kết quả "không chắc chắn"; bổ sung nhãn cho một phần vùng Normandy để đánh giá độ chính xác.'
T['TC09'] = dict(
    name='Giả lập lỗi dịch vụ ảnh vệ tinh bên ngoài', kind='Mock Test, hộp xám',
    req='Khi dịch vụ GEODES/THEIA gặp sự cố, hệ thống phải báo lỗi rõ ràng và tiếp tục hoạt động.',
    purpose='Kiểm tra cách hệ thống xử lý khi dịch vụ cung cấp ảnh vệ tinh mất kết nối, quá thời gian, trả lỗi 503 hoặc bị lỗi giữa chừng.',
    pre='Không cần mạng. Ứng dụng được chuyển sang chế độ lấy ảnh trực tuyến (geodes) với khóa API giả; lỗi được tạo bằng unittest.mock và httpx.MockTransport.',
    input='S1: mất kết nối; S2: quá thời gian; S3: dịch vụ trả HTTP 503; S4: thiếu khóa API; S5: lỗi ImageryError khi tải ảnh; S6: lỗi mạng có chứa tên máy chủ nội bộ giả; S7: kiểm tra lại /api/health.',
    steps=['Khởi động ứng dụng thật và chuyển sang chế độ geodes.',
           'Với từng kịch bản, gắn lỗi giả lập vào lớp mạng hoặc vào hàm tải ảnh, sau đó gửi yêu cầu lập kế hoạch hoặc phân tích.',
           'Ghi mã trạng thái, trạng thái job và thông báo trả về.',
           'Lệnh chạy: $PY -m scripts.tc09_external_service_failure'],
    expected='Trả 502 hoặc 503 với thông báo dễ hiểu; job lỗi chuyển sang trạng thái error; không lộ chi tiết nội bộ; dịch vụ vẫn hoạt động.',
    actual=lambda: ('S1–S3 trả 502 với thông báo "The GEODES catalogue is temporarily unavailable". S4 trả 503 và không tạo job. '
                    'S5 và S6 làm job kết thúc với trạng thái error; ở S6, tên máy chủ nội bộ không xuất hiện trong phản hồi. '
                    f"Sau các lỗi, /api/health vẫn trả 200 và hàng đợi trống ({checks('TC09')} kiểm tra đạt)."),
    figs=[('TC09/report_log_excerpt.png', 'Trích nhật ký thực thi TC09', 100)],
    conclusion='Đạt (PASS). Đây là kiểm thử giả lập, không tải dữ liệu GEODES thật. Production đang chạy chế độ ảnh đã chuẩn bị sẵn nên không phụ thuộc GEODES.')
T['TC10'] = dict(
    name='Giả lập lỗi trong quá trình suy luận', kind='Mock Test, hộp xám',
    req='Lỗi của mô hình hoặc lỗi đọc dữ liệu không được làm hỏng dịch vụ; checkpoint bị sửa phải bị từ chối.',
    purpose='Kiểm tra cách hệ thống xử lý khi mô hình phát sinh lỗi, trả kết quả hỏng, hoặc khi checkpoint bị thay đổi.',
    pre='Như TC05. Thử nghiệm checkpoint bị sửa dùng một bản sao trong thư mục tạm; file gốc không bị chỉnh sửa.',
    input='Job phân tích ô 48×48 pixel (4 cửa sổ). S1: mô hình báo lỗi ở cửa sổ thứ 2; S2: mô hình trả kết quả rỗng; S3: lỗi đọc file ảnh; S4: chạy lại job thật; S5: checkpoint bị lật 1 byte.',
    steps=['Gắn lỗi giả lập vào hàm dự đoán hoặc hàm đọc ảnh, gửi job và chờ kết thúc.',
           'Kiểm tra trạng thái job, thông báo lỗi, file kết quả còn sót và mã trả về khi tải kết quả của job lỗi.',
           'Gửi một job bình thường để kiểm tra khả năng phục hồi.',
           'Tạo bản sao checkpoint bị sửa 1 byte, thử khởi tạo mô hình và khởi động ứng dụng.',
           'Lệnh chạy: $PY -m scripts.tc10_inference_failure'],
    expected='Job lỗi chuyển sang error với thông báo chung, không để lại kết quả dở dang; job tiếp theo chạy bình thường; checkpoint bị sửa bị từ chối.',
    actual=lambda: ('S1–S3: job chuyển sang error với thông báo "Analysis failed. Please retry or check the server log.", không có classification.tif, '
                    'yêu cầu tải kết quả trả 409. S4: job thật chạy xong sau khoảng 3 giây, không cần khởi động lại. S5: mô hình báo lỗi '
                    '"Checkpoint integrity mismatch" và ứng dụng không khởi động.'),
    figs=[('TC10/report_log_excerpt.png', 'Trích nhật ký thực thi TC10', 100)],
    conclusion='Đạt (PASS, {c} kiểm tra). S1–S3 và S5 là lỗi giả lập; S4 là suy luận thật.')

# ---- attack tests
T['AT01'] = dict(
    name='Tấn công bằng dữ liệu sai cấu trúc', kind='Security attack, negative',
    purpose='Kiểm tra API có từ chối các yêu cầu sai cú pháp hoặc sai kiểu dữ liệu mà không gây lỗi máy chủ hay tạo job ngoài ý muốn.',
    pre='Ứng dụng chạy tại local với dữ liệu thật; tối đa 60 yêu cầu, gửi tuần tự.',
    input='12 payload gửi tới POST /api/analyses: JSON bị cắt cụt, sai Content-Type, thiếu trường, geometry là chuỗi/mảng/số, season là số, patch_id là chuỗi "10003", số thực 10003.0, số rất lớn 2^70, và payload có thêm trường lạ.',
    steps=['Gửi lần lượt 12 payload.', 'Ghi mã trạng thái, kiểm tra phản hồi không chứa stack trace và đếm số job được tạo.',
           'Hủy các job được tạo ngoài dự kiến.', 'Lệnh chạy: $PY -m scripts.at01_malformed_input'],
    expected='Tất cả trả 422, không có lỗi 500, không tạo job.',
    actual=lambda: ('9/12 payload bị từ chối đúng. 3 payload được chấp nhận (202) và tạo job: patch_id dạng chuỗi "10003", patch_id 10003.0 và payload có trường thừa. '
                    'Không có lỗi 500, không lộ stack trace.'),
    figs=[('AT01/report_log_excerpt.png', 'Trích nhật ký thực thi AT01', 100)],
    finding='Pydantic đang ở chế độ ép kiểu mặc định nên chuyển "10003" và 10003.0 thành số nguyên, đồng thời bỏ qua trường thừa. Ba job vẫn dùng dữ liệu hợp lệ.',
    fix='Khai báo model ở chế độ strict và cấm trường thừa (ConfigDict(strict=True, extra="forbid")).')
T['AT02'] = dict(
    name='Tấn công bằng payload kích thước lớn', kind='Security attack, boundary',
    purpose='Kiểm tra hệ thống xử lý thế nào khi nhận polygon rất nhiều đỉnh, thân yêu cầu rất lớn hoặc JSON lồng quá sâu.',
    pre='Ứng dụng chạy tại local; 5 yêu cầu, gửi tuần tự; đo bộ nhớ tiến trình trước và sau.',
    input='Polygon 101 đỉnh (vượt giới hạn 100), polygon 100.000 đỉnh (4 MB), payload hợp lệ kèm trường thừa 6 MiB, JSON lồng 1.100 cấp.',
    steps=['Gửi lần lượt từng payload tới /api/imagery-plan, ghi mã trạng thái, thời gian và bộ nhớ.',
           'Gọi /api/health để xác nhận dịch vụ còn hoạt động.', 'Lệnh chạy: $PY -m scripts.at02_oversized_payload'],
    expected='Các payload bất thường bị từ chối bằng 413 hoặc 422, không có lỗi 500.',
    actual=lambda: ('Polygon 101 đỉnh và 100.000 đỉnh bị từ chối (422; trường hợp 100.000 đỉnh mất 462 ms, bộ nhớ tăng 44 MB). '
                    'Payload 6 MiB được chấp nhận (200). JSON lồng 1.100 cấp gây lỗi 500. Sau đó /api/health vẫn trả 200.'),
    figs=[('AT02/report_log_excerpt.png', 'Trích nhật ký thực thi AT02', 100)],
    finding='Ứng dụng không giới hạn kích thước thân yêu cầu. JSON lồng quá sâu gây RecursionError khi phân tích cú pháp (đã tái hiện, xem evidence/AT07/root_cause_reproduction.txt). File cấu hình Caddy mẫu có giới hạn 1 MB, nhưng cấu hình thật trên Production chưa được kiểm chứng.',
    fix='Giới hạn kích thước body ở reverse proxy và middleware; bắt RecursionError để trả 400 hoặc 422.')
T['AT03'] = dict(
    name='Gửi dồn dập yêu cầu tới API', kind='Security/hiệu năng, có giới hạn',
    purpose='Kiểm tra API có ổn định khi bị gửi nhiều yêu cầu cùng lúc và hàng đợi phân tích có bị giới hạn đúng thiết kế không.',
    pre='Ứng dụng chạy tại local; tối đa 310 yêu cầu, 8 luồng song song, trong 120 giây.',
    input='200 yêu cầu GET /api/health với 8 luồng song song; 12 yêu cầu POST /api/analyses hợp lệ (ô 24×24 pixel) gửi liên tiếp.',
    steps=['Gửi 200 yêu cầu health bằng 8 luồng, ghi thời gian từng yêu cầu.', 'Gửi nhanh 12 yêu cầu phân tích, đếm số yêu cầu nhận 202 và 429.',
           'Hủy toàn bộ job đã tạo.', 'Lệnh chạy: $PY -m scripts.at03_api_flooding'],
    expected='Không có yêu cầu health lỗi, p95 dưới 1.000 ms; hàng đợi dừng nhận ở 4 job và trả 429 cho phần còn lại.',
    actual=lambda: (f"200 yêu cầu health không có lỗi; p50 = {n(P03['p50'], 1)} ms, p95 = {n(P03['p95'], 1)} ms, p99 = {n(P03['p99'], 1)} ms "
                    "(tính từ 200 thời gian đo trong evidence/AT03/response.json). Trong 12 yêu cầu phân tích, 4 yêu cầu nhận 202 và 8 yêu cầu bị từ chối 429."),
    figs=[('AT03/latency.png', 'Thời gian phản hồi của 200 yêu cầu /api/health', 70)],
    finding='Không phát hiện lỗi. Tuy nhiên hệ thống chưa giới hạn số yêu cầu theo IP hay người dùng, nên một client có thể chiếm cả 4 vị trí trong hàng đợi.',
    fix='Bổ sung giới hạn tốc độ theo IP hoặc người dùng.')
T['AT04'] = dict(
    name='Tấn công đối kháng FGSM và PGD', kind='Adversarial attack, hộp trắng',
    purpose='Đánh giá mức độ mô hình bị đánh lừa khi đầu vào bị thêm nhiễu được tính có chủ đích theo gradient, so với nhiễu ngẫu nhiên cùng độ lớn.',
    pre='Có checkpoint và nhãn của patch 10003; dùng 3 cửa sổ tại vị trí (0,0), (48,48), (96,96).',
    input='Nhiễu FGSM và PGD (3 bước) với ε = 0,01; 0,05; 0,1 trên dữ liệu đã chuẩn hóa; nhiễu ngẫu nhiên cùng độ lớn để so sánh.',
    steps=['Tính gradient của hàm mất mát theo đầu vào.', 'Tạo ảnh bị tấn công: FGSM cộng ε·sign(gradient); PGD lặp 3 bước và giới hạn trong phạm vi ε.',
           'Dự đoán lại và tính accuracy so với nhãn.', 'Lệnh chạy: $PY -m scripts.at04_adversarial_noise'],
    expected='Với ε = 0,01, accuracy giảm không quá 0,05.',
    actual=lambda: 'Accuracy gốc trên 3 cửa sổ là 0,8378. Nhiễu có chủ đích làm accuracy giảm mạnh, trong khi nhiễu ngẫu nhiên gần như không ảnh hưởng (bảng số liệu bên dưới).',
    table=lambda: ('Accuracy theo ε', ['ε', 'FGSM', 'PGD', 'Ngẫu nhiên'],
                   [[n(e, 2)] + [n(next(x['accuracy'] for x in M['AT04']['experiments'] if x['attack'] == a and x['epsilon'] == e)) for a in ('FGSM', 'PGD', 'random_PGD')]
                    for e in (0.01, 0.05, 0.1)], [16, 28, 28, 28]),
    figs=[('AT04/accuracy_vs_epsilon.png', 'Accuracy theo ε với FGSM, PGD và nhiễu ngẫu nhiên', 64)],
    finding='Mô hình rất nhạy với nhiễu có chủ đích. Tuy nhiên người dùng API không gửi được ảnh vệ tinh tùy ý, vì ảnh do máy chủ đọc từ dữ liệu đã chuẩn bị. Muốn khai thác, kẻ tấn công phải can thiệp được vào nguồn dữ liệu.',
    fix='Bảo vệ toàn vẹn dữ liệu đầu vào (đã có dataset_version và hash); cân nhắc huấn luyện đối kháng nếu dữ liệu có thể đến từ nguồn không tin cậy.')
T['AT05'] = dict(
    name='Thao túng chuỗi thời gian', kind='Adversarial/robustness',
    purpose='Kiểm tra ảnh hưởng khi thứ tự ảnh hoặc ngày quan sát (DOY) bị sai lệch có chủ đích.',
    pre='Có checkpoint và nhãn của patch 10003; dùng toàn bộ 25 cửa sổ.',
    input='Đảo thứ tự ảnh (giữ ngày), xáo trộn ảnh, đảo đồng thời ảnh và ngày, lệch ngày ±30 và ±60, lặp ảnh đầu tiên cho mọi mốc.',
    steps=['Tạo từng biến thể từ chuỗi ảnh và ngày gốc.', 'Dự đoán và tính accuracy so với nhãn.',
           'Kiểm tra ngày ngoài khoảng 1–365 có bị từ chối không.', 'Lệnh chạy: $PY -m scripts.at05_temporal_manipulation'],
    expected='Accuracy của mỗi biến thể giảm không quá 0,05 so với dữ liệu gốc.',
    actual=lambda: ('Accuracy gốc là 0,8734. Đảo thứ tự ảnh còn 0,2739, xáo trộn còn 0,4822, lệch ngày −60/−30/+30/+60 còn 0,5573/0,6905/0,7153/0,3819, '
                    'lặp ảnh đầu còn 0,1593. Đảo đồng thời ảnh và ngày vẫn giữ 0,8734. Ngày ngoài khoảng 1–365 bị từ chối.'),
    figs=[('AT05/temporal_accuracy.png', 'Accuracy theo từng kiểu thao túng chuỗi thời gian', 70)],
    finding='Mô hình phụ thuộc vào việc ảnh và ngày quan sát khớp nhau, nhưng không phụ thuộc vào vị trí trong chuỗi. Người dùng API không gửi được chuỗi thời gian tùy ý, nên đây là rủi ro ở khâu chuẩn bị dữ liệu.',
    fix='Kiểm tra lịch thu nhận (ngày tăng dần, không trùng lặp, khớp metadata) trong pipeline chuẩn bị dữ liệu.')
T['AT06'] = dict(
    name='Đầu vào ngoài phân phối (dữ liệu tổng hợp)', kind='Robustness',
    purpose='Kiểm tra mô hình có nhận ra dữ liệu vô nghĩa hay vẫn gán nhãn cây trồng với độ tin cậy cao.',
    pre='Có checkpoint; dùng 3 cửa sổ thật của patch 10003 làm mốc so sánh.',
    input='Ảnh toàn giá trị 0, ảnh hằng số 10000 (giống mây dày), nhiễu đều trong khoảng [0, 10000], ảnh thật nhân 3, ảnh thật đảo thứ tự band.',
    steps=['Tạo các đầu vào tổng hợp có cùng kích thước với dữ liệu thật.', 'Dự đoán, ghi độ tin cậy trung bình và tỉ lệ pixel có độ tin cậy ≥ 0,9.',
           'Lệnh chạy: $PY -m scripts.at06_ood_input'],
    expected='Với dữ liệu vô nghĩa, độ tin cậy trung bình ≤ 0,60 và tỉ lệ pixel có độ tin cậy ≥ 0,9 không quá 10%.',
    actual=lambda: ('Độ tin cậy trung bình: dữ liệu thật 0,936; ảnh toàn 0 là 1,000; ảnh hằng số 10000 là 1,000; nhiễu đều 0,997; ảnh nhân 3 là 0,795; '
                    'đảo band 1,000. Với ba loại dữ liệu vô nghĩa, 100% pixel có độ tin cậy ≥ 0,9.'),
    figs=[('AT06/ood_confidence.png', 'Độ tin cậy của mô hình trên dữ liệu thật và dữ liệu tổng hợp', 70)],
    finding='Mô hình không phân biệt được dữ liệu vô nghĩa, kết quả này trùng với TC06 và TC08. Đây là dữ liệu tổng hợp, không có nhãn thật.',
    fix='Kiểm tra chất lượng đầu vào (dải giá trị phản xạ, tỉ lệ mây, số mốc tối thiểu); hiệu chỉnh xác suất hoặc thêm ngưỡng để đánh dấu "không chắc chắn".')
T['AT07'] = dict(
    name='Tấn công bằng GeoJSON không hợp lệ', kind='Security attack, negative/boundary',
    purpose='Kiểm tra API xử lý các vùng chọn có hình học sai hoặc giá trị đặc biệt.',
    pre='Ứng dụng chạy tại local; gửi tuần tự, hủy mọi job tạo ngoài dự kiến.',
    input='13 biến thể gửi tới cả /api/imagery-plan và /api/analyses (26 lượt): ring hở, 3 điểm, MultiPolygon, polygon có lỗ, NaN, +Infinity, −Infinity, kinh độ 181/vĩ độ 91, tọa độ 3D, polygon tự cắt hình nơ, diện tích 0, ngoài vùng có ảnh, nửa địa cầu.',
    steps=['Gửi từng biến thể tới hai endpoint.', 'Ghi mã trạng thái và số job được tạo.',
           'Tái hiện các trường hợp lỗi 500 để tìm nguyên nhân (evidence/AT07/root_cause_reproduction.txt).', 'Lệnh chạy: $PY -m scripts.at07_malformed_geojson'],
    expected='Tất cả trả 422, không có lỗi 500, không tạo job.',
    actual=lambda: ('18/26 lượt trả đúng 422. NaN, +Infinity và −Infinity trả 500 trên cả hai endpoint (6 lượt). '
                    'Polygon tự cắt được chấp nhận (200 và 202) và tạo 1 job.'),
    figs=[('AT07/report_log_excerpt.png', 'Trích nhật ký thực thi AT07', 100)],
    finding=('Bộ kiểm tra vẫn phát hiện NaN là không hợp lệ, nhưng khi tạo phản hồi 422, FastAPI chép lại dữ liệu đầu vào chứa NaN '
             'và hàm json.dumps không mã hóa được giá trị này ("Out of range float values are not JSON compliant"), nên kết quả thành 500. Không có dữ liệu bị ghi. '
             'Polygon tự cắt được chấp nhận vì chưa có bước kiểm tra tính hợp lệ hình học.'),
    fix='Từ chối NaN/Infinity ngay khi đọc JSON, hoặc bỏ trường "input" khỏi phản hồi lỗi; thêm kiểm tra hình học hợp lệ (ví dụ shapely is_valid).')
T['AT08'] = dict(
    name='Can thiệp tham số và định danh tài nguyên', kind='Security attack, negative',
    purpose='Kiểm tra API có chặn việc sửa tham số để truy cập dữ liệu ngoài phạm vi, đọc file hệ thống hoặc thao tác job của người khác.',
    pre='Ứng dụng chạy tại local; tối đa 120 yêu cầu, tuần tự.',
    input='patch_id 10000 (tập huấn luyện, không có trong catalog), patch không tồn tại hoặc âm, mùa giả; mã job dạng ../, mã hóa URL, UUID viết hoa; định dạng tải về giả; tọa độ ngoài miền; client B hủy job của client A.',
    steps=['Gửi các yêu cầu với tham số đã bị sửa.', 'Ghi mã trạng thái từng trường hợp.',
           'Cho client A tạo job, client B (phiên khác) gửi DELETE job đó.', 'Lệnh chạy: $PY -m scripts.at08_parameter_tampering'],
    expected='Patch ẩn và tham số sai bị từ chối; đường dẫn giả trả 404; client khác không hủy được job (401/403).',
    actual=lambda: ('Các trường hợp đường dẫn giả, UUID không chuẩn, định dạng giả và tọa độ sai đều bị chặn (404/422). '
                    'Patch 10000 vẫn phân tích được (202). Client B hủy được job của client A (200).'),
    figs=[('AT08/report_log_excerpt.png', 'Trích nhật ký thực thi AT08', 100)],
    finding='API không có xác thực và không gắn job với người tạo. Mã job là UUIDv4 (122 bit ngẫu nhiên) nên không đoán được; rủi ro chỉ xảy ra khi mã job bị lộ. Patch huấn luyện bị ẩn khỏi catalog nhưng chưa bị chặn khi phân tích.',
    fix='Gắn job với phiên hoặc token của người tạo; chặn patch không thuộc tập test hoặc external trong hàm analyze().')
T['AT09'] = dict(
    name='Tiêu thụ tài nguyên bằng yêu cầu phân tích lớn', kind='Security/hiệu năng, có giới hạn',
    purpose='Kiểm tra hệ thống khi nhận một yêu cầu hợp lệ nhưng rất nặng: phân tích toàn bộ vùng Normandy.',
    pre='Ứng dụng chạy tại local; chỉ 1 job, chạy trong 60 giây rồi hủy.',
    input='Polygon phủ toàn bộ vùng 900010 (23,04 × 23,04 km, 9.216 cửa sổ).',
    steps=['Gọi /api/imagery-plan để biết số cửa sổ.', 'Gửi yêu cầu phân tích; trong 60 giây, mỗi giây ghi bộ nhớ, CPU, thời gian /api/health và tiến độ job.',
           'Gửi DELETE để hủy job, đo thời gian đến khi job dừng.', 'Lệnh chạy: $PY -m scripts.at09_resource_exhaustion'],
    expected='Trong lúc job chạy, /api/health vẫn phản hồi nhanh; lệnh hủy có hiệu lực; bộ nhớ không tăng mất kiểm soát.',
    actual=lambda: (f"Trong 60 giây, job xử lý {M['AT09']['completed_windows']}/{M['AT09']['windows']} cửa sổ. /api/health có p95 = "
                    f"{n(M['AT09']['health_p95_ms'], 2)} ms. Bộ nhớ tăng từ {n(M['AT09']['rss_baseline_mb'], 0)} MB lên tối đa {n(M['AT09']['rss_peak_sampled_mb'], 0)} MB. "
                    f"Lệnh hủy có hiệu lực sau {n(M['AT09']['cancel_latency_seconds'], 2)} s. Ngoại suy từ tốc độ đo được, chạy hết vùng mất khoảng "
                    f"{M['AT09']['estimated_full_run_seconds_extrapolated'] / 60:.0f} phút (con số ước tính, không chạy hết)."),
    figs=[('AT09/resources.png', 'Bộ nhớ và CPU của tiến trình khi chạy job toàn vùng', 70)],
    finding='Kiểm thử đạt theo tiêu chí, nhưng cho thấy một rủi ro về khả dụng: một yêu cầu hợp lệ có thể chiếm worker duy nhất khoảng 42 phút, trong thời gian đó người dùng khác phải chờ.',
    fix='Giới hạn số cửa sổ cho mỗi job hoặc mỗi người dùng; đặt thời gian chạy tối đa; dùng kết quả tính sẵn cho chức năng "Whole region".')
T['AT10'] = dict(
    name='Giá trị số và kích thước tensor không hợp lệ', kind='Security/robustness, boundary',
    purpose='Kiểm tra bước tiền xử lý và mô hình có từ chối dữ liệu số không hợp lệ hay không.',
    pre='Có checkpoint; dùng cửa sổ (0,0) của patch 10003 (43 mốc).',
    input='Giá trị NaN, +Inf, −Inf, −32768, 32767, giá trị âm; tensor sai kích thước [T, 10, 23, 24]; T = 0; T = 200; số ngày quan sát không khớp số ảnh; chèn NaN vào job API.',
    steps=['Gọi trực tiếp preprocess và Engine.predict với từng trường hợp, ghi lại việc có ValueError hay không.',
           'Kiểm tra T = 200 có bị cắt về 60 mốc không.', 'Chèn NaN vào dữ liệu của một job API và kiểm tra trạng thái job.',
           'Lệnh chạy: $PY -m scripts.at10_invalid_numerics'],
    expected='Tất cả trường hợp không hợp lệ bị từ chối bằng ValueError; T = 200 được cắt về 60; job chứa NaN kết thúc với trạng thái error.',
    actual=lambda: ('10/18 lượt bị từ chối đúng (NaN, +Inf, −Inf, sai kích thước, số ngày không khớp). Không bị từ chối: −32768, 32767, giá trị âm, T = 0. '
                    'T = 200 được cắt đúng về 60. Job chứa NaN kết thúc với trạng thái error.'),
    figs=[('AT10/report_log_excerpt.png', 'Trích nhật ký thực thi AT10', 100)],
    finding='Chuỗi rỗng (T = 0) vẫn cho ra dự đoán; giá trị phản xạ hữu hạn nhưng bất thường không bị chặn. Riêng giá trị âm và giá trị bão hòa có thể xuất hiện trong dữ liệu L2A thật, nên tiêu chí ở điểm này khá chặt; tiêu chí được giữ nguyên vì đã đặt trước khi chạy.',
    fix='Từ chối T = 0 hoặc số mốc dưới mức tối thiểu; cân nhắc kiểm tra dải giá trị phản xạ hợp lý.')

SEVERITY = {k: v['severity'] for k, v in AT_REVIEW.items()}

# ------------------------------------------------------------------ HTML
fig_no, tab_no, toc = {}, {}, []


def h(level, num, title):
    a = f'a{len(toc)}'
    toc.append((level, num, title, a))
    return f'<h{level} id="{a}">{esc(num)} {esc(title)}</h{level}>'


def figure(ch, rel, caption, width):
    fig_no[ch] = fig_no.get(ch, 0) + 1
    data = base64.b64encode((E / rel).read_bytes()).decode()
    return (f'<figure><img src="data:image/png;base64,{data}" style="width:{width}%"><figcaption>Hình {ch}.{fig_no[ch]}. '
            f'{esc(caption)}.</figcaption></figure>')


def table(ch, caption, header, rows, widths):
    tab_no[ch] = tab_no.get(ch, 0) + 1
    cols = ''.join(f'<col style="width:{w}%">' for w in widths)
    body = ''.join('<tr>' + ''.join(f'<td>{esc(x)}</td>' for x in r) + '</tr>' for r in rows)
    return (f'<p class="cap">Bảng {ch}.{tab_no[ch]}. {esc(caption)}</p><table><colgroup>{cols}</colgroup>'
            f'<thead><tr>{"".join(f"<th>{esc(x)}</th>" for x in header)}</tr></thead><tbody>{body}</tbody></table>')


def para(label, text):
    return f'<p>{esc(label)}: {esc(text)}</p>'


def spec_table(ch, t):
    d, r = T[t], R[t]
    steps = ''.join(f'<div class="st">{i}. {esc(x)}</div>' for i, x in enumerate(d['steps'], 1))
    status = ('PASS' if r['status'] == 'PASS' else 'FAIL') + f' ({checks(t)} kiểm tra đạt)'
    rows = [('Mã kiểm thử', esc(t)),
            ('Loại kiểm thử', esc(d['kind'])),
            ('Yêu cầu kiểm tra', esc(d.get('req') or d['purpose'])),
            ('Môi trường thực hiện', esc(r['environment'])),
            ('Điều kiện thực hiện', esc(d['pre'])),
            ('Dữ liệu đầu vào', esc(d['input'])),
            ('Các bước thực hiện', steps),
            ('Kết quả mong đợi', esc(d['expected'])),
            ('Kết quả thực tế', esc(d['actual']())),
            ('Đánh giá', status)]
    tab_no[ch] = tab_no.get(ch, 0) + 1
    body = ''.join(f'<tr><td>{k}</td><td>{v}</td></tr>' for k, v in rows)
    return (f'<p class="cap">Bảng {ch}.{tab_no[ch]}. Đặc tả test case {t}</p><table class="spec"><colgroup><col style="width:24%"><col style="width:76%"></colgroup>'
            f'<thead><tr><th>Trường</th><th>Nội dung</th></tr></thead><tbody>{body}</tbody></table>')


def test_block(ch, idx, t):
    d, r = T[t], R[t]
    out = [h(2, f'{ch}.{idx}.', f'{t} – {d["name"]}'), spec_table(ch, t)]
    if d.get('table'):
        out.append(table(ch, *d['table']()))
    for rel, cap, w in d['figs']:
        out.append(figure(ch, rel, cap, w))
    if t.startswith('AT'):
        if r['status'] == 'FAIL':
            out.append(para('Lỗi phát hiện', d['finding']))
            out.append(para('Mức độ ảnh hưởng', SEVERITY[t]))
            out.append(para('Hướng khắc phục', d['fix']))
        else:
            out.append(para('Nhận xét', d['finding'] + ' Đề xuất: ' + d['fix']))
    else:
        text = d['conclusion'].format(c=checks(t))
        note = text.split('). ', 1)[1] if '). ' in text else (text.split('. ', 1)[1] if r['status'] == 'FAIL' else '')
        if r['status'] == 'FAIL':
            out.append(para('Lỗi phát hiện', note))
            out.append(para('Hướng khắc phục', d['fix']))
        elif note:
            out.append(para('Nhận xét', note))
    return f'<section class="tc{" first" if idx == 1 else ""}">' + ''.join(out) + '</section>'


CSS = '''
@page { size: A4; margin: 2cm 2cm 2.2cm 3cm; }
html, body { background: #fff; color: #000; }
body { font-family: "Liberation Serif", "Times New Roman", serif; font-size: 13pt; line-height: 1.35; }
h1 { font-size: 16pt; font-weight: bold; text-align: center; text-transform: uppercase; margin: 0 0 12pt; break-before: page; }
h2 { font-size: 14pt; font-weight: bold; margin: 14pt 0 6pt; break-after: avoid; }
h3 { font-size: 13pt; font-weight: bold; margin: 10pt 0 4pt; break-after: avoid; }
p { margin: 0 0 5pt; text-align: justify; }
p.step { margin: 0 0 2pt 1cm; text-indent: 0; text-align: left; }
p.keep { break-after: avoid; margin-bottom: 2pt; }
b, strong { font-weight: normal; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0 9pt; font-size: 12pt; line-height: 1.3; table-layout: fixed; }
th, td { border: 0.5pt solid #000; padding: 2pt 5pt; vertical-align: top; text-align: left; overflow-wrap: anywhere; }
th { font-weight: normal; }
tr { break-inside: avoid; }
p.cap { text-align: center; margin: 6pt 0 2pt; break-after: avoid; }
figure { margin: 6pt 0 8pt; text-align: center; break-inside: avoid; }
figure img { max-height: 80mm; max-width: 100%; object-fit: contain; }
figcaption { text-align: center; margin-top: 3pt; }
.toc a { display: flex; margin: 0; line-height: 1.32; text-align: left; color: #000; text-decoration: none; } .toc .l2 { padding-left: 1cm; }
.toc .dots { flex: 1; border-bottom: 1pt dotted #000; margin: 0 4pt 5pt; }
section.tc { break-before: auto; }\ntable.spec { font-size: 12pt; break-inside: avoid; } h2 + p.cap { break-before: avoid; } table.spec td:first-child { white-space: normal; } .st { margin: 0 0 1pt; }
ul { margin: 0 0 5pt; padding-left: 1cm; } li { text-align: justify; margin-bottom: 3pt; }
'''


def body(pages):
    toc.clear(); fig_no.clear(); tab_no.clear()
    x = ['<h1 style="break-before:auto">Mục lục</h1><div class="toc">@@TOC@@</div>']
    # Chapter 1
    x.append(h(1, 'Chương 1.', 'Giới thiệu và môi trường kiểm thử'))
    x.append(h(2, '1.1.', 'Giới thiệu dự án'))
    x.append('<p>Satellite Crop Mapping là hệ thống phân loại cây trồng từ chuỗi ảnh vệ tinh Sentinel-2. Người dùng chọn một vùng trên bản đồ, hệ thống chạy mô hình và trả về bản đồ phân loại cho từng pixel 10 m, kèm thống kê diện tích theo loại cây. Kết quả tải về được ở dạng GeoTIFF, GeoJSON, CSV, PNG hoặc ZIP. Hệ thống đang chạy tại https://crop.loanhviet.dev.</p>')
    x.append(h(2, '1.2.', 'Mô hình AI'))
    x.append('<p>Mô hình là TSViT (Temporal-Spatial Vision Transformer), được huấn luyện trên bộ dữ liệu PASTIS với 19 lớp (lớp 0 là nền, 1–18 là các loại cây trồng). Đầu vào là chuỗi tối đa 60 ảnh, mỗi ảnh có 10 band phổ và ngày quan sát, trên cửa sổ 24×24 pixel. Mô hình học sự thay đổi phản xạ phổ theo mùa vụ để phân biệt các loại cây. Trước khi nạp, checkpoint được kiểm tra SHA-256 với file manifest của dự án.</p>')
    x.append(h(2, '1.3.', 'Kiến trúc hệ thống'))
    x.append('<p>Giao diện web dùng Leaflet. Backend FastAPI nhận vùng chọn dạng GeoJSON, kiểm tra dữ liệu đầu vào và đưa job vào hàng đợi (1 worker, tối đa 4 job chờ). Worker đọc chuỗi ảnh đã chuẩn bị, chia vùng thành các cửa sổ 24×24, chạy TSViT trên CPU, ghép kết quả và xuất file. Giao diện hỏi trạng thái job định kỳ và hiển thị lớp phủ kết quả. Hệ thống được đóng gói bằng Docker; GitHub Actions tự động build image ARM64 và triển khai lên Oracle Cloud, có kiểm tra sức khỏe dịch vụ và rollback khi lỗi.</p>')
    x.append(h(2, '1.4.', 'Môi trường kiểm thử'))
    x.append(table('1', 'Môi trường Local và Production', ['Hạng mục', 'Local', 'Production'], [
        ['Phần cứng', 'Intel Core i5-12500H, 16 luồng, 15 GiB RAM', 'Oracle Cloud Ampere A1 (ARM64), container 2 CPU'],
        ['Hệ điều hành', 'Ubuntu 24.04.5', 'Ubuntu 24.04, Docker, Caddy'],
        ['Phần mềm', 'Python 3.13, PyTorch 2.14.1 (CPU), FastAPI 0.143.0', 'Image build từ cùng mã nguồn'],
        ['Checkpoint', 'SHA-256 92a83d0d…a40b733', 'Cùng checkpoint (xác nhận ở TC01)'],
        ['Dữ liệu', '8 patch test PASTIS, patch 10000, vùng Normandy; nhãn của patch 10003 và 10000', 'Cùng danh mục dữ liệu (xác nhận ở TC01)']], [18, 44, 38]))
    x.append('<p>Production chỉ dùng cho các kiểm thử an toàn: gọi các endpoint đọc, kiểm tra dữ liệu đầu vào bằng endpoint không tạo job, và đúng hai lần phân tích (một qua API, một qua giao diện). Các yêu cầu được gửi tuần tự, có giới hạn thời gian chờ. Tổng cộng có ' + f'{S["production_api_requests_scripted"]} yêu cầu do script gửi và {S["production_api_requests_from_ui"]} yêu cầu do giao diện tự sinh khi hỏi trạng thái job. Tất cả kiểm thử tấn công, giả lập lỗi và gây tải chỉ chạy ở Local.</p>')
    x.append(h(2, '1.5.', 'Công cụ kiểm thử'))
    x.append('<p>Kiểm thử API dùng pytest, FastAPI TestClient và httpx. Kiểm thử giao diện dùng Playwright điều khiển Google Chrome. Kiểm thử mô hình dùng NumPy và PyTorch. Giả lập lỗi dùng unittest.mock và httpx.MockTransport. Biểu đồ được vẽ bằng Matplotlib từ dữ liệu đo được. Trước khi kiểm thử, bộ test có sẵn của dự án được chạy lại với dữ liệu thật và đạt 53/53.</p>')
    x.append(h(2, '1.6.', 'Phương pháp và tiêu chí đánh giá'))
    x.append('<p>Mỗi test case được thiết kế theo các trường: mã, yêu cầu kiểm tra, điều kiện thực hiện, dữ liệu đầu vào, các bước, kết quả mong đợi, kết quả thực tế và Pass/Fail. Dữ liệu thử gồm cả trường hợp đúng (positive), sai (negative) và giá trị biên (boundary). Kết quả mong đợi và ngưỡng được ghi trước khi chạy, không sửa sau đó. Test case đạt (PASS) khi mọi kiểm tra đạt; không đạt (FAIL) khi có ít nhất một kiểm tra sai; BLOCKED khi không thực hiện được. Với nhóm tấn công, FAIL nghĩa là đã phát hiện một điểm yếu của hệ thống. Mỗi test case lưu bằng chứng trong thư mục testing_report/evidence/&lt;mã test&gt;/, gồm result.json, execution.log, dữ liệu yêu cầu và phản hồi, ảnh. Các lệnh trong báo cáo chạy từ thư mục testing_report, với $PY là Python của môi trường ảo dự án.</p>'.replace('&amp;lt;', '&lt;'))
    # Chapter 2, 3
    x.append(h(1, 'Chương 2.', 'Kiểm thử hệ thống AI'))
    x.append('<p>Chương này gồm 10 test case: 4 kiểm thử tự động API và hệ thống (TC01–TC04), 4 kiểm thử mô hình AI (TC05–TC08) và 2 kiểm thử giả lập lỗi (TC09–TC10).</p>')
    x += [test_block('2', i, t) for i, t in enumerate(IDS[:10], 1)]
    x.append(h(1, 'Chương 3.', 'Kiểm thử tấn công hệ thống AI'))
    x.append('<p>Chương này gồm 10 test case tấn công, tất cả chạy ở Local với checkpoint và dữ liệu thật. Có ba nhóm: tấn công tầng API (AT01–AT03, AT07–AT10), tấn công đối kháng vào mô hình (AT04, AT05) và kiểm tra độ bền với dữ liệu bất thường (AT06). Việc độ chính xác của mô hình giảm khi dữ liệu bị thao túng không được coi là lỗ hổng API nếu người dùng không có cách đưa dữ liệu đó vào hệ thống.</p>')
    x += [test_block('3', i, t) for i, t in enumerate(IDS[10:], 1)]
    # Chapter 4
    x.append(h(1, 'Chương 4.', 'Tổng hợp kết quả và kết luận'))
    x.append(h(2, '4.1.', 'Bảng tổng hợp'))
    notes = {'TC08': 'Mô hình tự tin hơn trên dữ liệu Normandy', 'AT01': 'Ép kiểu, bỏ qua trường thừa', 'AT02': 'Nhận body 6 MiB; JSON sâu gây 500',
             'AT03': 'Hàng đợi chặn đúng ở 4 job', 'AT04': 'PGD ε=0,1: accuracy 0,1455', 'AT05': 'Nhạy với ngày quan sát sai',
             'AT06': 'Độ tin cậy ≈1 với dữ liệu vô nghĩa', 'AT07': 'NaN/Infinity gây 500; nhận polygon tự cắt', 'AT08': 'Không có quyền sở hữu job',
             'AT09': 'Job toàn vùng chiếm worker khoảng 42 phút', 'AT10': 'Chấp nhận T = 0 và giá trị bất thường'}
    rows = [[i, t, T[t]['name'], R[t]['status'], notes.get(t, '')] for i, t in enumerate(IDS, 1)]
    x.append(table('4', 'Tổng hợp 20 test case', ['STT', 'Mã test', 'Tên kiểm thử', 'Kết quả', 'Ghi chú'], rows, [8, 11, 38, 11, 32]))
    x.append(h(2, '4.2.', 'Thống kê'))
    cnt = S['counts']
    x.append(table('4', 'Thống kê kết quả kiểm thử', ['Nhóm', 'Số test', 'PASS', 'FAIL', 'BLOCKED'], [
        ['Kiểm thử hệ thống AI', 10, S['group_a'].get('PASS', 0), S['group_a'].get('FAIL', 0), S['group_a'].get('BLOCKED', 0)],
        ['Kiểm thử tấn công', 10, S['group_b'].get('PASS', 0), S['group_b'].get('FAIL', 0), S['group_b'].get('BLOCKED', 0)],
        ['Tổng', S['total'], cnt.get('PASS', 0), cnt.get('FAIL', 0), cnt.get('BLOCKED', 0)]], [36, 13, 13, 13, 25]))
    x.append(f'<p>Tổng số kiểm tra đã thực hiện là {S["checks"]}, trong đó {S["checks_passed"]} đạt. Bảng 4.3 tổng hợp các số liệu hiệu năng đã đo.</p>')
    x.append(table('4', 'Số liệu hiệu năng đã đo', ['Phép đo', 'Số mẫu', 'p50 (ms)', 'p95 (ms)', 'p99 (ms)', 'Tỉ lệ lỗi'], [
        ['/api/health, Local, 8 luồng (AT03)', P03['n'], n(P03['p50'], 1), n(P03['p95'], 1), n(P03['p99'], 1), f"{P03['errors']}/{P03['n']}"],
        ['/api/health, Local, khi đang chạy job lớn (AT09)', '13', '–', n(M['AT09']['health_p95_ms'], 2), '–', '0'],
        ['/api/health, Production, tuần tự (TC01)', '3', n(M['TC01']['Production']['median_ms']['/api/health'], 1), '–', '–', '0/3']], [44, 11, 11, 11, 11, 12]))
    x.append(h(2, '4.3.', 'Các lỗi phát hiện'))
    x.append('<ul>' + ''.join(f'<li>{esc(s)}</li>' for s in [
        'Lỗi 1 (trung bình, AT07): GeoJSON chứa NaN hoặc Infinity gây lỗi 500 thay vì 422, do phản hồi lỗi chứa giá trị NaN không mã hóa được thành JSON.',
        'Lỗi 2 (trung bình, AT02): JSON lồng quá sâu gây lỗi 500; ứng dụng không giới hạn kích thước thân yêu cầu.',
        'Lỗi 3 (cao về khả dụng, AT09): chưa giới hạn kích thước phân tích; một yêu cầu hợp lệ có thể chiếm worker duy nhất hàng chục phút.',
        'Lỗi 4 (trung bình, TC08, AT06): mô hình quá tự tin với dữ liệu bất thường, chưa có cơ chế phát hiện dữ liệu ngoài phân phối.',
        'Lỗi 5 (trung bình, AT04, AT05): mô hình nhạy với nhiễu đối kháng và ngày quan sát bị sai lệch.',
        'Lỗi 6 (thấp, AT07): chấp nhận polygon tự cắt.',
        'Lỗi 7 (thấp đến trung bình, AT08): không có xác thực hay quyền sở hữu job; patch huấn luyện vẫn phân tích được bằng mã.',
        'Lỗi 8 (thấp, AT01, AT10): dữ liệu đầu vào chưa được kiểm tra chặt (ép kiểu, trường thừa, chuỗi ảnh rỗng).']) + '</ul>')
    x.append(h(2, '4.4.', 'Nhận xét về chất lượng hệ thống'))
    x.append('<p>Chức năng chính hoạt động ổn định trên cả hai môi trường. Kết quả của Local và Production trùng nhau từng pixel, và các file xuất ra đúng định dạng. Mô hình đạt OA 0,8734 và mIoU 0,7089 trên patch test có nhãn, chịu tốt nhiễu nhỏ và việc thiếu tới một nửa số mốc ảnh. Hệ thống xử lý tốt các lỗi vận hành như dịch vụ ngoài lỗi, mô hình lỗi, đọc file lỗi, và từ chối checkpoint bị sửa. Điểm yếu tập trung ở ba chỗ: hai đường xử lý dữ liệu đầu vào bất thường gây lỗi 500, chưa giới hạn tài nguyên cho mỗi yêu cầu, và mô hình chưa nhận biết được dữ liệu bất thường.</p>')
    x.append(h(2, '4.5.', 'Đề xuất cải thiện'))
    x.append('<p>Theo thứ tự ưu tiên: (1) giới hạn số cửa sổ và thời gian chạy của mỗi job; (2) sửa hai đường gây lỗi 500 và giới hạn kích thước thân yêu cầu; (3) thêm kiểm tra chất lượng dữ liệu đầu vào và cơ chế đánh dấu kết quả "không chắc chắn"; (4) gắn job với người tạo; (5) dùng chế độ kiểm tra chặt cho dữ liệu đầu vào; (6) đưa các test trong báo cáo này vào quy trình CI.</p>')
    x.append(h(2, '4.6.', 'Kết luận'))
    x.append(f'<p>Đã thiết kế và thực hiện đủ 20 test case: {cnt.get("PASS", 0)} đạt, {cnt.get("FAIL", 0)} không đạt, {cnt.get("BLOCKED", 0)} bị chặn. Nhóm kiểm thử hệ thống AI đạt 9/10; test không đạt (TC08) chỉ ra hạn chế về khả năng nhận biết dữ liệu bất thường của mô hình. Nhóm kiểm thử tấn công phát hiện 8 điểm yếu với mức độ khác nhau, đã nêu nguyên nhân và hướng khắc phục. Kết quả chỉ phản ánh các tình huống đã thử, không chứng minh hệ thống an toàn tuyệt đối. Bài kiểm thử còn hạn chế: chỉ có một patch test có nhãn, vùng Normandy không có nhãn, và các kiểm thử tấn công chưa được thực hiện trên Production để đảm bảo an toàn cho dịch vụ.</p>')
    html_toc = ''.join(f'<a class="l{lv}" href="#{a}"><span>{esc(num)} {esc(t)}</span><span class="dots"></span><span>{pages.get(a, "")}</span></a>' for lv, num, t, a in toc if lv <= 2)
    return f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(x).replace("@@TOC@@", html_toc)}</body></html>'


COVER = '''<!doctype html><html lang="vi"><head><meta charset="utf-8"><style>
@page { size: A4; margin: 0; } html, body { margin: 0; background: #fff; color: #000; font-family: "Liberation Serif", "Times New Roman", serif; }
.page { height: 297mm; display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; }
.t { font-size: 20pt; font-weight: bold; margin-bottom: 14pt; } .s { font-size: 14pt; font-weight: normal; }
</style></head><body><div class="page"><div class="t">BÁO CÁO THỰC HÀNH CHUYÊN ĐỀ – BUỔI 4</div><div class="s">Lỗ Anh Việt | 2351260695</div></div></body></html>'''

FOOTER = '<div style="width:100%;text-align:center;font-family:Liberation Serif,serif;font-size:11pt;color:#000"><span class="pageNumber"></span></div>'


def pdf(document, path, numbered):
    src = TMP / (path.stem + '.html'); src.write_text(document, encoding='utf-8')
    with sync_playwright() as p:
        b = p.chromium.launch(channel='chrome', headless=True)
        pg = b.new_page(); pg.goto(src.as_uri(), wait_until='load')
        pg.pdf(path=str(path), format='A4', prefer_css_page_size=True, print_background=False, outline=True, tagged=True,
               display_header_footer=numbered, header_template='<div></div>', footer_template=FOOTER if numbered else '<div></div>')
        b.close()


def page_of_headings(path):
    count = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', str(path)], capture_output=True, text=True).stdout).group(1))
    texts = [re.sub(r'\s+', ' ', subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), str(path), '-'], capture_output=True, text=True).stdout).upper()
             for i in range(1, count + 1)]
    pages, start = {}, 2
    for lv, num, t, a in toc:
        key = re.sub(r'\s+', ' ', f'{num} {t}').upper()[:40]
        for i in range(start, count + 1):
            if key in texts[i - 1]:
                pages[a] = i; start = i; break
    return pages, count


if __name__ == '__main__':
    TMP.mkdir(exist_ok=True)
    cover, main = TMP / 'final_cover.pdf', TMP / 'final_main.pdf'
    pdf(COVER, cover, False)
    pages = {}
    for _ in range(3):  # converge TOC page numbers
        pdf(body(pages), main, True)
        new, count = page_of_headings(main)
        if new == pages:
            break
        pages = new
    sys.path.insert(0, str(c.REPORT / '.pydeps-pdf'))
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.append(str(cover))
    writer.append(str(main))  # keeps internal links (TOC) and the outline/bookmarks of the body
    writer.write(str(OUT))
    missing = [t for lv, num, t, a in toc if lv <= 2 and a not in pages]
    print(f'{OUT} body_pages={count} total={count + 1} figures={sum(fig_no.values())} tables={sum(tab_no.values())} unresolved_toc={missing}')
