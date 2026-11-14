"""TC09 — External Service Failure (Mock): the GEODES/THEIA satellite catalogue is unreachable or fails mid-job.

The real GeodesProvider code runs; only the network layer (httpx.Client.send) or the provider method is mocked.
No request leaves this machine.
"""
import scripts.common as c
import json
import os
import time
from unittest import mock

import httpx

import imagery
from imagery import ImageryError

ev = c.Evidence('TC09', 'External Service Failure', 'Mock Test', 'Local (mock)')
client, api = c.local_client()
exchanges = []
GEOM = {'type': 'Polygon', 'coordinates': [[[1.40, 49.10], [1.405, 49.10], [1.405, 49.097], [1.40, 49.097], [1.40, 49.10]]]}
REQUEST = dict(season='2018–2019', geometry=GEOM)


def call(method, url, **kw):
    t = time.perf_counter()
    r = getattr(client, method)(url, **kw)
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text[:200]
    exchanges.append(dict(method=method.upper(), url=url, body=kw.get('json'), status=r.status_code,
                          elapsed_ms=round((time.perf_counter() - t) * 1000, 1), response=body))
    return r, body


with client, mock.patch.dict(os.environ, {'GEODES_API_KEY': 'mock-key-not-real'}):
    api.app.state.source_mode = 'geodes'           # live-imagery mode, as when CROP_SOURCE=geodes
    sent = []

    RealClient = httpx.Client
    def geodes_network(handler):
        """Only the GEODES httpx client created inside imagery.py gets the mock transport."""
        def factory(*a, **kw):
            kw['transport'] = httpx.MockTransport(handler)
            return RealClient(*a, **kw)
        return mock.patch.object(imagery.httpx, 'Client', factory)

    # S1: catalogue unreachable (DNS/TCP failure) — real provider code, mocked transport
    def refuse(request):
        sent.append(str(request.url))
        raise httpx.ConnectError('mocked: connection refused', request=request)
    with geodes_network(refuse):
        r, body = call('post', '/api/imagery-plan', json=REQUEST)
    ev.log(f'S1 ConnectError -> HTTP {r.status_code} {body}; mocked network calls={len(sent)}')
    ev.check('S1 Mất kết nối GEODES: /api/imagery-plan trả 502 có thông báo thân thiện', r.status_code == 502 and 'temporarily unavailable' in str(body), '502 + thông báo', f'{r.status_code} {body}')
    ev.check('S1 Request thực sự đi qua lớp mạng (mock được gọi)', len(sent) >= 1, '>=1 lần gọi', len(sent))

    # S2: catalogue times out
    def timeout(request):
        raise httpx.ReadTimeout('mocked: read timeout', request=request)
    with geodes_network(timeout):
        r, body = call('post', '/api/imagery-plan', json=REQUEST)
    ev.check('S2 GEODES timeout: trả 502, không treo, không 500', r.status_code == 502, '502', r.status_code)

    # S3: catalogue answers HTTP 503
    def unavailable(request):
        return httpx.Response(503, text='Service Unavailable')
    with geodes_network(unavailable):
        r, body = call('post', '/api/imagery-plan', json=REQUEST)
    ev.check('S3 GEODES trả HTTP 503: hệ thống trả 502 cho client', r.status_code == 502, '502', r.status_code)

    # S4: no API key configured -> analysis refused before any job is created
    before = set(p.name for p in api.RESULTS.iterdir())
    with mock.patch.dict(os.environ, {'GEODES_API_KEY': ''}):
        r, body = call('post', '/api/analyses', json=REQUEST)
    created = set(p.name for p in api.RESULTS.iterdir()) - before
    ev.check('S4 Thiếu GEODES_API_KEY: POST /api/analyses trả 503, không tạo job', r.status_code == 503 and not created, '503 + 0 job', f'{r.status_code}, {len(created)} job')

    # S5: imagery download fails mid-job with a known imagery error
    with mock.patch.object(api.app.state.imagery, 'prepare', side_effect=ImageryError('No usable Sentinel-2 scenes for this season (mocked).')):
        r, body = call('post', '/api/analyses', json=REQUEST)
        status = c.wait_job(client, body['id'], timeout=30, interval=.2) if r.status_code == 202 else {}
    exchanges.append(dict(method='GET', url=f'/api/analyses/{body.get("id")}', status=200, elapsed_ms='-', response=status))
    ev.check('S5 Lỗi ImageryError giữa chừng: job kết thúc status=error kèm thông báo rõ ràng', status.get('status') == 'error' and 'mocked' in status.get('message', ''), 'error + thông báo', status.get('status'))

    # S6: unexpected network exception mid-job -> generic message, no internal detail leaked
    with mock.patch.object(api.app.state.imagery, 'prepare', side_effect=httpx.RemoteProtocolError('secret-internal-host:9999 reset')):
        r, body = call('post', '/api/analyses', json=REQUEST)
        status = c.wait_job(client, body['id'], timeout=30, interval=.2) if r.status_code == 202 else {}
    exchanges.append(dict(method='GET', url=f'/api/analyses/{body.get("id")}', status=200, elapsed_ms='-', response=status))
    leaked = 'secret-internal-host' in json.dumps(status)
    ev.check('S6 Lỗi mạng bất ngờ: job=error, thông báo chung, không lộ chi tiết nội bộ', status.get('status') == 'error' and not leaked, 'error, không lộ host', f"{status.get('status')}, leaked={leaked}")

    # S7: service remains healthy and the queue is drained afterwards
    r, body = call('get', '/api/health')
    ev.check('S7 Sau các lỗi, /api/health vẫn 200 và hàng đợi rỗng', r.status_code == 200 and not api.app.state.pending, '200, pending=0', f'{r.status_code}, pending={len(api.app.state.pending)}')

ev.save('request.json', [dict(method=x['method'], url=x['url'], body=x.get('body')) for x in exchanges])
ev.save('response.json', exchanges)
c.request_response_png(ev, exchanges)
ev.finish(expected='Khi dịch vụ ảnh vệ tinh lỗi (mất kết nối, timeout, HTTP 503, thiếu khóa API, lỗi giữa job), API trả mã lỗi phù hợp (502/503) hoặc job chuyển status=error, không có HTTP 500, không lộ chi tiết nội bộ, dịch vụ vẫn hoạt động.',
          actual='; '.join(f"{x['check'].split(':')[0]}={'OK' if x['passed'] else 'LỖI'}" for x in ev.checks),
          notes='Mock test: không có dữ liệu GEODES thật được tải; mã của GeodesProvider chạy thật, chỉ lớp httpx (S1–S3) hoặc phương thức prepare (S5–S6) bị thay thế bằng unittest.mock. Production chạy chế độ prepared (offline), không phụ thuộc GEODES lúc chạy.')
