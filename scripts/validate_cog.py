"""Evaluate the actual prepared COG time series on its overlap with PASTIS.

Ground truth is used only here for evaluation, never by the web predictor.
The COG and PASTIS calendars differ; this is not a controlled source-only test.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from inference import DATA, Engine, PreparedProvider, write_json


def metrics(truth,prediction,mask):
    valid=mask&(truth<19)
    if not valid.any():raise ValueError('No labeled valid overlap pixels')
    matrix=np.bincount(19*truth[valid].astype(np.int64)+prediction[valid],minlength=19**2).reshape(19,19)
    tp=np.diag(matrix);union=matrix.sum(0)+matrix.sum(1)-tp
    iou=np.divide(tp,union,out=np.zeros(19,float),where=union>0)
    return dict(pixels=int(valid.sum()),accuracy=float(tp.sum()/matrix.sum()),
                miou=float(iou[union>0].mean()),
                class_iou={str(i):float(iou[i]) for i in range(19) if union[i]>0},
                confusion=matrix.tolist(),includes_background=True)


def common_class_metrics(baseline,external):
    """Use the same class set on both sides, including false-positive classes."""
    classes=sorted(set(baseline['class_iou'])|set(external['class_iou']),key=int)
    for result in [baseline,external]:
        result['miou_own_union']=result['miou']
        result['miou']=sum(result['class_iou'].get(i,0) for i in classes)/len(classes)
    return [int(i) for i in classes]


def validate(region_id=900001,reference_id=10003):
    provider=PreparedProvider(DATA)
    region=provider.get(region_id);reference=provider.get(reference_id)
    if region['crs']!=reference['crs']:raise ValueError('Comparison requires the same native CRS')
    delta=((reference['origin'][1]-region['origin'][1])/-10,
           (reference['origin'][0]-region['origin'][0])/10)
    if any(abs(x-round(x))>1e-5 for x in delta):raise ValueError('Comparison grids are not aligned')
    row,col=map(lambda x:int(round(x)),delta)
    h,w=reference['shape']
    if row<0 or col<0 or row+h>region['shape'][0] or col+w>region['shape'][1]:
        raise ValueError('Reference lies outside the prepared region')
    truth=np.load(DATA/f'TARGET_{reference_id}.npy',allow_pickle=False)[0,:h,:w]
    valid=np.asarray(provider.valid_mask(region_id)[row:row+h,col:col+w])
    engine=Engine()
    baseline=np.zeros((h,w),np.uint8);external=np.zeros_like(baseline)
    for r in range(0,h,24):
        for c in range(0,w,24):
            baseline[r:r+24,c:c+24]=engine.predict(provider.window(reference_id,r,c),reference['doy'])[0]
    # Exactly the web's region-wide window grid, including boundary windows.
    for r in range(row//24*24,row+h,24):
        for c in range(col//24*24,col+w,24):
            prediction=engine.predict(provider.window(region_id,r,c),region['doy'])[0]
            top,left=max(r,row),max(c,col)
            bottom,right=min(r+24,row+h),min(c+24,col+w)
            external[top-row:bottom-row,left-col:right-col]=prediction[top-r:bottom-r,left-c:right-c]
    result=dict(reference_patch=reference_id,region_id=region_id,checkpoint_sha256=engine.sha256,
                dataset_version=region['dataset_version'],
                reference_observations=min(60,reference['acquisition_count']),
                cog_observations=region['acquisition_count'],
                baseline_on_shared_mask=metrics(truth,baseline,valid),
                cog_on_shared_mask=metrics(truth,external,valid),
                prediction_agreement=float((baseline[valid]==external[valid]).mean()),
                note='One overlapping test patch only. Calendars, processing sources and window origins differ; COG follows the actual web grid. Not a full benchmark or source-only ablation.')
    result['miou_classes']=common_class_metrics(result['baseline_on_shared_mask'],result['cog_on_shared_mask'])
    result['miou_definition']='Mean IoU over the common union of ground-truth and predicted classes from both runs; background included.'
    output=provider.image_path(region).parent/'overlap-validation.json'
    write_json(output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['baseline_on_shared_mask','cog_on_shared_mask']},indent=2))
    print('PASTIS mIoU:',result['baseline_on_shared_mask']['miou'])
    print('COG mIoU:',result['cog_on_shared_mask']['miou'])
    print('Report:',output)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',type=int,default=900001)
    parser.add_argument('--reference',type=int,default=10003)
    args=parser.parse_args();validate(args.region,args.reference)
