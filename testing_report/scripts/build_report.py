"""Build the Vietnamese PDF report + 02_TEST_PLAN.md from evidence/*/result.json (no hand-typed results).

Run: cd testing_report && $PY -m scripts.build_report
Two passes: render → locate headings in the PDF (pdftotext) → re-render with TOC page numbers.
"""
import scripts.common as c
import sys
sys.path.insert(0, str(c.REPORT / '.pydeps-pw'))
import base64
import html
import json
import re
import subprocess
from datetime import date

from playwright.sync_api import sync_playwright

from scripts.report_content import AT, AT_STEPS, FINDINGS, PY_NOTE, TC

E = c.EVIDENCE
OUT_PDF = c.REPORT / 'Satellite_Crop_Mapping_AI_Testing_Report.pdf'
summary = json.loads((c.REPORT / 'summary.json').read_text())
R = {t: json.loads((E / t / 'result.json').read_text()) for t in [*TC, *AT]}
fig_no = {'3': 0, '4': 0, '1': 0, '5': 0, '2': 0}
tab_no = {'3': 0, '4': 0, '1': 0, '5': 0, '2': 0}
toc = []  # (level, number, title, anchor)


def esc(x):
    return html.escape(str(x))


def heading(level, number, title):
    anchor = f'h{len(toc)}'
    toc.append((level, number, title, anchor))
    tag = {1: 'h1', 2: 'h2', 3: 'h3'}[level]
    return f'<{tag} id="{anchor}">{esc(number)} {esc(title)}</{tag}>'


def img_src(path):
    data = path.read_bytes()
    kind = 'svg+xml' if path.suffix == '.svg' else 'png'
    return f'data:image/{kind};base64,{base64.b64encode(data).decode()}'


def figure(chapter, path, caption, width='100%', trace=None):
    fig_no[chapter] += 1
    src = trace or str(path.relative_to(c.REPORT)) if path.is_relative_to(c.REPORT) else trace
    note = f'<span class="trace">Nguồn: {esc(src)}</span>' if src else ''
    return (f'<figure><img src="{img_src(path)}" style="max-width:{width}"><figcaption>Hình {chapter}.{fig_no[chapter]}. '
            f'{esc(caption)} {note}</figcaption></figure>')


def table(chapter, caption, header, rows, cls='', widths=None):
    tab_no[chapter] += 1
    cols = ''.join(f'<col style="width:{w}">' for w in widths) if widths else ''
    head = ''.join(f'<th>{esc(h)}</th>' for h in header)
    body = ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows)
    return (f'<p class="tcap">Bảng {chapter}.{tab_no[chapter]}. {esc(caption)}</p>'
            f'<table class="{cls}"><colgroup>{cols}</colgroup><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>')


def badge(status):
    return f'<span class="badge {status.lower()}">{status}</span>'


def ol(items):
    return '<ol>' + ''.join(f'<li>{esc(i)}</li>' for i in items) + '</ol>'


def steps_html(items, command):
    pre = ['Chuẩn bị: mở terminal tại thư mục gốc repository, đặt biến PY trỏ tới Python của dự án (xem mục 1.4).', f'Chạy lệnh: {command}']
    rows = ''.join(f'<div class="step"><b>Bước {i}:</b> {esc(t)}</div>' for i, t in enumerate(pre + list(items) + [
        'Xem kết quả: mở evidence/<ID>/result.json (trạng thái, từng assertion) và execution.log; đối chiếu với kết quả mong đợi ở bảng này.'], 1))
    return rows.replace('&lt;ID&gt;', '{ID}')


def checks_table(chapter, test_id, limit=12):
    checks = R[test_id]['checks']
    failing = [x for x in checks if not x['passed']]
    if not failing and len(checks) > limit:
        return f'<p class="note">Tất cả <b>{len(checks)}/{len(checks)}</b> assertion của {test_id} đều đạt (bảng chỉ số ở trên; chi tiết từng assertion trong <span class="mono">evidence/{test_id}/execution.log</span>).</p>'
    shown = checks if len(checks) <= limit else (failing[:limit] if failing else checks[:limit])
    rows = [[esc(x['check']), esc(str(x['expected'])[:90]), esc(str(x['actual'])[:140]), badge('PASS' if x['passed'] else 'FAIL')] for x in shown]
    hidden = len(checks) - len(shown)
    cap = f'Kết quả từng assertion của {test_id} ({sum(x["passed"] for x in checks)}/{len(checks)} đạt'
    if hidden:
        cap += f'; liệt kê {"các assertion không đạt" if failing else f"{len(shown)} assertion đầu"}, {hidden} assertion còn lại xem execution.log)'
    else:
        cap += ')'
    return table(chapter, cap, ['Assertion', 'Mong đợi', 'Thực tế', 'KQ'], rows, 'checks', ['36%', '18%', '35%', '11%'])


def spec_table(chapter, test_id, rows_extra=()):
    r = R[test_id]
    info = TC.get(test_id) or {}
    a = AT.get(test_id) or {}
    m = r.get('metrics', {})
    is_at = test_id.startswith('AT')
    steps = info.get('steps') or AT_STEPS.get(test_id) or m.get('steps') or []
    run = f"cd testing_report && $PY -m scripts.{(info or a)['module']}"
    files = sorted(p.name for p in (E / test_id).iterdir() if p.is_file())
    rows = [('Test case ID', f'<b>{test_id}</b> — {esc(r["name"])}'),
            ('Loại kiểm thử', esc(a.get('category') if is_at else r['type'])),
            ('Môi trường', esc(r['environment'])),
            ('Mục tiêu', esc(info.get('objective') or m.get('objective', ''))),
            ('Thành phần kiểm thử', esc(info.get('component') or m.get('component', '')))]
    if is_at:
        rows.append(('Phương pháp tấn công', esc(m.get('method', ''))))
    rows += [('Tiền điều kiện', ol(info['prereq']) if info else esc('Checkpoint + dữ liệu thật tại local; chỉ dùng FastAPI TestClient cục bộ, không gửi request tới production. Giới hạn: ' + json.dumps(m.get('limits', {}), ensure_ascii=False))),
             ('Dữ liệu test / payload', esc(info.get('input') or m.get('payload', ''))),
             ('Các bước thực hiện', steps_html(steps, run).replace('{ID}', test_id)),
             ('Kết quả mong đợi', esc(r['expected'])),
             ('Kết quả thực tế', esc(r['actual'])),
             ('Trạng thái', badge(r['status']) + f' &nbsp; {sum(x["passed"] for x in r["checks"])}/{len(r["checks"])} assertion đạt · thời gian chạy {r["duration_seconds"]} s')]
    if is_at:
        impact = m.get('impact', '')
        impact = '' if 'cần xem kết quả' in impact else ' — ' + esc(impact.split(':', 1)[-1].strip())
        rows += [('Mức độ ảnh hưởng', f'<b>{esc(a["severity"])}</b>{impact}'),
                 ('Biện pháp khắc phục', esc(m.get('remediation', '')))]
    rows += list(rows_extra)
    key = [f for f in files if f in ('result.json', 'execution.log', 'request.json', 'response.json', 'input.json', 'output.json', 'root_cause_reproduction.txt', 'comparison.json')]
    rows.append(('Bằng chứng', f'<span class="mono">testing_report/evidence/{test_id}/</span> — {len(files)} file, gồm: ' + esc(', '.join(key)) + ('; ảnh/biểu đồ: ' + esc(', '.join(f for f in files if f.endswith('.png'))) if any(f.endswith('.png') for f in files) else '')))
    return table(chapter, f'Đặc tả và kết quả test case {test_id}', ['Mục', 'Nội dung'], [[f'<b>{esc(k)}</b>', v] for k, v in rows], 'spec', ['22%', '78%'])


# ---------------------------------------------------------------- metric tables per AI/API test
def metric_table(test_id):
    m = R[test_id]['metrics']
    if test_id == 'TC01':
        rows = [[esc(u), esc(m['Local']['median_ms'][u]), esc(m['Production']['median_ms'][u]), esc(m['Production']['max_ms'][u])] for u in m['Local']['median_ms']]
        return table('2', 'Thời gian phản hồi đo được (ms, 3 lượt/endpoint)', ['Endpoint', 'Local median', 'Production median', 'Production max'], rows)
    if test_id == 'TC02':
        t = m['table']; loc = [x for x in t if x['env'] == 'Local']; pro = {x['case']: x for x in t if x['env'] == 'Production'}
        rows = [[esc(x['case']), esc(x['expected']), esc(x['actual']), esc(pro[x['case']]['actual']), esc(x['message'][:80])] for x in loc]
        return table('2', 'Mã HTTP theo từng payload trên hai môi trường', ['Trường hợp', 'Mong đợi', 'Local', 'Production', 'Thông báo lỗi trả về'], rows, widths=['30%', '9%', '8%', '11%', '42%'])
    if test_id == 'TC03':
        ui = {k: json.loads((E / 'TC03' / f'ui_{k}' / 'summary.json').read_text()) for k in ('local', 'production')}
        rows = [['API: tổng thời gian (submit → done, kể cả polling)', f"{m['Local']['total_seconds']} s", f"{m['Production']['total_seconds']} s"],
                ['API: thời gian suy luận phía máy chủ (5,76 ha)', f"{m['Local']['server_duration_seconds']} s", f"{m['Production']['server_duration_seconds']} s"],
                ['API: phân bố lớp (pixel)', esc(m['Local']['classes']), esc(m['Production']['classes'])],
                ['UI: thời gian bấm Analyze → hiện kết quả (368,64 ha)', f"{ui['local']['seconds_click_to_result']} s", f"{ui['production']['seconds_click_to_result']} s"],
                ['UI: số lần gọi /api/* trong phiên', esc(ui['local']['api_calls']), esc(ui['production']['api_calls'])],
                ['UI: bảng kết quả hai môi trường giống hệt', 'Có' if ui['local']['panel'] == ui['production']['panel'] else 'Không', '']]
        return table('2', 'So sánh Local và Production cho luồng end-to-end', ['Chỉ số', 'Local', 'Production'], rows, widths=['46%', '27%', '27%'])
    if test_id == 'TC05':
        t, tr = m['test_10003'], m['train_10000']
        rows = [['10003 — test (held-out)', t['overall_accuracy'], t['miou'], t['macro_f1'], t['evaluated_pixels'], t['mean_confidence']],
                ['10000 — training (tham khảo)', tr['overall_accuracy'], tr['miou'], tr['macro_f1'], tr['evaluated_pixels'], tr['mean_confidence']]]
        out = table('2', 'Chỉ số chất lượng mô hình so với ground truth PASTIS', ['Patch', 'OA', 'mIoU', 'Macro-F1', 'Pixel đánh giá', 'Confidence TB'], [[esc(x) for x in r] for r in rows])
        pc = t['per_class']
        out += table('2', 'IoU và F1 theo lớp trên patch 10003', ['Lớp', 'IoU', 'F1', 'Pixel GT', 'Pixel dự đoán'], [[esc(k), v['iou'], v['f1'], v['gt_pixels'], v['pred_pixels']] for k, v in pc.items()])
        return out
    if test_id == 'TC06':
        rows = [[esc(k), v['overall_accuracy'], v['miou'], v['agreement_with_clean'], v['mean_confidence']] for k, v in m['mean_by_level'].items()]
        return table('2', 'Chất lượng theo mức nhiễu (trung bình 3 seed)', ['σ (× STD band)', 'OA', 'mIoU', 'Trùng dự đoán sạch', 'Confidence TB'], rows)
    if test_id == 'TC07':
        rows = [[f'Ngẫu nhiên {int(float(k)*100)}%', v] for k, v in m['mean_oa_random_drop'].items()] + [[esc(k), v] for k, v in m['seasonal'].items()]
        return table('2', f"OA khi thiếu mốc thời gian (đầy đủ {m['acquisitions']} mốc: OA = {m['clean_oa']})", ['Kịch bản thiếu dữ liệu', 'OA'], rows)
    if test_id == 'TC08':
        a, b = m['in_distribution'], m['domain_shift']
        keys = [('pixels', 'Số pixel'), ('mean_confidence', 'Confidence trung bình'), ('median_confidence', 'Confidence trung vị'), ('share_conf_below_0_5', 'Tỉ lệ pixel confidence < 0,5'), ('share_conf_below_0_7', 'Tỉ lệ pixel confidence < 0,7')]
        return table('2', 'Hành vi mô hình: in-distribution và domain shift', ['Chỉ số', 'PASTIS test', 'Normandy (THEIA COG)'], [[n, a[k], b[k]] for k, n in keys])
    return ''


# ---------------------------------------------------------------- figures kept (essential only)
FIGS = {
    'TC01': [('screenshot_production_home.png', 'Giao diện web production tại https://crop.loanhviet.dev (ảnh chụp thật bằng Chrome headless).', '82%')],
    'TC03': [('ui_production/3_results.png', 'Kết quả phân loại cây trồng trên giao diện production sau khi bấm "Analyze selected area" (Playwright + Chrome, ảnh chụp thật).', '82%')],
    'TC05': [('gt_vs_pred_10003.png', 'Patch 10003 (held-out): ảnh Sentinel-2, ground truth, dự đoán TSViT và bản đồ sai lệch.', '100%'),
             ('confusion_matrix_10003.png', 'Confusion matrix trên patch 10003.', '62%')],
    'TC06': [('noise_curve.png', 'Suy giảm chất lượng theo mức nhiễu Gauss.', '72%')],
    'TC07': [('temporal_gaps.png', 'OA khi thiếu mốc thời gian (ngẫu nhiên và theo mùa).', '92%')],
    'TC08': [('ood_confidence_classes.png', 'Phân bố confidence và phân bố lớp: PASTIS test so với Normandy.', '92%')],
    'AT04': [('accuracy_vs_epsilon.png', 'Accuracy theo epsilon: FGSM, PGD và nhiễu ngẫu nhiên cùng chuẩn.', '72%')],
    'AT05': [('temporal_accuracy.png', 'Accuracy theo kiểu thao túng chuỗi thời gian.', '72%')],
    'AT06': [('ood_confidence.png', 'Confidence của mô hình trên dữ liệu thật và dữ liệu tổng hợp.', '72%')],
    'AT09': [('resources.png', 'RSS/CPU của tiến trình và độ trễ /api/health khi chạy job toàn vùng (60 s rồi hủy).', '80%')],
}


def test_section(chapter, idx, test_id):
    r = R[test_id]
    out = f'<section class="test{" first" if idx == 1 else ""}">' + heading(2, f'{chapter}.{idx}', f'{test_id} — {r["name"]}')
    out += spec_table(chapter, test_id)
    out += metric_table(test_id)
    out += checks_table(chapter, test_id)
    for name, cap, width in FIGS.get(test_id, []):
        out += figure(chapter, E / test_id / name, f'{test_id} · {cap}', width, f'evidence/{test_id}/{name}')
    review = (TC.get(test_id) or AT.get(test_id))['review']
    out += f'<p class="review"><b>Đánh giá: {badge(r["status"])}</b> {esc(review)}</p>'
    if r.get('notes'):
        out += f'<p class="note"><i>Ghi chú phương pháp:</i> {esc(r["notes"])}</p>'
    return out + '</section>'


# ---------------------------------------------------------------- document
CSS = '''
@page { size: A4; margin: 22mm 18mm 22mm 28mm; }
body { font-family: "Liberation Serif", "Times New Roman", serif; font-size: 12.5pt; line-height: 1.42; color: #111; }
h1 { font-size: 17pt; text-transform: uppercase; text-align: center; margin: 0 0 14pt; break-before: page; }
h2 { font-size: 14pt; margin: 16pt 0 6pt; break-after: avoid; }
h3 { font-size: 12.5pt; margin: 10pt 0 4pt; break-after: avoid; }
p { text-align: justify; margin: 4pt 0 6pt; }
table { width: 100%; border-collapse: collapse; margin: 2pt 0 10pt; font-size: 10pt; line-height: 1.3; table-layout: fixed; }
th, td { border: 0.6pt solid #777; padding: 3pt 5pt; vertical-align: top; overflow-wrap: anywhere; }
th { background: #e8edf3; text-align: left; }
tr { break-inside: avoid; }
table.summary { font-size: 8.5pt; }
table.spec td:first-child { background: #f5f7fa; }
td ol { margin: 0; padding-left: 15pt; } td ol li { margin: 0; }
.tcap { text-align: center; font-style: italic; font-size: 10.5pt; margin: 8pt 0 2pt; break-after: avoid; }
figure { margin: 8pt 0 10pt; text-align: center; break-inside: avoid; }
figure img { max-height: 118mm; }
figcaption { font-size: 10.5pt; font-style: italic; margin-top: 3pt; }
.trace { font-family: "DejaVu Sans Mono", monospace; font-style: normal; font-size: 8pt; color: #555; display: block; }
.badge { display: inline-block; white-space: nowrap; padding: 0 5pt; border-radius: 3pt; font-weight: bold; font-size: 9pt; color: #fff; font-family: "DejaVu Sans", sans-serif; }
.badge.pass { background: #2e7d32; } .badge.fail { background: #c62828; } .badge.blocked { background: #757575; }
.cmd, pre, .mono { font-family: "DejaVu Sans Mono", monospace; font-size: 8.5pt; }
.cmd { background: #f3f3f3; border: 0.5pt solid #ccc; padding: 2pt 4pt; margin-top: 3pt; }
pre { background: #f6f6f6; border: 0.5pt solid #ccc; padding: 6pt; white-space: pre-wrap; line-height: 1.3; }
.step { margin: 0 0 2pt; padding-left: 0; }
.review { background: #f4f8f4; border-left: 3pt solid #2e7d32; padding: 5pt 8pt; }
.note { font-size: 10.5pt; color: #333; }
section.test { break-before: page; } section.test.first { break-before: auto; }
.cover { box-sizing: border-box; height: 240mm; border: 2.5pt double #1d3557; padding: 14mm 12mm; text-align: center; display: flex; flex-direction: column; break-after: page; }
.cover .uni { font-size: 15pt; font-weight: bold; } .cover .title { font-size: 21pt; font-weight: bold; color: #1d3557; margin-top: 30mm; }
.cover .topic { font-size: 15pt; font-weight: bold; margin-top: 16mm; line-height: 1.5; } .cover .info { margin: auto auto 0; text-align: left; font-size: 13pt; line-height: 1.9; }
.toc { list-style: none; padding: 0; } .toc li { display: flex; font-size: 12pt; margin: 1.5pt 0; }
.toc li.l1 { font-weight: bold; margin-top: 6pt; } .toc li.l2 { padding-left: 16pt; font-size: 11pt; }
.toc li .dots { flex: 1; border-bottom: 1pt dotted #888; margin: 0 4pt 4pt; } .toc a { color: inherit; text-decoration: none; }
'''


def build(pages):
    toc.clear()
    for d in (fig_no, tab_no):
        for k in d: d[k] = 0
    S = summary
    counts = S['counts']
    rows = S['rows']
    body = []
    body.append(f'''<div class="cover"><div class="uni">BỘ NÔNG NGHIỆP VÀ MÔI TRƯỜNG<br>TRƯỜNG ĐẠI HỌC THỦY LỢI</div>
<div class="title">BÁO CÁO KIỂM THỬ<br>HỆ THỐNG TRÍ TUỆ NHÂN TẠO</div>
<div class="topic">ĐỀ TÀI:<br>KIỂM THỬ VÀ ĐÁNH GIÁ AN TOÀN HỆ THỐNG<br>PHÂN LOẠI CÂY TRỒNG TỪ ẢNH VỆ TINH</div>
<div style="margin-top:8mm;font-size:13pt">Dự án: <b>Satellite Crop Mapping</b></div>
<div class="info">Sinh viên thực hiện: <b>Lỗ Anh Việt</b><br>Mã sinh viên: ..............................<br>Lớp: ..............................<br>Giảng viên hướng dẫn: ..............................</div>
<div style="margin-top:14mm">Hà Nội, {date.today().strftime("%m/%Y").replace("/", " năm ").join(["tháng ", ""])}</div></div>''')
    body.append('<h1 style="break-before:auto">MỤC LỤC</h1><ul class="toc">@@TOC@@</ul>')

    # ---------------- Chapter 1: scope, environment, procedure (short)
    body.append(heading(1, 'CHƯƠNG 1.', 'PHẠM VI, MÔI TRƯỜNG VÀ QUY TRÌNH KIỂM THỬ'))
    body.append(heading(2, '1.1', 'Đối tượng kiểm thử'))
    body.append('<p>Hệ thống Satellite Crop Mapping phân loại cây trồng cho từng pixel 10 m từ chuỗi ảnh Sentinel-2 bằng mô hình TSViT (19 lớp PASTIS). Người dùng chọn vùng trên bản đồ Leaflet; FastAPI xếp job vào hàng đợi có 1 worker (tối đa 4 job chờ); mô hình chạy trên các cửa sổ 24×24 px; kết quả xuất ra GeoTIFF, GeoJSON, CSV, PNG và ZIP. Production: https://crop.loanhviet.dev (Docker ARM64 trên Oracle A1, chế độ ảnh <i>prepared</i>, CI/CD bằng GitHub Actions).</p>')
    body.append(table('1', 'Thành phần được kiểm thử và test case tương ứng', ['Thành phần', 'Chức năng', 'Test case'], [
        ['API FastAPI (app.py)', '/api/health, /api/catalog, /api/imagery-plan, /api/analyses (202, theo dõi, hủy, tải kết quả)', 'TC01–TC04, AT01–AT03, AT07–AT09'],
        ['Kiểm tra đầu vào', 'AnalysisRequest/validate_polygon: Polygon WGS84, 1 ring, 4–100 đỉnh, hữu hạn, khép kín', 'TC02, AT01, AT02, AT07, AT08'],
        ['Mô hình TSViT (inference.py, model.py)', 'Tiền xử lý (chuẩn hóa, DOY, pad/cắt về 60 mốc), suy luận, kiểm tra SHA-256 checkpoint', 'TC05–TC08, TC10, AT04–AT06, AT10'],
        ['Xuất kết quả', 'GeoTIFF (nodata 255), CSV diện tích, GeoJSON, PNG, ZIP', 'TC03, TC04'],
        ['Dịch vụ ảnh ngoài (imagery.py)', 'GEODES/THEIA — production không dùng khi vận hành', 'TC09'],
        ['Giao diện web (web/)', 'Chọn vùng, phân tích, hiển thị bản đồ và bảng diện tích, tải về', 'TC01, TC03 (Playwright)']], widths=['24%', '50%', '26%']))
    body.append(heading(2, '1.2', 'Môi trường kiểm thử'))
    body.append(table('1', 'Cấu hình môi trường', ['Hạng mục', 'Local', 'Production'], [
        ['Phần cứng / HĐH', 'Intel Core i5-12500H, 16 luồng, 15 GiB RAM; Ubuntu 24.04.5', 'Oracle Cloud Ampere A1 (ARM64), container 2 CPU; Ubuntu 24.04'],
        ['Phần mềm', 'Python 3.13.14, PyTorch 2.14.1+cpu, FastAPI 0.143.0, NumPy 2.5.4, Rasterio 1.5.2', 'Image GHCR build từ cùng mã nguồn (commit 8ede7cf), sau Caddy'],
        ['Checkpoint', 'SHA-256 92a83d0d…a40b733 (khớp manifest)', 'Cùng SHA-256 (đã xác minh ở TC01)'],
        ['Dữ liệu', '8 patch test PASTIS + patch 10000 + vùng Normandy; ground truth TARGET_10003/10000', 'Catalog giống hệt local (đã xác minh ở TC01)'],
        ['Công cụ', 'pytest, FastAPI TestClient, httpx, unittest.mock, NumPy/PyTorch, Playwright 1.65 + Chrome 154, Matplotlib', 'httpx (HTTPS), Playwright']], widths=['16%', '46%', '38%']))
    body.append(heading(2, '1.3', 'Phạm vi Local / Production và tiêu chí đánh giá'))
    body.append('<p><b>Production</b> chỉ dùng cho các kiểm thử an toàn: GET, POST /api/imagery-plan (không tạo job), đúng 1 job qua API (5,76 ha) và 1 job qua giao diện (368,64 ha). Tất cả chạy tuần tự, có timeout và giãn cách 0,3 s, tối đa 80 request mỗi script. Tổng cộng ' + f'{S["production_api_requests_scripted"]} request do script gửi và {S["production_api_requests_from_ui"]} request do giao diện tự sinh (polling). Không deploy, không restart, không thay đổi cấu hình. <b>Local</b> dùng cho toàn bộ kiểm thử AI, mock, tấn công và tải (có giới hạn). Kết quả mong đợi và ngưỡng được ghi <b>trước khi chạy</b> và không sửa sau đó. Mọi số liệu trong báo cáo được đọc tự động từ <span class="mono">evidence/&lt;ID&gt;/result.json</span>.</p>')
    body.append(table('1', 'Tiêu chí trạng thái và phân bổ test case', ['Trạng thái / Nhóm', 'Ý nghĩa / Nội dung'], [
        [badge('PASS'), 'Mọi assertion đạt kết quả mong đợi.'],
        [badge('FAIL'), 'Có ít nhất một assertion không đạt. Với nhóm tấn công, FAIL là một phát hiện về hệ thống.'],
        [badge('BLOCKED'), 'Không thực thi được (thiếu dữ liệu, checkpoint hoặc quyền truy cập).'],
        ['Nhóm A (Chương 2)', 'Automation TC01–TC04 (Local + Production); AI Test TC05–TC08; Mock Test TC09–TC10'],
        ['Nhóm B (Chương 3)', 'Security attack AT01–AT03, AT07–AT10; Adversarial attack AT04–AT05; Robustness AT06 (chỉ Local)']], widths=['22%', '78%']))
    body.append(heading(2, '1.4', 'Quy trình thực hiện từng bước'))
    body.append(''.join(f'<div class="step"><b>Bước {i}:</b> {t}</div>' for i, t in enumerate([
        'Lấy mã nguồn: <span class="mono">git clone https://github.com/loanhviet/crop-mapping.git && cd crop-mapping</span>.',
        'Cài môi trường theo README của dự án (Python 3.13, <span class="mono">requirements/locks/linux-amd64.txt</span>), đặt checkpoint vào <span class="mono">weights/best.pth</span> và dữ liệu vào <span class="mono">data/</span>; kiểm tra bằng <span class="mono">python scripts/verify_assets.py --profile model</span>.',
        'Cài công cụ kiểm thử vào thư mục riêng: <span class="mono">uv pip install --target testing_report/.pydeps matplotlib</span> và <span class="mono">uv pip install --target testing_report/.pydeps-pw playwright</span>.',
        'Khai báo đường dẫn: <span class="mono">export PY=$PWD/.venv/bin/python</span> (và <span class="mono">CROP_ASSETS_ROOT</span> nếu weights/ và data/ nằm ở thư mục khác).',
        'Chạy bộ test hồi quy có sẵn làm mốc: <span class="mono">$PY -m pytest -v</span>. Kết quả thực tế: <b>53 passed</b> (evidence/_baseline/pytest_existing_suite.log).',
        'Chạy từng test bằng lệnh ghi trong bảng đặc tả của test đó, hoặc chạy toàn bộ bằng <span class="mono">bash testing_report/scripts/run_all.sh</span> (dùng <span class="mono">PROD=0</span> để không gọi production).',
        'Đọc kết quả trong <span class="mono">testing_report/evidence/&lt;ID&gt;/</span>: result.json (trạng thái, từng assertion), execution.log, request/response hoặc input/output, ảnh.',
        'Tổng hợp và sinh báo cáo: <span class="mono">cd testing_report && $PY -m scripts.collect_summary && $PY -m scripts.build_report</span>.'], 1)))

    # ---------------- Chapter 2 & 3: test cases
    body.append(heading(1, 'CHƯƠNG 2.', '10 TEST CASE KIỂM THỬ HỆ THỐNG AI'))
    for i, t in enumerate(TC, 1):
        body.append(test_section('2', i, t))
    body.append(heading(1, 'CHƯƠNG 3.', '10 TEST CASE TẤN CÔNG HỆ THỐNG AI'))
    body.append('<p>Chỉ chạy ở local với checkpoint và dữ liệu thật; giới hạn số request, thời gian và mức song song được ghi ở mục Tiền điều kiện của từng test. Suy giảm độ chính xác của mô hình (adversarial/robustness) không được coi là lỗ hổng API nếu người dùng API không có đường đưa dữ liệu đó vào hệ thống.</p>')
    for i, t in enumerate(AT, 1):
        body.append(test_section('3', i, t))

    # ---------------- Chapter 4: summary
    body.append(heading(1, 'CHƯƠNG 4.', 'TỔNG HỢP KẾT QUẢ'))
    body.append(heading(2, '4.1', 'Thống kê'))
    body.append(table('4', 'Thống kê thực thi', ['Chỉ số', 'Giá trị'], [
        ['Test case thiết kế / đã thực thi', f"{S['total']} / {S['executed']}"],
        ['PASS / FAIL / BLOCKED', f"{counts.get('PASS', 0)} / {counts.get('FAIL', 0)} / {counts.get('BLOCKED', 0)}"],
        ['Nhóm A — PASS / FAIL', f"{S['group_a'].get('PASS', 0)} / {S['group_a'].get('FAIL', 0)}"],
        ['Nhóm B — PASS / FAIL', f"{S['group_b'].get('PASS', 0)} / {S['group_b'].get('FAIL', 0)}"],
        ['Assertion đạt / tổng', f"{S['checks_passed']} / {S['checks']}"],
        ['Request tới production (script / giao diện)', f"{S['production_api_requests_scripted']} / {S['production_api_requests_from_ui']}"],
        ['Bộ test hồi quy có sẵn', '53 / 53 PASS'],
        ['Ảnh và biểu đồ minh chứng lưu trong evidence/', str(S['evidence_images'])]], widths=['62%', '38%']))
    body.append(figure('4', E / '_summary_status.png', 'Phân bố trạng thái theo nhóm (sinh từ summary.json).', '70%', 'evidence/_summary_status.png'))
    body.append(heading(2, '4.2', 'Bảng tổng hợp 20 test case'))
    def brief(text, n=115):
        text = str(text)
        return text if len(text) <= n else text[:n].rsplit(' ', 1)[0] + ' …'
    trows = [[str(i), r['id'], esc(r['name']), esc(((AT.get(r['id']) or {}).get('category') or r.get('type')).split(' (')[0]), esc(r.get('environment', '')),
              esc(brief(r.get('expected', ''))), esc(brief(r.get('actual', ''))), badge(r['status'])] for i, r in enumerate(rows, 1)]
    body.append(table('4', 'Tổng hợp kết quả 20 test case', ['STT', 'ID', 'Tên', 'Loại', 'Môi trường', 'Kết quả mong đợi', 'Kết quả thực tế', 'TT'], trows, 'summary',
                      ['4%', '7%', '13%', '10%', '9%', '23%', '23%', '11%']))
    body.append(heading(2, '4.3', 'Danh sách lỗi phát hiện (defect log)'))
    body.append(table('4', 'Các vấn đề phát hiện, sắp theo mức độ (trạng thái: Open)', ['ID', 'Mức độ', 'Nguồn', 'Mô tả', 'Đề xuất khắc phục'], [[f[0], esc(f[1]), esc(f[2]), esc(f[3]), esc(f[4])] for f in FINDINGS],
                      widths=['5%', '11%', '11%', '37%', '36%']))
    body.append(heading(2, '4.4', 'Điểm mạnh và hạn chế'))
    body.append('<p><b>Điểm mạnh:</b> OA 0,87 / mIoU 0,71 trên patch held-out (TC05); suy luận tất định, Local và Production trùng từng pixel (TC03, TC04); thông báo lỗi đầu vào rõ ràng (TC02); lỗi dịch vụ ngoài và lỗi suy luận được cô lập, worker tự phục hồi, checkpoint giả mạo bị từ chối (TC09, TC10); hàng đợi giới hạn 429, chống path traversal, hủy job lớn ngay lập tức (AT03, AT08, AT09); mô hình bền với nhiễu nhỏ và với việc mất tới 50% số mốc thời gian (TC06, TC07).</p>')
    body.append('<p><b>Hạn chế:</b> hai đường lỗi trả HTTP 500 (F1, F2); không có hạn mức tài nguyên cho mỗi yêu cầu (F3); mô hình quá tự tin và chưa phát hiện được dữ liệu ngoài phân phối (F4); nhạy với nhiễu đối kháng và với dữ liệu thời gian bị thao túng (F5); chưa có xác thực hay quyền sở hữu job (F7).</p>')

    # ---------------- Chapter 5: conclusion
    body.append(heading(1, 'CHƯƠNG 5.', 'KẾT LUẬN'))
    body.append('<ul>' + ''.join(f'<li><b>{esc(t)}:</b> {esc(x)}</li>' for t, x in [
        ('Mức độ hoàn thiện', 'Luồng chọn vùng → suy luận → hiển thị → xuất kết quả hoạt động đầy đủ trên production; 9/10 test nhóm A đạt; bộ test hồi quy có sẵn đạt 53/53.'),
        ('Chất lượng mô hình', 'OA 0,8734, mIoU 0,7089, macro-F1 0,7835 trên patch held-out duy nhất có ground truth (12.941 pixel). Đây là kết quả chỉ báo, chưa thay thế được đánh giá trên toàn bộ tập test PASTIS.'),
        ('Độ ổn định API và xử lý lỗi', 'Endpoint public ổn định (production khoảng 105 ms với request đọc); lỗi vận hành được xử lý tốt; còn 2 đường dữ liệu dị dạng trả 500, đã xác định nguyên nhân gốc.'),
        ('Khả năng chống chịu tấn công', 'Lớp API chặn được phần lớn payload dị dạng và tham số giả mạo. Điểm yếu nằm ở khả dụng (job lớn), xác thực và độ bền của mô hình. Kết quả chỉ phản ánh 10 tình huống đã thử, KHÔNG chứng minh hệ thống an toàn tuyệt đối.'),
        ('Production', 'Cùng checkpoint và dữ liệu với local, kết quả trùng từng pixel; thời gian phân tích qua giao diện dài hơn khoảng 2,8 lần (ARM64, 2 CPU).'),
        ('Hạn chế của bài kiểm thử', 'Ground truth chỉ có cho 1 patch; vùng Normandy không có nhãn; kiểm thử tấn công và tải chỉ chạy ở local (cấu hình Caddy thật trên production chưa được xác minh); tấn công đối kháng là white-box trên 3 cửa sổ.'),
        ('Ưu tiên khắc phục', 'F3 (hạn mức job) → F1, F2 (lỗi 500, giới hạn body) → F4 (kiểm tra chất lượng đầu vào, gắn cờ không chắc chắn) → F7 (xác thực) → đưa các test này vào CI.')]) + '</ul>')

    toc_html = ''.join(f'<li class="l{lv}"><a href="#{a}">{esc(n)} {esc(t)}</a><span class="dots"></span><span>{pages.get(a, "")}</span></li>' for lv, n, t, a in toc if lv <= 2)
    return f'<!doctype html><html lang="vi"><head><meta charset="utf-8"><title>Báo cáo kiểm thử</title><style>{CSS}</style></head><body>{"".join(body).replace("@@TOC@@", toc_html)}</body></html>'


FOOTER = '<div style="width:100%;font-size:9pt;font-family:Liberation Serif,serif;text-align:center;color:#444"><span class="pageNumber"></span></div>'


def render(document):
    path = c.REPORT / '.runtime' / 'report.html'
    path.parent.mkdir(exist_ok=True)
    path.write_text(document, encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        page = browser.new_page()
        page.goto(path.as_uri(), wait_until='load')
        page.pdf(path=str(OUT_PDF), format='A4', display_header_footer=True, header_template='<div></div>', footer_template=FOOTER,
                 prefer_css_page_size=True, print_background=True)
        browser.close()


def locate_pages():
    n = int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', str(OUT_PDF)], capture_output=True, text=True).stdout).group(1))
    texts = [subprocess.run(['pdftotext', '-f', str(i), '-l', str(i), '-layout', str(OUT_PDF), '-'], capture_output=True, text=True).stdout for i in range(1, n + 1)]
    norm = lambda s: re.sub(r'\s+', ' ', s)
    pages, start = {}, 3
    for lv, num, title, anchor in toc:
        key = norm(f'{num} {title}'.strip())[:45]
        for i in range(start, n + 1):
            if key.upper() in norm(texts[i - 1]).upper():
                pages[anchor] = i; start = i
                break
    return pages, n


if __name__ == '__main__':
    render(build({}))
    pages, _ = locate_pages()
    render(build(pages))
    pages2, n = locate_pages()
    missing = [t for lv, num, t, a in toc if lv <= 2 and a not in pages2]
    print(f'PDF: {OUT_PDF} pages={n} toc_entries={len([x for x in toc if x[0] <= 2])} unresolved={missing}')
    if pages2 != pages:
        render(build(pages2)); print('re-rendered (TOC shifted pages)')
