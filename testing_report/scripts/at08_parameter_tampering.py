import scripts.common as c
import time
from scripts.at01_malformed_input import begin, finish, run, client_local, body_for, send, api_artifacts, cancel

def main():
    ev=begin('AT08','Can thiệp tham số và định danh tài nguyên','security',
             'Patch training ẩn bị từ chối 422 theo chính sách cách ly tập test; patch sai/season sai bị 422; traversal/UUID không chuẩn bị 404; include sai 422; tọa độ sai 422; client khác không được hủy job (401/403).',
             'Đánh giá kiểm tra định danh, truy cập dữ liệu ẩn và ranh giới quyền sở hữu job.',
             'resolve, job_directory, download, pixel, DELETE analyses',
             'Dùng một job hoàn tất để tránh nhầm 409 với validation download; tạo job khác và thử DELETE từ client B không có cookie/token.',
             'ID training/nonexistent/negative, season giả, traversal, UUID viết hoa, format/include giả, lat/lng sai.',
             'Nếu cần cách ly training thì kiểm tra split khi resolve explicit ID; thêm xác thực và quyền sở hữu job nếu triển khai đa người dùng; giữ UUID/path validation.',
             dict(max_requests=120,max_concurrency=1,max_seconds=120))
    client,module=client_local(); exchanges=[]; observations=[]
    with client:
        valid=body_for(module); catalog=send(client,'GET','/api/catalog'); exchanges.append(catalog)
        advertised=[p['id'] for p in catalog['response']['patches']]
        ev.check('catalog ẩn training',10000 not in advertised,'không có 10000',10000 in advertised)
        variants=[('training 10000',body_for(module,10000)),('patch không tồn tại',{**valid,'patch_id':999999999}),('patch âm',{**valid,'patch_id':-1}),('season giả',{**valid,'season':'../../weights/best.pth'}),('season tương lai',{**valid,'season':'2099–2100'})]
        for name,body in variants:
            x=send(client,'POST','/api/analyses',body); exchanges.append(x); ev.check(name+' bị chặn',x['status']==422,422,x['status']); observations.append(dict(case=name,status=x['status']))
            if x['status']==202: cancel(client,x['response']['id'],exchanges)
        x=send(client,'POST','/api/analyses',valid); exchanges.append(x); ev.check('job kiểm soát được tạo',x['status']==202,202,x['status']); job=x['response']['id']
        status=None
        for _ in range(60):
            x=send(client,'GET','/api/analyses/'+job); exchanges.append(x); status=x['response']
            if status.get('status') in ['done','error','cancelled']: break
            time.sleep(.25)
        ev.check('job kiểm soát hoàn tất',status.get('status')=='done','done',status.get('status'))
        paths=[('/api/analyses/../weights/best.pth',404),('/api/analyses/%2e%2e%2fweights%2fbest.pth',404),
               ('/api/analyses/'+job.upper(),404),('/api/analyses/'+job+'/download/..%2F..%2Fweights%2Fbest.pth',404),
               ('/api/analyses/'+job+'/download/zip?include=../../weights/best.pth',422),
               ('/api/analyses/'+job+'/download/zip?include=tif,secret',422),
               ('/api/analyses/'+job+'/pixel?lat=91&lng=181',422),('/api/analyses/'+job+'/pixel?lat=-91&lng=-181',422)]
        for path,expected in paths:
            x=send(client,'GET',path); exchanges.append(x); ev.check(path,x['status']==expected,expected,x['status']); observations.append(dict(case=path,status=x['status']))
        # 25 windows keep this job active while client B submits cancellation.
        x=send(client,'POST','/api/analyses',body_for(module,size=120)); exchanges.append(x); other=x['response']['id']
        second,_=client_local()
        try: x=send(second,'DELETE','/api/analyses/'+other)
        finally: second.close()
        exchanges.append(x); ev.check('client khác không được hủy job',x['status'] in [401,403],'401/403',x['status']); observations.append(dict(case='DELETE client B',status=x['status'],response=x['response']))
        cancel(client,other,exchanges)
    api_artifacts(ev,exchanges)
    finish(ev,'Training explicit ID và DELETE từ client B: '+str([o for o in observations if o['case'] in ['training 10000','DELETE client B']])+'.',
           notes='Không có khái niệm chủ job/xác thực trong thiết kế hiện tại; DELETE từ client B là quan sát thiết kế đa người dùng, không chứng minh đoán được UUIDv4. Chính sách cách ly training là tiêu chí đánh giá đặt trước, không phải cam kết đã công bố của ứng dụng.',
           observations=observations,impact='Trung bình: UUIDv4 khó đoán nhưng ai biết URL job có thể hủy; patch training ẩn vẫn có thể được chọn bằng ID.')
if __name__=='__main__': run(main)
