import scripts.common as c
import time
import os
import re
import numpy as np
from scripts.at01_malformed_input import begin, finish, run, client_local, body_for, send, api_artifacts, cancel, rss_mb, plot_series

def main():
    ev=begin('AT09','Tiêu thụ tài nguyên vùng Normandy có giới hạn','security/availability',
             'Kế hoạch vùng Normandy có >1000 cửa sổ; job được nhận; trong 60 giây health luôn 200 và p95 <1000 ms, RSS tăng <1024 MiB; hủy chuyển cancelled trong 15 giây.',
             'Đo chi phí một job lớn và khả năng phản hồi/hủy trong lúc CPU suy luận.',
             'imagery-plan, worker TSViT, health và DELETE analyses',
             'Lập kế hoạch toàn mosaic 900010; chạy thật tối đa 60 giây với 13 mẫu RSS/CPU/health; hủy và thăm dò tối đa 30 lần.',
             'Polygon 2304x2304 px từ catalog thật; một job duy nhất, không gọi production.',
             'Áp quota cửa sổ/diện tích/thời gian theo người dùng; giới hạn mỗi job và lập lịch công bằng ngoài giới hạn 4 pending.',
             dict(max_requests=65,max_concurrency=1,job_run_seconds=60,max_seconds=110,max_jobs=1))
    client,module=client_local(); exchanges=[]; samples=[]
    with client:
        body=body_for(module,900010,size=2304)
        plan=send(client,'POST','/api/imagery-plan',body); exchanges.append(plan)
        ev.check('plan thành công',plan['status']==200,200,plan['status']); windows=plan['response'].get('windows',0)
        ev.check('vùng có >1000 cửa sổ',windows>1000,'>1000',windows)
        baseline_rss=rss_mb(); start_cpu=os.times(); started=time.perf_counter()
        x=send(client,'POST','/api/analyses',body); exchanges.append(x); ev.check('job lớn được nhận',x['status']==202,202,x['status']); job=x['response']['id']
        prev_wall=time.perf_counter(); prev_cpu=os.times(); deadline=started+60
        while True:
            health=send(client,'GET','/api/health'); exchanges.append(health)
            status=send(client,'GET','/api/analyses/'+job); exchanges.append(status)
            now=time.perf_counter(); cpu=os.times(); match=re.search(r'(\d+) / (\d+) windows',status['response'].get('message',''))
            samples.append(dict(seconds=now-started,rss_mb=rss_mb(),cpu_percent=100*((cpu.user+cpu.system)-(prev_cpu.user+prev_cpu.system))/(now-prev_wall),
                                health_status=health['status'],health_latency_ms=health['elapsed_ms'],job_status=status['response'].get('status'),progress=status['response'].get('progress'),
                                completed_windows=int(match.group(1)) if match else 0,message=status['response'].get('message')))
            ev.log(str(samples[-1])); prev_wall=now; prev_cpu=cpu
            if now>=deadline or status['response'].get('status') in ['done','error','cancelled']: break
            time.sleep(min(5,max(0,deadline-now)))
        at_cancel=time.perf_counter(); cancel(client,job,exchanges)
        final={}
        for _ in range(30):
            x=send(client,'GET','/api/analyses/'+job); exchanges.append(x); final=x['response']
            if final.get('status') in ['cancelled','done','error']: break
            time.sleep(.5)
        cancel_latency=time.perf_counter()-at_cancel
        h=send(client,'GET','/api/health'); exchanges.append(h)
        lat=[s['health_latency_ms'] for s in samples]; max_rss=max(s['rss_mb'] for s in samples)
        ev.check('health luôn 200',all(s['health_status']==200 for s in samples) and h['status']==200,'tất cả 200',[s['health_status'] for s in samples])
        ev.check('health p95 <1000 ms',np.percentile(lat,95)<1000,'<1000',float(np.percentile(lat,95)))
        ev.check('RSS tăng <1024 MiB',max_rss-baseline_rss<1024,'<1024',max_rss-baseline_rss)
        ev.check('job chuyển cancelled',final.get('status')=='cancelled','cancelled',final.get('status'))
        ev.check('hủy trong 15 giây',cancel_latency<15,'<15',cancel_latency)
    completed=max(s['completed_windows'] for s in samples); duration=samples[-1]['seconds']
    estimated=windows*duration/completed if completed else None
    api_artifacts(ev,exchanges); ev.save('resource_samples.json',samples)
    plot_series(ev,'resources.png',{'RSS MiB':([s['seconds'] for s in samples],[s['rss_mb'] for s in samples]),'CPU % (100=1 lõi)':([s['seconds'] for s in samples],[s['cpu_percent'] for s in samples])},'RSS / CPU','Giây')
    plot_series(ev,'health_latency.png',{'health ms':([s['seconds'] for s in samples],lat)},'Độ trễ (ms)','Giây')
    finish(ev,f'{windows} cửa sổ; đã xử lý {completed} trong {duration:.1f}s; trạng thái cuối {final.get("status")}; hủy {cancel_latency:.3f}s.',
           notes='Thư mục kết quả riêng theo helper chung đã được coordinator cập nhật để tránh tiến trình kiểm thử khác đánh dấu job là restart. Thời gian toàn vùng là NGOẠI SUY tuyến tính từ số cửa sổ trong message, gồm overhead khởi tạo; không phải lần chạy hoàn chỉnh. RSS/CPU là cả tiến trình TestClient, CPU 100% tương ứng một lõi. Hàng đợi giới hạn 4 nhưng không có quota cửa sổ mỗi job.',
           windows=windows,completed_windows=completed,observed_seconds=duration,estimated_full_run_seconds_extrapolated=estimated,health_p95_ms=float(np.percentile(lat,95)),
           rss_baseline_mb=baseline_rss,rss_peak_sampled_mb=max_rss,cancel_latency_seconds=cancel_latency,final_job=final,samples=samples,
           impact='Cao: một yêu cầu hợp lệ có thể chiếm worker duy nhất hàng chục phút; phép thử cho thấy phản hồi health/hủy trong khoảng đo, không chứng minh chống DoS dài hạn.')
if __name__=='__main__': run(main)
