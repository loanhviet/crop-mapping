"""Aggregate every evidence/*/result.json into summary.json + summary chart (no numbers are typed by hand)."""
import scripts.common as c
import json
from collections import Counter

import matplotlib.pyplot as plt

IDS = [f'TC{i:02d}' for i in range(1, 11)] + [f'AT{i:02d}' for i in range(1, 11)]
rows = []
for test_id in IDS:
    path = c.EVIDENCE / test_id / 'result.json'
    if path.exists():
        r = json.loads(path.read_text())
        rows.append(dict(id=test_id, name=r['name'], type=r['type'], environment=r['environment'], status=r['status'],
                         expected=r['expected'], actual=r['actual'], checks=len(r['checks']),
                         checks_passed=sum(x['passed'] for x in r['checks']), duration_seconds=r['duration_seconds']))
    else:
        rows.append(dict(id=test_id, status='BLOCKED', name='(chưa chạy)', checks=0, checks_passed=0))

prod_requests = 0
for path in c.EVIDENCE.glob('*/response.json'):
    data = json.loads(path.read_text())
    prod_requests += sum(1 for x in data if isinstance(x, dict) and x.get('env') == 'Production')
ui = c.EVIDENCE / 'TC03/ui_production/network.json'
prod_ui = len(json.loads(ui.read_text())) if ui.exists() else 0
images = sorted(str(p.relative_to(c.EVIDENCE)) for p in c.EVIDENCE.rglob('*.png'))
counts = Counter(r['status'] for r in rows)
summary = dict(total=len(IDS), executed=sum(r['status'] != 'BLOCKED' for r in rows), counts=dict(counts),
               group_a=dict(Counter(r['status'] for r in rows if r['id'].startswith('TC'))),
               group_b=dict(Counter(r['status'] for r in rows if r['id'].startswith('AT'))),
               checks=sum(r['checks'] for r in rows), checks_passed=sum(r['checks_passed'] for r in rows),
               production_api_requests_scripted=prod_requests, production_api_requests_from_ui=prod_ui,
               evidence_images=len(images), rows=rows)
(c.REPORT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))

colors = {'PASS': '#2e7d32', 'FAIL': '#c62828', 'BLOCKED': '#9e9e9e'}
fig, axes = plt.subplots(1, 2, figsize=(10, 3.6))
for ax, (title, key) in zip(axes, [('Nhóm A — Kiểm thử hệ thống AI', 'group_a'), ('Nhóm B — Tấn công / chống chịu', 'group_b')]):
    data = summary[key]
    labels = [k for k in ('PASS', 'FAIL', 'BLOCKED') if data.get(k)]
    ax.pie([data[k] for k in labels], labels=[f'{k}: {data[k]}' for k in labels], colors=[colors[k] for k in labels],
           startangle=90, wedgeprops=dict(width=.45, edgecolor='white'), textprops=dict(fontsize=10))
    ax.set_title(title, fontsize=10)
fig.tight_layout(); fig.savefig(c.EVIDENCE / '_summary_status.png', dpi=130); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 4.6))
ids = [r['id'] for r in rows]
ax.barh(ids, [r['checks_passed'] for r in rows], color='#2e7d32', label='Check đạt')
ax.barh(ids, [r['checks'] - r['checks_passed'] for r in rows], left=[r['checks_passed'] for r in rows], color='#c62828', label='Check không đạt')
ax.invert_yaxis(); ax.set_xlabel('Số assertion'); ax.legend(); ax.set_title('Số assertion đạt/không đạt theo test case', fontsize=10)
fig.tight_layout(); fig.savefig(c.EVIDENCE / '_summary_checks.png', dpi=130); plt.close(fig)
print(json.dumps({k: v for k, v in summary.items() if k != 'rows'}, ensure_ascii=False, indent=1))
