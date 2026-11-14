import scripts.common as c
import copy
import json
from scripts.at01_malformed_input import begin, finish, run, client_local, body_for, send, api_artifacts, cancel, RESULTS

def main():
    ev=begin('AT07','Tấn công GeoJSON không hợp lệ','security',
             'Mọi hình học sai hoặc không hỗ trợ bị 422 trên cả imagery-plan và analyses, không 500, không tạo job.',
             'Kiểm tra cấu trúc, tính hữu hạn, topology và giới hạn phủ của polygon.', 'AnalysisRequest.validate_polygon và selection_mask',
             'Gửi 13 biến thể trên 2 endpoint; chụp mã HTTP và thư mục job; hủy mọi job ngoài dự kiến.',
             'Ring hở/3 điểm, MultiPolygon, lỗ, NaN/±Infinity, tọa độ ngoài miền/3D, bow-tie, diện tích 0, ngoài phủ, nửa địa cầu.',
             'Kiểm tra topology bằng thư viện hình học; từ chối số không hữu hạn trước bước serialize lỗi; chuẩn hóa HTTP 422.',
             dict(max_requests=60,max_concurrency=1,max_seconds=90))
    client,module=client_local(); exchanges=[]; results=[]
    with client:
        valid=body_for(module); geometry=valid['geometry']; ring=geometry['coordinates'][0]; a,b,d,e=ring[:4]
        cases=[]
        def add(name,value): cases.append((name,value))
        add('ring không khép',{'type':'Polygon','coordinates':[ring[:-1]+[[ring[0][0]+1e-5,ring[0][1]]]]})
        add('3 điểm',{'type':'Polygon','coordinates':[[a,b,a]]})
        add('MultiPolygon',{'type':'MultiPolygon','coordinates':[[ring]]})
        add('Polygon có lỗ',{'type':'Polygon','coordinates':[ring,ring]})
        for name,value in [('NaN',float('nan')),('+Infinity',float('inf')),('-Infinity',float('-inf'))]:
            g=copy.deepcopy(geometry); g['coordinates'][0][1][0]=value; add(name,g)
        g=copy.deepcopy(geometry); g['coordinates'][0][1]=[181,91]; add('lon181 lat91',g)
        add('tọa độ 3D',{'type':'Polygon','coordinates':[[point+[10] for point in ring]]})
        add('tự cắt bow-tie',{'type':'Polygon','coordinates':[[a,d,b,e,a]]})
        add('diện tích 0',{'type':'Polygon','coordinates':[[a,a,a,a]]})
        add('ngoài vùng phủ',{'type':'Polygon','coordinates':[[[0,0],[.01,0],[.01,.01],[0,.01],[0,0]]]})
        add('nửa địa cầu',{'type':'Polygon','coordinates':[[[-90,-80],[90,-80],[90,80],[-90,80],[-90,-80]]]})
        for name,g in cases:
            for endpoint in ['/api/imagery-plan','/api/analyses']:
                before=set(RESULTS.iterdir()); x=send(client,'POST',endpoint,raw=json.dumps({**valid,'geometry':g}),headers={'content-type':'application/json'}); exchanges.append(x)
                created=[p.name for p in set(RESULTS.iterdir())-before]; results.append(dict(case=name,endpoint=endpoint,status=x['status'],created_job_ids=created))
                ev.check(name+' '+endpoint+' 422',x['status']==422,422,x['status'])
                ev.check(name+' '+endpoint+' không tạo job',not created,0,len(created))
                if x['status']==202: cancel(client,x['response']['id'],exchanges)
        h=send(client,'GET','/api/health'); exchanges.append(h); ev.check('dịch vụ còn sống',h['status']==200,200,h['status'])
    api_artifacts(ev,exchanges)
    finish(ev,'Có '+str(sum(r['status']!=422 for r in results))+' / '+str(len(results))+' trường hợp không trả 422.',
           notes='Bow-tie thử hoàn toàn bên trong patch thật; chỉ quan sát cục bộ. NaN/Infinity được gửi bằng raw JSON ngoài chuẩn để kiểm tra parser và đường lỗi.',
           cases=results,impact='Trung bình: lỗi 500 do đường serialize hoặc polygon tự cắt được nhận có thể gây kết quả bất định và tốn job.')
if __name__=='__main__': run(main)
