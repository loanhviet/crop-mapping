"""TC01 — API Health & Availability on Local and Production (read-only GETs)."""
import scripts.common as c
import scripts.api_common as a
import json
import statistics

ev = c.Evidence('TC01', 'API Health & Availability', 'Automation', 'Local + Production')
manifest = json.loads((c.REPO / 'assets/model-manifest.json').read_text())
expected_sha = json.dumps(manifest)  # searched below for the checkpoint hash
ENDPOINTS = ['/api/health', '/api/catalog', '/', '/openapi.json', '/docs']
REPEAT = 3
recorders, summary = [], {}
for env in ['Local', 'Production']:
    with a.environment(env) as client:
        rec = a.Recorder(ev, env, client); recorders.append(rec)
        for _ in range(REPEAT):
            for url in ENDPOINTS:
                rec('GET', url)
        health = next(x['response'] for x in rec.exchanges if x['url'] == '/api/health')
        catalog = next(x['response'] for x in rec.exchanges if x['url'] == '/api/catalog')
        openapi = next(x for x in rec.exchanges if x['url'] == '/openapi.json')
        all_ok = all(x['status'] == 200 for x in rec.exchanges)
        lat = {u: [x['elapsed_ms'] for x in rec.exchanges if x['url'] == u] for u in ENDPOINTS}
        summary[env] = dict(requests=len(rec.exchanges), all_200=all_ok, health=health,
                            classes=len(catalog['classes']), regions=len(catalog['patches']),
                            median_ms={u: statistics.median(v) for u, v in lat.items()},
                            max_ms={u: max(v) for u, v in lat.items()})
        ev.check(f'[{env}] Tất cả {len(rec.exchanges)} request trả 200', all_ok, 'HTTP 200', sorted({x['status'] for x in rec.exchanges}))
        ev.check(f'[{env}] health: status=ok, model=TSViT', health.get('status') == 'ok' and health.get('model') == 'TSViT', 'ok/TSViT', f"{health.get('status')}/{health.get('model')}")
        ev.check(f'[{env}] checkpoint_sha256 khớp model-manifest.json của repository', health.get('checkpoint_sha256', '') in expected_sha, 'hash trong manifest', health.get('checkpoint_sha256'))
        ev.check(f'[{env}] catalog có 19 lớp cây trồng', len(catalog['classes']) == 19, 19, len(catalog['classes']))
        ev.check(f'[{env}] median /api/health < 3000 ms', summary[env]['median_ms']['/api/health'] < 3000, '< 3000 ms', summary[env]['median_ms']['/api/health'])

ev.check('Local và Production dùng cùng checkpoint', summary['Local']['health']['checkpoint_sha256'] == summary['Production']['health']['checkpoint_sha256'],
         'giống nhau', summary['Production']['health']['checkpoint_sha256'][:16] + '…')
a.save_exchanges(ev, recorders)
for name, url in [('screenshot_production_home.png', c.PROD + '/'), ('screenshot_production_swagger.png', c.PROD + '/docs')]:
    c.chrome_screenshot(url, ev.dir / name, wait_ms=12000)
    ev.log(f'Screenshot {name} <- {url} (headless Chrome)')

import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt, numpy as np
fig, ax = plt.subplots(figsize=(9, 3.8)); x = np.arange(len(ENDPOINTS))
for i, env in enumerate(summary):
    ax.bar(x + (i - .5) * .38, [summary[env]['median_ms'][u] for u in ENDPOINTS], .38, label=env)
ax.set_xticks(x, ENDPOINTS); ax.set_ylabel('Median response time (ms)'); ax.set_yscale('log'); ax.legend()
ax.set_title(f'TC01 · Thời gian phản hồi ({REPEAT} lần/endpoint/môi trường)', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'latency_local_vs_production.png', dpi=110); plt.close(fig)
ev.finish(expected='Mọi endpoint public trả 200; health báo ok/TSViT với checkpoint đúng manifest; catalog đủ 19 lớp; median /api/health < 3 s; Local và Production cùng checkpoint.',
          actual=f"Local median health={summary['Local']['median_ms']['/api/health']} ms; Production median health={summary['Production']['median_ms']['/api/health']} ms, max={summary['Production']['max_ms']['/api/health']} ms; số request production={summary['Production']['requests']}.",
          notes='Production chỉ dùng GET, tuần tự, giãn cách 0.3 s; tổng 15 request + 2 lượt chụp màn hình.',
          metrics=summary)
