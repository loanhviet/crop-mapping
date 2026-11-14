import scripts.common as c
import time
from unittest.mock import patch
import numpy as np
from inference import preprocess
from scripts.at01_malformed_input import begin, finish, run, model_assets, client_local, body_for, send, api_artifacts, plot_series

def main():
    ev=begin('AT10','Giá trị số và kích thước tensor không hợp lệ','security/robustness',
             'NaN/±Inf, int16 cực trị, reflectance âm, kích thước sai, T=0 và DOY lệch độ dài bị ValueError sạch; T=200 được cắt đúng 60; job chứa NaN kết thúc error với thông báo chung.',
             'Kiểm tra ranh giới số học từ preprocess đến job API và hành vi cắt chuỗi.', 'preprocess, Engine.predict, run_analysis exception handler',
             'Chạy từng tensor qua preprocess và Engine.predict; đối chiếu T=200 với 60 frame đầu; mock riêng provider.window bằng NaN trong một job thật.',
             'NaN, +Inf, -Inf, -32768/32767, -1; 23x24, 0/200 frame, DOY lệch độ dài.',
             'Thêm kiểm tra T>=1 và miền reflectance theo hợp đồng dữ liệu/QA; giữ kiểm tra hữu hạn và thông báo lỗi job chung.',
             dict(max_model_calls=24,max_api_requests=65,max_concurrency=1,max_seconds=120))
    engine,provider,_=model_assets(); image=provider.window(10003,0,0).astype(np.float32); dates=np.array(provider.window_doy(10003,0,0))
    cases=[]
    for name,value in [('NaN',np.nan),('+Inf',np.inf),('-Inf',-np.inf),('int16_min',-32768),('int16_max',32767),('negative',-1)]:
        x=image.copy(); x[0,0,0,0]=value; cases.append((name,x,dates))
    cases += [('shape_23x24',image[:,:,:23,:],dates),('T_zero',image[:0],dates[:0]),('DOY_length_mismatch',image,dates[:-1])]
    outputs=[]
    ev.save('input.json',dict(patch_id=10003,window=[0,0],checkpoint=engine.sha256,cases=[dict(name=n,shape=list(x.shape),doy_len=len(d)) for n,x,d in cases],long_sequence_frames=200,invalid_values=['NaN','+Inf','-Inf',-32768,32767,-1]))
    for name,x,doy in cases:
        for component,fn in [('preprocess',preprocess),('Engine.predict',engine.predict)]:
            item=dict(case=name,component=component)
            try:
                result=fn(x,doy); item.update(rejected=False,output_finite=bool(all(np.isfinite(v).all() for v in result)) if isinstance(result,tuple) else bool(np.isfinite(result.numpy()).all()))
            except ValueError as exc: item.update(rejected=True,exception='ValueError',message=str(exc))
            except Exception as exc: item.update(rejected=False,exception=type(exc).__name__,message=str(exc))
            outputs.append(item); ev.check(name+' '+component+' ValueError',item['rejected'],'ValueError',item)
            if 'output_finite' in item: ev.check(name+' '+component+' hữu hạn',item['output_finite'],True,item['output_finite'])
    long=np.repeat(image[:1],200,axis=0); long_doy=np.resize(dates,200)
    full=preprocess(long,long_doy); first=preprocess(long[:60],long_doy[:60]); equal=bool(np.array_equal(full.numpy(),first.numpy()))
    pred,confidence=engine.predict(long,long_doy); reference,ref_conf=engine.predict(long[:60],long_doy[:60])
    same=bool(np.array_equal(pred,reference) and np.array_equal(confidence,ref_conf))
    ev.check('T=200 cắt đúng 60 ở preprocess',equal,True,equal); ev.check('T=200 predict như 60 đầu',same,True,same)
    exchanges=[]; client,module=client_local()
    with client:
        with patch.object(module.app.state.provider,'window',return_value=np.full_like(image,np.nan)):
            x=send(client,'POST','/api/analyses',body_for(module)); exchanges.append(x); job=x['response']['id']; final={}
            for _ in range(60):
                x=send(client,'GET','/api/analyses/'+job); exchanges.append(x); final=x['response']
                if final.get('status') in ['error','done','cancelled']: break
                time.sleep(.1)
        ev.check('job NaN chuyển error',final.get('status')=='error','error',final.get('status'))
        generic='Analysis failed. Please retry or check the server log.'
        ev.check('job NaN dùng thông báo chung',final.get('message')==generic,generic,final.get('message'))
        ev.check('job không lộ stack trace','Traceback' not in str(final),False,'Traceback' in str(final))
        h=send(client,'GET','/api/health'); exchanges.append(h); ev.check('health sau lỗi',h['status']==200,200,h['status'])
    api_artifacts(ev,exchanges); ev.save('output.json',dict(cases=outputs,truncation_preprocess_equal=equal,truncation_predict_equal=same,api_nan_job=final))
    plot_series(ev,'numerical_rejections.png',{'bị ValueError':([x['case']+' '+x['component'] for x in outputs],[int(x['rejected']) for x in outputs])},'1=bị từ chối, 0=được nhận')
    finish(ev,str(sum(x['rejected'] for x in outputs))+'/'+str(len(outputs))+' phép thử tensor bị ValueError; T=200 cắt đúng='+str(same)+'; job NaN='+str(final.get('status'))+'.',
           notes='NaN imagery được mock tại provider của job cục bộ; các phần còn lại gồm model thật. Reflectance âm/cực trị hữu hạn không được kiểm tra miền ở preprocess hiện tại; tiêu chí từ chối đã đặt trước để phát hiện khoảng trống này. API không cho client gửi tensor trực tiếp.',
           cases=outputs,truncation_equal=same,api_nan_job=final,impact='Trung bình: tensor hữu hạn nhưng vô nghĩa và chuỗi rỗng có thể tạo dự đoán; NaN/Inf cần bị chặn và lỗi job không được lộ chi tiết.')
if __name__=='__main__': run(main)
