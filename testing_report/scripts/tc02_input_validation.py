"""TC02 — API Input Validation on Local and Production.

Uses POST /api/imagery-plan only: it validates the same AnalysisRequest model as /api/analyses
but never creates a job, so it is safe on production. 10 small sequential requests per environment.
"""
import scripts.common as c
import scripts.api_common as a
from inference import PastisProvider

ev = c.Evidence('TC02', 'API Input Validation', 'Automation', 'Local + Production')
patch = PastisProvider().get(10003)
valid = c.window_geometry(patch, 0, 0, 24)
ring = valid['coordinates'][0]
CASES = [
    ('V1 hợp lệ: ô 24x24 trong patch 10003', dict(season='2018–2019', geometry=valid), 200),
    ('I1 thiếu geometry', dict(season='2018–2019'), 422),
    ('I2 geometry là Point', dict(geometry={'type': 'Point', 'coordinates': ring[0]}), 422),
    ('I3 ring không khép kín', dict(geometry={'type': 'Polygon', 'coordinates': [ring[:-1]]}), 422),
    ('I4 chỉ 3 điểm', dict(geometry={'type': 'Polygon', 'coordinates': [[ring[0], ring[1], ring[0]]]}), 422),
    ('I5 vĩ độ 95° (ngoài WGS84)', dict(geometry={'type': 'Polygon', 'coordinates': [[[2, 95], [3, 95], [3, 94], [2, 95]]]}), 422),
    ('I6 mùa không có dữ liệu 2025–2026', dict(season='2025–2026', geometry=valid), 422),
    ('I7 vùng ngoài khu vực có ảnh (Hà Nội)', dict(geometry={'type': 'Polygon', 'coordinates': [[[105.80, 21.02], [105.81, 21.02], [105.81, 21.01], [105.80, 21.01], [105.80, 21.02]]]}), 422),
    ('I8 patch_id không tồn tại', dict(patch_id=999999, geometry=valid), 422),
    ('I9 patch_id sai kiểu (chuỗi)', dict(patch_id='abc', geometry=valid), 422),
]
recorders, table = [], []
for env in ['Local', 'Production']:
    with a.environment(env) as client:
        rec = a.Recorder(ev, env, client); recorders.append(rec)
        for name, body, expected in CASES:
            r = rec('POST', '/api/imagery-plan', json_body=body)
            detail = r.json().get('detail') if r.headers.get('content-type', '').startswith('application/json') else None
            message = detail if isinstance(detail, str) else (detail[0].get('msg') if isinstance(detail, list) and detail else '')
            table.append(dict(env=env, case=name, expected=expected, actual=r.status_code, message=message, ms=rec.exchanges[-1]['elapsed_ms']))
            ev.check(f'[{env}] {name}', r.status_code == expected, expected, f'{r.status_code} {message[:90]}')
            if r.status_code == 500 or 'Traceback' in r.text:
                ev.check(f'[{env}] {name}: không lộ stack trace', False, 'không có Traceback', r.text[:200])

local = {t['case']: t for t in table if t['env'] == 'Local'}
prod = {t['case']: t for t in table if t['env'] == 'Production'}
same = all(local[k]['actual'] == prod[k]['actual'] and local[k]['message'] == prod[k]['message'] for k in local)
ev.check('Local và Production trả cùng mã trạng thái và cùng thông báo lỗi cho mọi case', same, 'giống nhau', same)
ev.save('comparison.json', table)
a.save_exchanges(ev, recorders)
passed = sum(1 for t in table if t['expected'] == t['actual'])
ev.finish(expected='Input hợp lệ → 200 kèm kế hoạch phân tích; mọi input sai → 422 với thông báo rõ ràng, không có 500/stack trace; hành vi Local và Production giống nhau.',
          actual=f'{passed}/{len(table)} lượt đúng mã kỳ vọng; Local/Production nhất quán: {same}.',
          notes='Production: 10 POST tuần tự tới /api/imagery-plan (không tạo job, không ghi dữ liệu).',
          metrics=dict(cases=len(CASES), table=table))
