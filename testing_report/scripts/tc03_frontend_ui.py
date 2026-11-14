"""TC03 (UI part) — real browser drives the Leaflet frontend: load → Ready → Analyze → results table.

Usage: python -m scripts.tc03_frontend_ui <base_url> <label>
Writes evidence/TC03/ui_<label>/ (screenshots + network log). One analysis click per run.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '.pydeps-pw'))
import json
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

base, label = sys.argv[1].rstrip('/'), sys.argv[2]
out = Path(__file__).resolve().parents[1] / 'evidence' / 'TC03' / f'ui_{label}'
out.mkdir(parents=True, exist_ok=True)
log, network = [], []


def note(msg):
    line = f'[{datetime.now().strftime("%H:%M:%S")}] {msg}'
    print(line, flush=True); log.append(line)


with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport=dict(width=1440, height=900))
    page.on('response', lambda r: network.append(dict(t=round(time.time(), 2), method=r.request.method, url=r.url.replace(base, ''), status=r.status))
            if '/api/' in r.url else None)
    note(f'open {base}/')
    page.goto(base + '/', wait_until='networkidle', timeout=60000)
    page.wait_for_selector('#ready-state:not([hidden])', timeout=60000)
    note('ready-state: ' + page.inner_text('#ready-description'))
    page.screenshot(path=out / '1_ready.png')
    t0 = time.time()
    page.click('#analyze')
    page.wait_for_selector('#running-state:not([hidden])', timeout=30000)
    time.sleep(1.5)
    note('running: ' + page.inner_text('#progress-message'))
    page.screenshot(path=out / '2_running.png')
    page.wait_for_selector('#results:not([hidden]), #error-state:not([hidden])', timeout=600000)
    elapsed = round(time.time() - t0, 1)
    ok = page.is_visible('#results')
    note(f'finished after {elapsed}s, results visible={ok}')
    time.sleep(3)  # let overlay tiles render
    page.screenshot(path=out / '3_results.png')
    table = page.inner_text('#results') if ok else page.inner_text('#error-state')
    note('results panel:\n' + table)
    page.click('#export') if ok else None
    if ok:
        page.wait_for_selector('#export-dialog[open]', timeout=10000)
        page.screenshot(path=out / '4_export_dialog.png')
        note('export dialog: ' + page.inner_text('#export-description'))
    browser.close()

(out / 'network.json').write_text(json.dumps(network, indent=1))
(out / 'ui.log').write_text('\n'.join(log) + '\n', encoding='utf-8')
(out / 'summary.json').write_text(json.dumps(dict(base=base, results_visible=ok, seconds_click_to_result=elapsed,
                                                  analyses_posts=sum(1 for n in network if n['method'] == 'POST' and n['url'] == '/api/analyses'),
                                                  api_calls=len(network), panel=table), ensure_ascii=False, indent=1))
