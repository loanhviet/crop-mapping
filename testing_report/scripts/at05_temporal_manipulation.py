import scripts.common as c
import numpy as np
from inference import preprocess
from scripts.at01_malformed_input import begin, finish, run, model_assets, scores, plot_series

def main():
    ev=begin('AT05','Thao túng chuỗi thời gian và ngày quan sát','adversarial/robustness',
             'Accuracy mỗi biến thể thay thời gian không giảm quá 5 điểm phần trăm; đảo cả ảnh và DOY là đối chứng bất biến; DOY 0/366 bị ValueError.',
             'Đánh giá ảnh hưởng việc ghép sai ảnh-ngày và thiếu đa dạng thời gian trên toàn patch test.',
             'PreparedProvider, preprocess, TSViT',
             'Chạy đủ 25 cửa sổ 24x24 trên 10003, đảo/shuffle ảnh, đảo cặp, dịch DOY ±30/±60 theo modulo 365 và lặp frame đầu.',
             'Ảnh thật cùng GT, thay đổi trật tự hoặc ngày; seed 20261114.',
             'Kiểm tra lịch thu nhận và provenance; cảnh báo chuỗi lặp; kiểm tra tính nhất quán ảnh-ngày.',
             dict(max_windows=25,max_model_forwards=225,max_seconds=540,seed=20261114))
    engine,provider,truth=model_assets(); rng=np.random.default_rng(20261114)
    names=['clean','reverse_images','shuffle_images','reverse_pairs','doy_-60','doy_-30','doy_30','doy_60','duplicate_first']
    predictions={name:np.zeros((120,120),np.uint8) for name in names}; permutations=[]
    ev.save('input.json',dict(patch_id=10003,windows=25,variants=names,seed=20261114,checkpoint=engine.sha256,
                             ground_truth='TARGET channel 0, top-left 120x120; void=19; giữ background'))
    for row in range(0,120,24):
        for col in range(0,120,24):
            image=provider.window(10003,row,col); dates=np.asarray(provider.window_doy(10003,row,col)); order=rng.permutation(len(image)); permutations.append(order.tolist())
            variants={'clean':(image,dates),'reverse_images':(image[::-1],dates),'shuffle_images':(image[order],dates),
                      'reverse_pairs':(image[::-1],dates[::-1]),'duplicate_first':(np.repeat(image[:1],len(image),axis=0),dates)}
            for delta in [-60,-30,30,60]: variants['doy_'+str(delta)]=(image,((dates-1+delta)%365)+1)
            for name,(x,doy) in variants.items():
                labels,_=engine.predict(x,doy); predictions[name][row:row+24,col:col+24]=labels
        ev.log(f'Hoàn tất hàng cửa sổ {row//24+1}/5')
    values={name:scores(truth,pred) for name,pred in predictions.items()}; baseline=values['clean']['accuracy']
    for name,value in values.items():
        if name=='clean': continue
        drop=baseline-value['accuracy']; value['accuracy_drop']=drop
        if name=='reverse_pairs':
            change=float((predictions[name]!=predictions['clean']).mean()); value['prediction_change_fraction']=change
            ev.check('đảo cặp ảnh-ngày bất biến nhãn',change<=.001,'<=0.001',change)
        else: ev.check(name+' accuracy giảm <=5pp',drop<=.05,'<=0.05',drop)
    image=provider.window(10003,0,0); dates=np.asarray(provider.window_doy(10003,0,0)); rejected=[]
    for invalid in [0,366]:
        modified=dates.copy(); modified[0]=invalid
        try: preprocess(image,modified); caught=False
        except ValueError: caught=True
        rejected.append(dict(doy=invalid,rejected=caught)); ev.check('DOY '+str(invalid)+' bị chặn',caught,'ValueError',caught)
    ev.save('output.json',dict(metrics=values,doy_validation=rejected,permutations=permutations,predictions={k:v.tolist() for k,v in predictions.items()}))
    plot_series(ev,'temporal_accuracy.png',{'accuracy':(names,[values[n]['accuracy'] for n in names])},'Accuracy')
    finish(ev,'Accuracy theo biến thể: '+', '.join(n+'='+format(values[n]['accuracy'],'.4f') for n in names)+'.',
           notes='API không nhận trường DOY độc lập: phép kiểm ngày ngoài miền chạy tại preprocess, đúng ranh giới dữ liệu mà job API sử dụng. Đảo ảnh cùng DOY giữ cặp làm đối chứng; đảo riêng ảnh phá ghép ngày. Đây là kiểm tra đối kháng và độ bền, không phải bypass xác thực.',
           results=values,doy_validation=rejected,impact='Trung bình: lịch thu nhận sai hoặc frame lặp có thể làm lệch dự đoán trên cùng khu vực.')
if __name__=='__main__': run(main)
