"""TC10 — Model Inference Failure (Mock): the model or the imagery read fails during a job; a corrupted checkpoint at startup."""
import scripts.common as c
import scripts.ai_common as ai
import json
import shutil
import tempfile
import time
from pathlib import Path
from unittest import mock

import inference

ev = c.Evidence('TC10', 'Model Inference Failure', 'Mock Test', 'Local (mock)')
client, api = c.local_client()
exchanges = []


def call(method, url, **kw):
    t = time.perf_counter()
    r = getattr(client, method)(url, **kw)
    body = r.json() if r.headers.get('content-type', '').startswith('application/json') else r.text[:200]
    exchanges.append(dict(method=method.upper(), url=url, body=kw.get('json'), status=r.status_code,
                          elapsed_ms=round((time.perf_counter() - t) * 1000, 1), response=body))
    return r, body


def job(request):
    r, body = call('post', '/api/analyses', json=request)
    status = c.wait_job(client, body['id'], timeout=120, interval=.2) if r.status_code == 202 else dict(status=f'HTTP {r.status_code}')
    exchanges.append(dict(method='GET', url=f"/api/analyses/{body.get('id')}", status=200, elapsed_ms='-',
                          response={k: status.get(k) for k in ('status', 'message', 'progress')}))
    return status


with client:
    patch = api.app.state.provider.get(10003)
    request = dict(season='2018–2019', geometry=c.window_geometry(patch, 0, 0, 48))  # 4 windows

    # S1: model forward pass raises (e.g. out-of-memory) on the 2nd window
    calls = {'n': 0}
    real_predict = api.app.state.engine.predict
    def flaky(image, doy):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('mocked: CUDA out of memory at /opt/internal/model.py:131')
        return real_predict(image, doy)
    with mock.patch.object(api.app.state.engine, 'predict', side_effect=flaky):
        s1 = job(request)
    leaked = '/opt/internal' in json.dumps(s1) or 'CUDA' in json.dumps(s1)
    ev.check('S1 Exception trong forward pass: job=error, thông báo chung, không lộ stack/đường dẫn', s1['status'] == 'error' and not leaked, 'error, không lộ chi tiết', f"{s1['status']}: {s1.get('message')}")
    job_dir = api.RESULTS / exchanges[-2]['response']['id']
    ev.check('S1 Không ghi file kết quả dở dang (classification.tif)', not (job_dir / 'classification.tif').exists(), 'không có classification.tif', sorted(p.name for p in job_dir.iterdir()))
    r, body = call('get', f"/api/analyses/{job_dir.name}/download/tif")
    ev.check('S1 Tải kết quả của job lỗi bị từ chối 409', r.status_code == 409, '409', r.status_code)

    # S2: model returns corrupted output (wrong shape) -> must not crash the worker
    with mock.patch.object(api.app.state.engine, 'predict', return_value=(None, None)):
        s2 = job(request)
    ev.check('S2 Mô hình trả output hỏng: job=error, worker không chết', s2['status'] == 'error', 'error', s2['status'])

    # S3: imagery read failure (disk / memory-map error)
    with mock.patch.object(api.app.state.provider, 'window', side_effect=OSError('mocked: I/O error reading S2_10003.npy')):
        s3 = job(request)
    ev.check('S3 Lỗi đọc dữ liệu ảnh: job=error', s3['status'] == 'error' and 'I/O' not in s3.get('message', ''), 'error, thông báo chung', f"{s3['status']}: {s3.get('message')}")

    # S4: recovery — real inference works right after the failures (same worker thread, no restart)
    t = time.perf_counter()
    s4 = job(request)
    ev.check('S4 Phục hồi: job thật tiếp theo hoàn tất (done) không cần khởi động lại', s4['status'] == 'done', 'done', f"{s4['status']} sau {time.perf_counter()-t:.1f}s")
    r, body = call('get', '/api/health')
    ev.check('S4 /api/health 200, hàng đợi rỗng', r.status_code == 200 and not api.app.state.pending, '200, pending=0', f'{r.status_code}, pending={len(api.app.state.pending)}')

# S5: corrupted checkpoint (one byte flipped, same size) -> Engine refuses to load, app refuses to start
with tempfile.TemporaryDirectory() as tmp:
    for name in ('best.pth', 'config.yaml'):
        shutil.copy(c.ASSETS / 'weights' / name, Path(tmp) / name)
    raw = bytearray((Path(tmp) / 'best.pth').read_bytes()); raw[len(raw) // 2] ^= 0xFF
    (Path(tmp) / 'best.pth').write_bytes(bytes(raw))
    with mock.patch.object(inference, 'WEIGHTS', Path(tmp)):
        try:
            inference.Engine(); error = None
        except RuntimeError as exc:
            error = str(exc)
        ev.log(f'S5 Engine() with tampered checkpoint -> {error}')
        ev.check('S5 Checkpoint bị sửa 1 byte: Engine từ chối nạp (RuntimeError xác minh SHA-256)', bool(error) and 'verification failed' in error, 'RuntimeError verification failed', error)
        client2, _ = c.local_client()
        try:
            with client2:
                started = True
        except RuntimeError as exc:
            started = False; ev.log(f'S5 app startup aborted: {exc}')
        ev.check('S5 Ứng dụng không khởi động với checkpoint giả mạo', not started, 'startup bị hủy', 'khởi động' if started else 'bị hủy')

ev.save('request.json', [dict(method=x['method'], url=x['url'], body=x.get('body')) for x in exchanges])
ev.save('response.json', exchanges)
c.request_response_png(ev, exchanges)
ev.finish(expected='Lỗi suy luận/đọc dữ liệu làm job chuyển status=error với thông báo chung, không lộ chi tiết nội bộ, không ghi kết quả dở dang; worker phục hồi để chạy job kế tiếp; checkpoint bị sửa đổi bị từ chối ngay khi khởi động.',
          actual='; '.join(f"{x['check'].split(' ')[0]}={'OK' if x['passed'] else 'LỖI'}" for x in ev.checks),
          notes='Mock test: lỗi được tiêm bằng unittest.mock (S1–S3) và checkpoint bản sao bị lật 1 byte (S5). S4 là suy luận thật với checkpoint thật. Checkpoint gốc không bị chỉnh sửa.')
