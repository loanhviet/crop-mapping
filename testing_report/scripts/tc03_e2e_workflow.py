"""TC03 — End-to-End Inference Workflow (Local + Production): plan → submit → poll → result → downloads.

Exactly ONE small analysis (24x24 px = 5.76 ha) is submitted to production, like a normal user click.
"""
import scripts.common as c
import scripts.api_common as a
import time

from inference import PastisProvider

ev = c.Evidence('TC03', 'End-to-End Inference Workflow', 'Automation', 'Local + Production')
patch = PastisProvider().get(10003)
REQUEST = dict(season='2018–2019', geometry=c.window_geometry(patch, 0, 0, 24))
ev.save('input_request.json', REQUEST)
recorders, runs = [], {}
for env in ['Local', 'Production']:
    with a.environment(env) as client:
        rec = a.Recorder(ev, env, client); recorders.append(rec)
        out = ev.dir / env.lower(); out.mkdir()
        t0 = time.perf_counter()
        plan = rec('POST', '/api/imagery-plan', json_body=REQUEST).json()
        submit = rec('POST', '/api/analyses', json_body=REQUEST)
        ev.check(f'[{env}] POST /api/analyses trả 202 + id', submit.status_code == 202 and 'id' in submit.json(), 202, submit.status_code)
        job = submit.json()['id']
        states, status = [], {}
        deadline = time.time() + 300
        while time.time() < deadline:
            status = rec('GET', f'/api/analyses/{job}').json()
            states.append((round(time.perf_counter() - t0, 2), status['status'], status.get('progress')))
            if status['status'] in ('done', 'error', 'cancelled'):
                break
            time.sleep(2 if env == 'Production' else .3)
        total = round(time.perf_counter() - t0, 2)
        ev.check(f'[{env}] Job hoàn tất status=done', status.get('status') == 'done', 'done', status.get('status'))
        result = status.get('result', {})
        files = {}
        for fmt, name in [('tif', 'classification.tif'), ('csv', 'summary.csv'), ('geojson', 'classification.geojson'), ('png', 'classification.png')]:
            r = rec('GET', f'/api/analyses/{job}/download/{fmt}')
            (out / name).write_bytes(r.content); files[fmt] = (r.status_code, len(r.content))
        r = rec('GET', f'/api/analyses/{job}/overlay.png'); (out / 'overlay.png').write_bytes(r.content)
        r = rec('GET', f'/api/analyses/{job}/download/zip?include=tif,csv,png,geojson'); (out / 'bundle.zip').write_bytes(r.content); files['zip'] = (r.status_code, len(r.content))
        ev.check(f'[{env}] Tải đủ tif/csv/geojson/png/zip (200, không rỗng)', all(s == 200 and n > 0 for s, n in files.values()), 'tất cả 200', files)
        ev.save(f'{env.lower()}/result.json', result)
        ev.save(f'{env.lower()}/status_timeline.json', states)
        runs[env] = dict(job_id=job, plan=plan, total_seconds=total, server_duration_seconds=result.get('duration_seconds'),
                         polls=len(states), area_ha=result.get('area_ha'), mean_confidence=result.get('mean_confidence'),
                         classes={x['name']: x['pixels'] for x in result.get('classes', [])}, files=files)
        ev.log(f'[{env}] job={job} total={total}s server={result.get("duration_seconds")}s area={result.get("area_ha")} ha classes={runs[env]["classes"]}')
        ev.check(f'[{env}] Diện tích = 5.76 ha (24x24 pixel 10 m)', result.get('area_ha') == 5.76, 5.76, result.get('area_ha'))

ev.check('Phân bố lớp Local == Production (cùng checkpoint + dữ liệu)', runs['Local']['classes'] == runs['Production']['classes'], runs['Local']['classes'], runs['Production']['classes'])
a.save_exchanges(ev, recorders)
ev.save('comparison.json', runs)
c.chrome_screenshot((ev.dir / 'production' / 'classification.png').as_uri(), ev.dir / 'screenshot_production_classification.png', 600, 600, 1000)
ev.finish(expected='Cả hai môi trường: kế hoạch → job 202 → trạng thái queued/running → done; diện tích 5.76 ha; tải được GeoTIFF, CSV, GeoJSON, PNG, ZIP; kết quả Local và Production trùng nhau.',
          actual=f"Local: {runs['Local']['total_seconds']} s (suy luận {runs['Local']['server_duration_seconds']} s); Production: {runs['Production']['total_seconds']} s (suy luận {runs['Production']['server_duration_seconds']} s); phân bố lớp giống nhau: {runs['Local']['classes'] == runs['Production']['classes']}.",
          notes='Production: 1 job 5.76 ha, polling 2 s, toàn bộ tuần tự. Thời gian tổng gồm cả độ trễ mạng và chu kỳ polling.',
          metrics=runs)
