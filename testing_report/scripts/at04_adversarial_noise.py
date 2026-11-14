import scripts.common as c
import time
import numpy as np
import torch
import torch.nn.functional as F
from inference import preprocess
from scripts.at01_malformed_input import begin, finish, run, model_assets, scores, plot_series

def main():
    ev=begin('AT04','Nhiễu đối kháng FGSM và PGD','adversarial',
             'Ở epsilon <=0.05 trong không gian chuẩn hóa, accuracy và mIoU không giảm quá 5 điểm phần trăm so với ảnh sạch trên cùng pixel hợp lệ.',
             'Định lượng độ nhạy white-box của checkpoint với nhiễu nhỏ và đối chứng ngẫu nhiên cùng chuẩn.',
             'TSViT thật; kênh ảnh chuẩn hóa, giữ nguyên DOY và padding',
             '3 cửa sổ patch test 10003; FGSM và PGD 3 bước ở epsilon 0.01/0.05/0.1; đối chứng Rademacher cùng chuẩn L2 và Linf cho từng nhiễu.',
             'Gradient cross-entropy theo GT, bỏ void=19; chỉ thay 10 kênh phổ của frame thật.',
             'Huấn luyện đối kháng, đánh giá trên nhiều patch và phát hiện đầu vào bất thường trước suy luận.',
             dict(max_windows=3,max_model_forwards=100,max_seconds=540,pgd_steps=3,seed=20261114))
    torch.manual_seed(20261114); rng=np.random.default_rng(20261114)
    engine,provider,truth=model_assets(); model=engine.model
    for parameter in model.parameters(): parameter.requires_grad_(False)
    positions=[(0,0),(48,48),(96,96)]; epsilons=[.01,.05,.1]; rows=[]; all_predictions={}; truths=[]; window_data=[]
    ev.save('input.json',dict(patch_id=10003,positions=positions,epsilons=epsilons,pgd_steps=3,seed=20261114,
                             ground_truth='TARGET_10003.npy channel 0, top-left 120x120; void=19; background=0 included',checkpoint=engine.sha256))
    for row,col in positions:
        image=provider.window(10003,row,col); dates=provider.window_doy(10003,row,col)
        x=preprocess(image,dates)[None]; y=torch.from_numpy(truth[row:row+24,col:col+24].astype(np.int64))[None]
        mask=torch.zeros_like(x); mask[:,:min(len(image),60),:,:,:10]=1
        window_data.append((x,y,mask)); truths.append(y.numpy()[0])
    target=np.stack(truths)
    def evaluate(key, values):
        preds=[]
        with torch.no_grad():
            for value in values: preds.append(model(value).argmax(1)[0].numpy())
        pred=np.stack(preds); all_predictions[key]=pred
        return scores(target,pred)
    baseline=evaluate('clean',[x for x,_,_ in window_data]); ev.log('Ảnh sạch: '+str({k:v for k,v in baseline.items() if k!='confusion'}))
    for eps in epsilons:
        attacks={k:[] for k in ['FGSM','PGD','random_FGSM','random_PGD']}; norms=[]
        for x,y,mask in window_data:
            value=x.clone().requires_grad_(True)
            loss=F.cross_entropy(model(value),y,ignore_index=19)
            grad=torch.autograd.grad(loss,value)[0]
            fgsm=x+eps*grad.sign()*mask
            pgd=x.clone()
            for _ in range(3):
                pgd=pgd.detach().requires_grad_(True)
                loss=F.cross_entropy(model(pgd),y,ignore_index=19)
                grad=torch.autograd.grad(loss,pgd)[0]
                pgd=(x+torch.clamp(pgd+eps/2*grad.sign()*mask-x,-eps,eps)*mask).detach()
            for name,adversarial in [('FGSM',fgsm.detach()),('PGD',pgd)]:
                delta=adversarial-x
                # Retain every absolute element, randomize its sign: exact same L2/Linf norm.
                signs=torch.from_numpy(rng.choice(np.array([-1,1],np.float32),size=tuple(x.shape)))
                random=x+delta.abs()*signs
                attacks[name].append(adversarial); attacks['random_'+name].append(random)
                norms.append(dict(attack=name,linf=float(delta.abs().max()),l2=float(delta.norm()),
                                  random_l2=float((random-x).norm()),random_linf=float((random-x).abs().max())))
        for name,values in attacks.items():
            metric=evaluate(name+'_'+str(eps),values)
            drop=baseline['accuracy']-metric['accuracy']; miou_drop=baseline['miou']-metric['miou']
            rows.append(dict(attack=name,epsilon=eps,**metric,accuracy_drop=drop,miou_drop=miou_drop,norms=[n for n in norms if n['attack']==name.replace('random_','')]))
            ev.log(f'{name} epsilon={eps}: accuracy={metric["accuracy"]:.5f}, mIoU={metric["miou"]:.5f}')
            if name in ['FGSM','PGD'] and eps<=.05:
                ev.check(f'{name} eps={eps} accuracy giảm <=5pp',drop<=.05,'<=0.05',drop)
                ev.check(f'{name} eps={eps} mIoU giảm <=5pp',miou_drop<=.05,'<=0.05',miou_drop)
    ev.save('output.json',dict(baseline=baseline,experiments=rows,predictions={k:v.tolist() for k,v in all_predictions.items()}))
    plot_series(ev,'accuracy_vs_epsilon.png',{name:([0]+epsilons,[baseline['accuracy']]+[r['accuracy'] for r in rows if r['attack']==name]) for name in ['FGSM','PGD','random_FGSM','random_PGD']},'Accuracy','Epsilon (chuẩn hóa)')
    plot_series(ev,'miou_vs_epsilon.png',{name:([0]+epsilons,[baseline['miou']]+[r['miou'] for r in rows if r['attack']==name]) for name in ['FGSM','PGD','random_FGSM','random_PGD']},'mIoU','Epsilon (chuẩn hóa)')
    worst=max(rows,key=lambda r:r['accuracy_drop'])
    finish(ev,f"Accuracy sạch {baseline['accuracy']:.4f}; giảm lớn nhất {worst['accuracy_drop']:.4f} tại {worst['attack']}, epsilon={worst['epsilon']}.",
           notes='Đây là tấn công đối kháng mô hình white-box, không phải lỗ hổng bảo mật API. Chỉ 3 cửa sổ của một patch, không đại diện toàn bộ phân bố. mIoU lấy trung bình lớp có hợp GT/pred >0, gồm background, bỏ void. Không đổi DOY/padding.',
           baseline=baseline,experiments=rows,impact='Cao: nhiễu có gradient có thể làm sai bản đồ cây trồng; kẻ tấn công cần quyền thay ảnh đầu vào hoặc luồng dữ liệu.')
if __name__=='__main__': run(main)
