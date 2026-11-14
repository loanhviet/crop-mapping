"""AT01 and local-only reusable helpers; run: python -m scripts.at01_malformed_input."""
import scripts.common as c  # MUST be the first project import.
import json
import time
import traceback
from pathlib import Path
import numpy as np

RESULTS = Path(c.os.environ['CROP_RESULTS_DIR'])

def begin(test_id, name, kind, expected, objective, component, method, payload, remediation, limits):
    ev = c.Evidence(test_id, name, kind, 'Local')
    ev.expected = expected
    ev.meta = dict(objective=objective, component=component, method=method,
                   steps=['Chạy từ testing_report bằng Python đã cấp: python -m scripts.' + Path(__import__('sys').argv[0]).stem,
                          'Nạp checkpoint và dữ liệu thật qua scripts.common; chỉ gọi TestClient cục bộ.',
                          'Gửi các đầu vào mô tả trong request.json hoặc input.json và ghi kết quả thực đo.',
                          'Đối chiếu các tiêu chí đã lưu trước khi chạy trong expected.json.'],
                   payload=payload, impact='Trung bình: cần xem kết quả từng phép kiểm và phạm vi cục bộ.',
                   remediation=remediation, limits=limits)
    ev.save('expected.json', dict(expected=expected, type=kind, metrics=ev.meta))
    return ev

def finish(ev, actual, notes='', **metrics):
    return ev.finish(expected=ev.expected, actual=actual, notes=notes, metrics={**ev.meta, **metrics})

def run(main):
    ev = None
    try:
        main()
    except Exception as exc:
        # An unexpected harness failure must never appear as an SUT PASS.
        test_id = Path(__import__('sys').argv[0]).stem[:4].upper()
        directory = c.EVIDENCE / test_id
        path = directory / 'harness_error.txt'
        directory.mkdir(parents=True, exist_ok=True)
        path.write_text(traceback.format_exc())
        expected_path = directory / 'expected.json'
        spec = json.loads(expected_path.read_text()) if expected_path.exists() else {}
        c.render_log(path, directory / 'harness_error.png', 'Lỗi thực thi kịch bản')
        # Preserve partial artifacts instead of Evidence's constructor cleanup.
        ev = object.__new__(c.Evidence)
        ev.id, ev.name, ev.kind, ev.environment = test_id, 'Lỗi thực thi kịch bản', spec.get('type', 'robustness'), 'Local'
        ev.dir, ev.lines, ev.checks, ev.started = directory, [], [], time.time()
        for name in ['input.json', 'output.json']:
            if not (directory / name).exists(): ev.save(name, dict(error=str(exc)))
        ev.finish(expected=spec.get('expected', 'Kịch bản chạy hoàn tất.'), actual='Không hoàn tất: '+str(exc), status='BLOCKED',
                  notes='Lỗi công cụ/kịch bản; xem harness_error.txt, không coi đây là lỗi hệ thống.', metrics=spec.get('metrics', {}))
        raise

def send(client, method, url, body=None, raw=None, headers=None):
    assert url.startswith('/api/'), 'Chỉ cho phép đường dẫn API cục bộ'
    start = time.perf_counter()
    kwargs = dict(headers=headers or {})
    if raw is not None: kwargs['content'] = raw
    elif body is not None: kwargs['json'] = body
    response = client.request(method, url, **kwargs)
    try: value = response.json()
    except ValueError: value = response.text
    return dict(method=method, url=url, body=body if raw is None else dict(raw_prefix=raw[:300], bytes=len(raw.encode())),
                status=response.status_code, elapsed_ms=round((time.perf_counter()-start)*1000, 3), response=value)

def api_artifacts(ev, exchanges):
    ev.save('request.json', [{k:v for k,v in x.items() if k in ('method','url','body')} for x in exchanges])
    ev.save('response.json', [{k:v for k,v in x.items() if k not in ('method','url','body')} for x in exchanges])
    c.request_response_png(ev, exchanges)

def client_local():
    client, module = c.local_client()
    client._transport.raise_server_exceptions = False
    return client, module

def body_for(module, patch_id=10003, row=0, col=0, size=24):
    return dict(patch_id=patch_id, season='2018–2019', geometry=c.window_geometry(module.app.state.provider.get(patch_id), row, col, size))

def cancel(client, job_id, exchanges=None):
    x = send(client, 'DELETE', '/api/analyses/'+job_id)
    if exchanges is not None: exchanges.append(x)
    return x

def rss_mb():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'): return int(line.split()[1])/1024

def plot_series(ev, filename, series, ylabel, xlabel='Biến thể'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11,5))
    for name, (xs, ys) in series.items(): ax.plot(xs, ys, 'o-', label=name)
    ax.set(xlabel=xlabel, ylabel=ylabel, title=ev.id+' — số liệu thực đo cục bộ')
    if series and len(next(iter(series.values()))[0]) > 6 and isinstance(next(iter(series.values()))[0][0], str):
        for tick in ax.get_xticklabels(): tick.set_rotation(40); tick.set_horizontalalignment('right')
    ax.grid(alpha=.25); ax.legend(); fig.tight_layout(); fig.savefig(ev.dir/filename, dpi=130); plt.close(fig)

def model_assets():
    from inference import Engine, PastisProvider
    p = PastisProvider()
    truth = np.load(c.ASSETS/'data/TARGET_10003.npy', allow_pickle=False)[0,:120,:120]
    return Engine(), p, truth

def scores(truth, prediction):
    truth, prediction = np.asarray(truth).ravel(), np.asarray(prediction).ravel()
    valid = truth != 19
    truth, prediction = truth[valid], prediction[valid]
    matrix = np.bincount(truth.astype(int)*19+prediction.astype(int), minlength=361).reshape(19,19)
    intersection = np.diag(matrix); union = matrix.sum(0)+matrix.sum(1)-intersection
    return dict(accuracy=float((truth==prediction).mean()), miou=float((intersection[union>0]/union[union>0]).mean()),
                valid_pixels=int(valid.sum()), confusion=matrix.tolist())

def main():
    ev = begin('AT01', 'Tấn công đầu vào sai cấu trúc', 'security',
               'Mọi đầu vào sai trả 422, không lộ stack trace và không tạo thư mục job.',
               'Đánh giá ranh giới kiểm tra kiểu và cấu trúc yêu cầu.', 'AnalysisRequest và POST /api/analyses',
               'Gửi từng payload sai với TestClient thật và so sánh thư mục kết quả trước/sau.',
               'JSON hỏng, content-type sai, sai kiểu, thiếu trường, trường thừa.',
               'Bật strict cho kiểu dữ liệu và extra=forbid; chuẩn hóa lỗi JSON trước khi xử lý.',
               dict(max_requests=60, max_concurrency=1, max_seconds=60))
    exchanges=[]; results=[]
    client, module = client_local()
    with client:
        valid=body_for(module)
        cases=[('JSON hỏng',None,'{"geometry":',{'content-type':'application/json'}),
               ('content-type sai',None,json.dumps(valid),{'content-type':'text/plain'}),
               ('thiếu geometry',{'patch_id':10003},None,None), ('thiếu toàn bộ',{},None,None)]
        for value in ['polygon', [], 42]: cases.append(('geometry '+type(value).__name__,{**valid,'geometry':value},None,None))
        cases.append(('season số',{**valid,'season':2019},None,None))
        for value in ['10003',10003.0,2**70]: cases.append(('patch_id '+str(value),{**valid,'patch_id':value},None,None))
        cases.append(('trường thừa',{**valid,'admin':True},None,None))
        for label, body, raw, headers in cases:
            before=set(RESULTS.iterdir()); x=send(client,'POST','/api/analyses',body,raw,headers); exchanges.append(x)
            created=sorted(p.name for p in set(RESULTS.iterdir())-before)
            ev.check(label+' trả 422',x['status']==422,422,x['status'])
            ev.check(label+' không tạo job',not created,0,len(created))
            ev.check(label+' không lộ trace','Traceback' not in str(x['response']),False,'Traceback' in str(x['response']))
            results.append(dict(case=label,status=x['status'],created_job_ids=created))
            if x['status']==202: cancel(client,x['response']['id'],exchanges)
    api_artifacts(ev,exchanges)
    finish(ev, 'Có '+str(sum(r['status']!=422 for r in results))+' / '+str(len(results))+' payload sai được chấp nhận hoặc xử lý khác 422.',
           notes='Không gửi yêu cầu ra mạng; các job chấp nhận ngoài dự kiến đều được yêu cầu hủy.', cases=results)

if __name__=='__main__': run(main)
