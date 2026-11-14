"""Generate 02_TEST_PLAN.md from report_content (design) + evidence/*/result.json (actual results)."""
import scripts.common as c
import json

from scripts.report_content import AT, AT_STEPS, TC

out = ['# 02 — Test Plan: 20 test case', '',
       'Thiết kế (mục tiêu, input, expected, steps) được viết trước khi chạy; cột kết quả được điền tự động từ `evidence/<ID>/result.json`.', '',
       '| ID | Tên | Loại | Môi trường | Trạng thái |', '|---|---|---|---|---|']
for t in [*TC, *AT]:
    r = json.loads((c.EVIDENCE / t / 'result.json').read_text())
    kind = AT[t]['category'] if t in AT else r['type']
    out.append(f"| {t} | {r['name']} | {kind} | {r['environment']} | **{r['status']}** |")
for t in [*TC, *AT]:
    r = json.loads((c.EVIDENCE / t / 'result.json').read_text())
    d, m = (TC.get(t) or {}), r.get('metrics', {})
    steps = d.get('steps') or AT_STEPS.get(t, [])
    module = (TC.get(t) or AT.get(t))['module']
    out += ['', f"## {t} — {r['name']}", '',
            f"1. **ID:** {t}", f"2. **Tên:** {r['name']}", f"3. **Loại:** {AT[t]['category'] if t in AT else r['type']}",
            f"4. **Mục tiêu:** {d.get('objective') or m.get('objective', '')}",
            f"5. **Thành phần:** {d.get('component') or m.get('component', '')}",
            f"6. **Môi trường:** {r['environment']}",
            f"7. **Điều kiện tiên quyết:** {'; '.join(d['prereq']) if d else 'Checkpoint + dữ liệu thật tại local; giới hạn ' + json.dumps(m.get('limits', {}), ensure_ascii=False)}",
            f"8. **Input:** {d.get('input') or m.get('payload', '')}",
            f"9. **Expected:** {r['expected']}",
            '10. **Steps:** ' + ' '.join(f'({i}) {s}' for i, s in enumerate(steps, 1)) + f' — lệnh: `cd testing_report && $PY -m scripts.{module}`',
            f"11. **Actual:** {r['actual']}",
            f"12. **Status:** {r['status']} ({sum(x['passed'] for x in r['checks'])}/{len(r['checks'])} assertion)",
            f"13. **Evidence:** `testing_report/evidence/{t}/`",
            f"14. **Nhận xét:** {(TC.get(t) or AT.get(t))['review']}"]
(c.REPORT / '02_TEST_PLAN.md').write_text('\n'.join(out) + '\n', encoding='utf-8')
print('written', len(out), 'lines')
