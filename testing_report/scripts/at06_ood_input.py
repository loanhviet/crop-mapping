import scripts.common as c
import numpy as np
from scripts.at01_malformed_input import begin, finish, run, model_assets, plot_series

def main():
    ev=begin('AT06','Đầu vào ngoài phân bố','robustness',
             'Ba đầu vào rác zero/cloud/noise có confidence softmax trung bình <=0.60 và tỷ lệ pixel confidence >=0.90 <=10%; ghi nhận riêng ảnh scale và đổi band.',
             'Kiểm tra mô hình có đưa dự đoán tự tin trên ảnh vô nghĩa khi không có cổng OOD.', 'preprocess và Engine.predict',
             '3 cửa sổ thật 10003 làm đối chứng; tạo zeros, 10000, uniform[0,10000], nhân 3, đảo thứ tự 10 band.',
             'Tensor ảnh tổng hợp cùng hình dạng và lịch thật; seed 20261114.',
             'Bổ sung QA mây/reflectance, OOD detector, hiệu chuẩn confidence và quyền từ chối suy luận.',
             dict(max_windows=3,max_model_forwards=18,max_seconds=120,seed=20261114))
    engine,provider,_=model_assets(); rng=np.random.default_rng(20261114); results={}; distributions={}; outputs=[]
    positions=[(0,0),(48,48),(96,96)]
    ev.save('input.json',dict(patch_id=10003,positions=positions,seed=20261114,uniform_range=[0,10000],high_constant=10000,scale=3,band_order=list(range(9,-1,-1)),checkpoint=engine.sha256))
    for row,col in positions:
        image=provider.window(10003,row,col).astype(np.float32); dates=provider.window_doy(10003,row,col)
        variants={'real':image,'zeros':np.zeros_like(image),'cloud10000':np.full_like(image,10000),
                  'uniform_noise':rng.uniform(0,10000,image.shape).astype(np.float32),'scaled_x3':image*3,'band_reversed':image[:,::-1]}
        for name,x in variants.items():
            labels,confidence=engine.predict(x,dates)
            results.setdefault(name,[]).append(confidence.ravel()); distributions.setdefault(name,np.zeros(19,int)); distributions[name]+=np.bincount(labels.ravel(),minlength=19)
            outputs.append(dict(window=[row,col],variant=name,mean_confidence=float(confidence.mean()),labels=labels.tolist()))
    metrics={}
    for name,chunks in results.items():
        conf=np.concatenate(chunks)
        metrics[name]=dict(mean_confidence=float(conf.mean()),high_confidence_fraction=float((conf>=.9).mean()),
                           distribution=(distributions[name]/distributions[name].sum()).tolist(),dominant_class=int(distributions[name].argmax()))
        ev.log(name+': '+str(metrics[name]))
        if name in ['zeros','cloud10000','uniform_noise']:
            ev.check(name+' confidence thấp',conf.mean()<=.6,'<=0.60',float(conf.mean()))
            ev.check(name+' ít pixel quá tự tin',(conf>=.9).mean()<=.1,'<=0.10',float((conf>=.9).mean()))
    ev.save('output.json',dict(metrics=metrics,predictions=outputs))
    plot_series(ev,'ood_confidence.png',{'mean confidence':(list(metrics),[v['mean_confidence'] for v in metrics.values()]),'fraction >=0.9':(list(metrics),[v['high_confidence_fraction'] for v in metrics.values()])},'Tỷ lệ / confidence')
    import matplotlib.pyplot as plt
    fig,ax=plt.subplots(figsize=(11,5)); im=ax.imshow([v['distribution'] for v in metrics.values()],vmin=0,vmax=1,aspect='auto'); ax.set_yticks(range(len(metrics)),list(metrics)); ax.set_xticks(range(19)); ax.set(xlabel='Lớp dự đoán',title='Phân bố lớp thực đo; không phải độ chính xác'); fig.colorbar(im,ax=ax); fig.tight_layout(); fig.savefig(ev.dir/'class_distribution.png',dpi=130); plt.close(fig)
    finish(ev,'Confidence trung bình: '+', '.join(k+'='+format(v['mean_confidence'],'.3f') for k,v in metrics.items())+'.',
           notes='Ảnh tổng hợp KHÔNG có ground truth; không gọi confidence là accuracy. Không có nhánh từ chối OOD trong Engine.predict; kết quả chỉ chứng minh hành vi checkpoint trên các đầu vào đã thử.',
           results=metrics,impact='Trung bình: ảnh rác có thể nhận nhãn cây trồng tự tin và gây hiểu nhầm nếu dữ liệu đầu vào vượt qua QA.')
if __name__=='__main__': run(main)
