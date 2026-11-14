import scripts.common as c
import time
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from scripts.at01_malformed_input import begin, finish, run, client_local, body_for, send, api_artifacts, cancel, plot_series

def main():
    ev=begin('AT03','Dồn yêu cầu API có giới hạn','security',
             '200 GET health đều 200 với p95 dưới 1000 ms; đợt 12 POST có 429 khi hàng đợi đủ 4; mọi job được hủy và dịch vụ còn sống.',
             'Kiểm tra tính sẵn sàng và giới hạn hàng đợi khi có đợt tải ngắn.', 'health, analyses, hàng đợi ThreadPoolExecutor',
             '8 luồng gửi tối đa 200 GET rồi 12 POST cửa sổ thật; DELETE và kiểm tra trạng thái tối đa 80 lần.',
             'Đợt tải health và yêu cầu suy luận 24x24 px hợp lệ.',
             'Giữ giới hạn hàng đợi, bổ sung rate limit theo người dùng/IP và giới hạn khối lượng mỗi job.',
             dict(max_requests=310,max_concurrency=8,max_seconds=120,health_requests=200,analysis_requests=12))
    client,module=client_local(); exchanges=[]
    with client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            health=list(pool.map(lambda _:send(client,'GET','/api/health'),range(200)))
        exchanges.extend(health); lat=[x['elapsed_ms'] for x in health]
        ev.check('200 health thành công',all(x['status']==200 for x in health),200,sum(x['status']==200 for x in health))
        ev.check('p95 dưới 1000 ms',np.percentile(lat,95)<1000,'<1000',float(np.percentile(lat,95)))
        body=body_for(module)
        with ThreadPoolExecutor(max_workers=8) as pool:
            post=list(pool.map(lambda _:send(client,'POST','/api/analyses',body),range(12)))
        exchanges.extend(post); ids=[x['response']['id'] for x in post if x['status']==202]
        ev.check('hàng đợi trả 429',any(x['status']==429 for x in post),'>=1',sum(x['status']==429 for x in post))
        ev.check('POST chỉ trả 202/429',all(x['status'] in [202,429] for x in post),'202/429',[x['status'] for x in post])
        for job in ids: cancel(client,job,exchanges)
        final={}; polls=0
        for _ in range(20):
            for job in ids:
                if polls<80 and final.get(job,{}).get('status') not in ['done','error','cancelled']:
                    x=send(client,'GET','/api/analyses/'+job); polls+=1; exchanges.append(x); final[job]=x['response']
            if all(v.get('status') in ['done','error','cancelled'] for v in final.values()) and len(final)==len(ids): break
            time.sleep(.25)
        ev.check('job đã kết thúc sau hủy',all(v.get('status') in ['done','cancelled'] for v in final.values()),'done/cancelled',[v.get('status') for v in final.values()])
        last=send(client,'GET','/api/health'); exchanges.append(last); ev.check('health sau tải',last['status']==200,200,last['status'])
    api_artifacts(ev,exchanges)
    plot_series(ev,'latency.png',{'health':(list(range(1,201)),lat)},'Độ trễ (ms)','Thứ tự yêu cầu')
    finish(ev,f"Health lỗi={sum(x['status']!=200 for x in health)}; POST nhận={len(ids)}, từ chối 429={sum(x['status']==429 for x in post)}.",
           notes='Tải ngắn trong cùng tiến trình, không suy ra thông lượng mạng/production. Đối chiếu mã nguồn giới hạn pending >=4 trước khi tạo job.',
           health_p50_ms=float(np.percentile(lat,50)),health_p95_ms=float(np.percentile(lat,95)),health_errors=sum(x['status']!=200 for x in health),
           post_statuses=[x['status'] for x in post],final_jobs=final,total_requests=len(exchanges))
if __name__=='__main__': run(main)
