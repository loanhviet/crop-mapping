import scripts.common as c
import json
import math
import hashlib
from scripts.at01_malformed_input import begin, finish, run, client_local, body_for, send, api_artifacts, rss_mb, plot_series

def main():
    ev=begin('AT02','Tấn công payload quá lớn','security',
             'Payload 101/100000 đỉnh, JSON 6 MiB và JSON sâu 1100 mức bị từ chối bằng 422/413; dịch vụ còn phản hồi.',
             'Đo khả năng chặn tiêu thụ tài nguyên ở tầng body và cấu trúc.', 'HTTP parser, Pydantic, imagery-plan',
             'Gửi tuần tự 4 yêu cầu có giới hạn, đo thời gian và RSS trước/sau.',
             '101 đỉnh, 100000 đỉnh, trường thừa chứa 6 MiB ký tự, JSON lồng sâu 1100.',
             'Giới hạn byte body tại ứng dụng/proxy; chặn trường thừa và độ sâu JSON; trả 413/422 nhất quán.',
             dict(max_requests=5,max_concurrency=1,max_body_bytes=20*1024*1024,max_seconds=60))
    client,module=client_local(); exchanges=[]; measured=[]
    with client:
        valid=body_for(module)
        raws=[]
        for count in [101,100000]:
            ring=[[2+0.001*math.cos(2*math.pi*i/(count-1)),49+0.001*math.sin(2*math.pi*i/(count-1))] for i in range(count-1)]
            ring.append(ring[0]); raw=json.dumps({**valid,'geometry':{'type':'Polygon','coordinates':[ring]}})
            raws.append((str(count)+' đỉnh',raw))
        raws.append(('6 MiB JSON hợp lệ + trường thừa',json.dumps({**valid,'padding':'A'*(6*1024*1024)})))
        raws.append(('JSON sâu 1100 mức','{"geometry":'+('['*1100)+'0'+(']'*1100)+'}'))
        for label,raw in raws:
            before=rss_mb(); x=send(client,'POST','/api/imagery-plan',raw=raw,headers={'content-type':'application/json'}); after=rss_mb(); exchanges.append(x)
            m=dict(case=label,bytes=len(raw.encode()),sha256=hashlib.sha256(raw.encode()).hexdigest(),status=x['status'],latency_ms=x['elapsed_ms'],rss_before_mb=before,rss_after_mb=after,rss_delta_mb=after-before); measured.append(m)
            ev.check(label+' bị từ chối',x['status'] in [422,413],'422/413',x['status'])
            ev.log(json.dumps(m,ensure_ascii=False))
        health=send(client,'GET','/api/health'); exchanges.append(health); ev.check('dịch vụ còn sống',health['status']==200,200,health['status'])
    api_artifacts(ev,exchanges); ev.save('payload_recipes.json',dict(cases=measured,reproduction='Sinh payload theo mã nguồn at02_oversized_payload.py; chỉ lưu prefix trong request.json để tránh nhân bản body lớn.'))
    plot_series(ev,'resources.png',{'RSS delta MiB':([m['case'] for m in measured],[m['rss_delta_mb'] for m in measured])},'MiB')
    finish(ev,'HTTP từng payload: '+str([m['status'] for m in measured])+'.',
           notes='RSS đo trong cùng tiến trình TestClient gồm cả client và server; không phải RSS server độc lập. Không xác minh Caddy hoặc production; giới hạn proxy chỉ là khả năng lý thuyết.',cases=measured,
           body_size_limit_observed=measured[2]['status'] in [413,422])
if __name__=='__main__': run(main)
