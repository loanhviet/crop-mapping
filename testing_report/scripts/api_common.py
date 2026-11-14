"""Run the same API scenario against Local (TestClient, real model) and Production (HTTPS, sequential, bounded)."""
import scripts.common as c
import json
import time
from contextlib import contextmanager

PROD_BUDGET = {'used': 0}
PROD_MAX_REQUESTS_PER_SCRIPT = 80


@contextmanager
def environment(name):
    if name == 'Local':
        client, _ = c.local_client()
        with client:
            yield client
    else:
        with c.prod_client(timeout=60) as client:
            yield client


class Recorder:
    def __init__(self, ev, env, client):
        self.ev, self.env, self.client, self.exchanges = ev, env, client, []

    def __call__(self, method, url, json_body=None, content=None, headers=None, keep_bytes=False):
        if self.env == 'Production':
            PROD_BUDGET['used'] += 1
            if PROD_BUDGET['used'] > PROD_MAX_REQUESTS_PER_SCRIPT:
                raise RuntimeError('Production request budget exceeded — aborting to protect the service.')
            time.sleep(0.3)  # gentle pacing: strictly sequential, ~3 req/s max
        t = time.perf_counter()
        r = self.client.request(method, url, json=json_body, content=content, headers=headers)
        ms = round((time.perf_counter() - t) * 1000, 1)
        ctype = r.headers.get('content-type', '')
        body = r.json() if ctype.startswith('application/json') else (f'<{ctype}, {len(r.content)} bytes>')
        self.exchanges.append(dict(env=self.env, method=method, url=url,
                                   body=json_body if json_body is not None else (content.decode()[:300] if content else None),
                                   status=r.status_code, elapsed_ms=ms, response=body))
        self.ev.log(f'[{self.env}] {method} {url} -> {r.status_code} in {ms} ms')
        return r


def save_exchanges(ev, recorders):
    exchanges = [x for r in recorders for x in r.exchanges]
    ev.save('request.json', [dict(env=x['env'], method=x['method'], url=x['url'], body=x['body']) for x in exchanges])
    ev.save('response.json', exchanges)
    shown = []
    for x in exchanges:
        y = dict(x)
        y['url'] = f"[{x['env']}] {x['url']}"
        y['response'] = json.dumps(x['response'], ensure_ascii=False)[:500] if not isinstance(x['response'], str) else x['response']
        shown.append(y)
    c.request_response_png(ev, shown)
    return exchanges
