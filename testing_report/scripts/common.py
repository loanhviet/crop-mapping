"""Shared helpers for the AI-system test suite (TCxx, ATxx).

Every test script imports this module FIRST: it points the app at the provisioned
checkpoint/data of the main checkout (read-only use) and redirects job outputs to
testing_report/.runtime so real data is never modified.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

REPORT = Path(__file__).resolve().parents[1]
REPO = REPORT.parent
ASSETS = Path(os.getenv('CROP_ASSETS_ROOT', '/home/viet/projects/TLU/TSViT/crop-mapping'))
RUNTIME = REPORT / '.runtime'
EVIDENCE = REPORT / 'evidence'
PROD = os.getenv('CROP_PROD_URL', 'https://crop.loanhviet.dev')

os.environ.setdefault('CROP_DATA_DIR', str(ASSETS / 'data'))
os.environ.setdefault('CROP_WEIGHTS_DIR', str(ASSETS / 'weights'))
# Per-process results dir: app startup marks queued/running jobs in RESULTS as interrupted,
# so concurrent test processes must never share one.
os.environ.setdefault('CROP_RESULTS_DIR', str(RUNTIME / 'results' / f'{Path(sys.argv[0]).stem}-{os.getpid()}'))
os.environ.setdefault('CROP_SOURCE', 'prepared')
os.environ.setdefault('CROP_DEVICE', 'cpu')
os.environ.setdefault('CROP_THREADS', '4')
Path(os.environ['CROP_RESULTS_DIR']).mkdir(parents=True, exist_ok=True)
sys.path[:0] = [str(REPO), str(REPORT / '.pydeps')]

import numpy as np  # noqa: E402


class Evidence:
    """Collects artifacts for one test case under evidence/<ID>/."""

    def __init__(self, test_id: str, name: str, kind: str, environment: str):
        self.id, self.name, self.kind, self.environment = test_id, name, kind, environment
        self.dir = EVIDENCE / test_id
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.lines: list[str] = []
        self.checks: list[dict] = []
        self.started = time.time()
        self.log(f'{test_id} — {name} | type={kind} | env={environment}')
        self.log(f'host={os.uname().nodename} python={sys.version.split()[0]} started={datetime.now().isoformat(timespec="seconds")}')

    def log(self, message: str):
        line = f'[{datetime.now().strftime("%H:%M:%S.%f")[:-3]}] {message}'
        print(line, flush=True)
        self.lines.append(line)

    def save(self, name: str, value):
        path = self.dir / name
        if isinstance(value, (bytes, bytearray)):
            path.write_bytes(value)
        elif isinstance(value, str):
            path.write_text(value, encoding='utf-8')
        else:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=_default), encoding='utf-8')
        return path

    def check(self, name: str, passed: bool, expected, actual):
        """One assertion. Never raises: the verdict is computed from all checks."""
        self.checks.append(dict(check=name, expected=expected, actual=actual, passed=bool(passed)))
        self.log(f'{"PASS" if passed else "FAIL"} · {name} · expected={expected} · actual={actual}')
        return bool(passed)

    def finish(self, expected: str, actual: str, status: str | None = None, notes: str = '', metrics=None):
        if status is None:
            status = 'PASS' if self.checks and all(c['passed'] for c in self.checks) else 'FAIL'
        result = dict(id=self.id, name=self.name, type=self.kind, environment=self.environment,
                      status=status, expected=expected, actual=actual, notes=notes,
                      metrics=metrics or {}, checks=self.checks,
                      duration_seconds=round(time.time() - self.started, 2),
                      finished_at=datetime.now().isoformat(timespec='seconds'))
        self.log(f'VERDICT {self.id}: {status}')
        self.save('result.json', result)
        self.save('execution.log', '\n'.join(self.lines) + '\n')
        render_log(self.dir / 'execution.log', self.dir / 'log.png', f'{self.id} — execution.log (rendered from the real log file)')
        return result


def _default(value):
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    return str(value)


def render_log(source: Path, target: Path, title: str, max_lines: int = 60):
    """Render a real text artifact as an image (clearly titled as such, no editing)."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    lines = Path(source).read_text(encoding='utf-8').splitlines()
    if len(lines) > max_lines:
        lines = lines[:max_lines // 2] + [f'... ({len(lines) - max_lines} lines omitted, see {Path(source).name}) ...'] + lines[-max_lines // 2:]
    lines = [l if len(l) <= 150 else l[:147] + '...' for l in lines]
    height = 0.6 + 0.19 * (len(lines) + 1)
    fig = plt.figure(figsize=(13, height), dpi=110)
    fig.patch.set_facecolor('#1e1e1e')
    fig.text(0.01, 1 - 0.25 / height, title, color='#9cdcfe', family='DejaVu Sans Mono', fontsize=9, va='top')
    for i, line in enumerate(lines):
        color = '#6a9955' if ' PASS' in line or 'VERDICT' in line and 'PASS' in line else '#f48771' if 'FAIL' in line else '#d4d4d4'
        fig.text(0.01, 1 - (0.5 + 0.19 * (i + 1)) / height, line, color=color, family='DejaVu Sans Mono', fontsize=8, va='top')
    fig.savefig(target, facecolor=fig.get_facecolor())
    plt.close(fig)


def window_geometry(patch: dict, row: int = 0, col: int = 0, size_px: int = 24) -> dict:
    """WGS84 polygon covering pixel window [row:row+size, col:col+size] of a prepared patch."""
    from pyproj import Transformer
    west, north = patch['origin']
    x0, y0 = west + col * 10, north - row * 10
    d = size_px * 10
    to_wgs = Transformer.from_crs(patch['crs'], 4326, always_xy=True)
    ring = [list(to_wgs.transform(x, y)) for x, y in [(x0, y0), (x0 + d, y0), (x0 + d, y0 - d), (x0, y0 - d), (x0, y0)]]
    return {'type': 'Polygon', 'coordinates': [ring]}


def local_client():
    """FastAPI TestClient running the real app (real checkpoint) in-process."""
    from fastapi.testclient import TestClient
    import app as api_module
    return TestClient(api_module.app), api_module


def wait_job(client, job_id: str, timeout: float = 600, interval: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f'/api/analyses/{job_id}').json()
        if status['status'] in ('done', 'error', 'cancelled'):
            return status
        time.sleep(interval)
    return dict(status='timeout')


def prod_client(timeout: float = 30):
    """Production HTTP client: generic UA, timeout. Callers must stay sequential and small."""
    import httpx
    return httpx.Client(base_url=PROD, timeout=timeout, headers={'User-Agent': 'crop-mapping-test-suite/1.0'})


def chrome_screenshot(url: str, target: Path, width: int = 1440, height: int = 900, wait_ms: int = 8000):
    """Real headless-Chrome screenshot of a URL (or file://)."""
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run(['google-chrome', '--headless=new', '--disable-gpu', '--hide-scrollbars',
                        f'--user-data-dir={profile}', f'--window-size={width},{height}',
                        f'--virtual-time-budget={wait_ms}', f'--screenshot={target}', url],
                       check=True, capture_output=True, timeout=120)
    return target


def request_response_png(ev: Evidence, exchanges: list[dict], name: str = 'request_response.png'):
    """Render saved request/response pairs (real data) as a readable image."""
    text = []
    for x in exchanges:
        text.append(f'>>> {x.get("method","GET")} {x.get("url")}')
        if x.get('body') is not None:
            text.append('    body: ' + json.dumps(x['body'], ensure_ascii=False)[:300])
        text.append(f'<<< HTTP {x.get("status")}  ({x.get("elapsed_ms")} ms)')
        text.append('    ' + str(x.get('response'))[:600].replace('\n', ' '))
        text.append('')
    path = ev.dir / 'request_response.txt'
    path.write_text('\n'.join(text), encoding='utf-8')
    render_log(path, ev.dir / name, f'{ev.id} — request/response (rendered from request_response.txt)')
