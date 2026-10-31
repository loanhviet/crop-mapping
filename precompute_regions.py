"""Run the real TSViT checkpoint once per native window; resume after interruption.

Finished block arrays are reused unchanged when building the large mosaic.
Run on CPU or with CROP_DEVICE=cuda:0 in an existing CUDA environment.
"""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import time

import numpy as np
import rasterio
import torch
from PIL import Image

from cog_data import digest,write_json
from inference import DATA, Engine, PreparedProvider, grid, preprocess
from predictions import PIPELINE_VERSION,PredictionStore


def finish(store,patch,labels,confidence,details):
    directory=store.directory(patch)
    valid=labels!=255
    with rasterio.open(directory/'classification.pending.tif','w',driver='GTiff',
            height=labels.shape[0],width=labels.shape[1],count=1,dtype='uint8',
            crs=patch['crs'],transform=grid(patch),nodata=255,compress='deflate',tiled=True) as raster:
        raster.write(labels,1)
        raster.update_tags(model='TSViT',checkpoint_sha256=store.checkpoint,
                           dataset_version=patch['dataset_version'],pipeline_version=PIPELINE_VERSION)
    (directory/'classification.pending.tif').replace(directory/'classification.tif')
    report=dict(key=store.key(patch),region_id=patch['id'],shape=patch['shape'],model='TSViT',
                checkpoint_sha256=store.checkpoint,dataset_version=patch['dataset_version'],
                pipeline_version=PIPELINE_VERSION,created_at=datetime.now(timezone.utc).isoformat(),
                torch_version=torch.__version__,
                valid_pixels=int(valid.sum()),area_ha=round(int(valid.sum())*.01,2),
                **details,files={name:dict(bytes=(directory/name).stat().st_size,sha256=digest(directory/name))
                    for name in ['labels.npy','confidence.npy','classification.tif']})
    write_json(directory/'ready.json',report)
    print(json.dumps(dict(stage='prediction_ready',region_id=patch['id'],**details)),flush=True)
    return report


def compute(provider,store,engine,patch,batch_size=1):
    # A compact native-grid preview lets EC2 serve saved results without raw cubes.
    if not patch.get('components'):
        directory=store.directory(patch);directory.mkdir(parents=True,exist_ok=True)
        preview_path=directory/'preview-rgb.png'
        if not preview_path.exists():
            h,w=patch['shape']
            image=provider.image(patch['id'])[patch['preview_index'],[2,1,0],:h,:w].astype(np.float32)
            rgb=np.uint8(np.clip(image/3000,0,1)**(1/1.3)*255)
            temporary=directory/'preview-rgb.tmp'
            Image.fromarray(rgb.transpose(1,2,0)).save(temporary,format='PNG')
            temporary.replace(preview_path)
    if store.ready(patch):
        print(json.dumps(dict(stage='prediction_cached',region_id=patch['id'])),flush=True)
        return store.ready(patch)
    directory=store.directory(patch);directory.mkdir(parents=True,exist_ok=True)
    height,width=patch['shape'];started=time.monotonic()
    labels_path=directory/'labels.npy';confidence_path=directory/'confidence.npy'
    progress=directory/'completed.npy'
    if not progress.exists():
        for path,dtype,fill in [(labels_path,'uint8',255),(confidence_path,'float32',0)]:
            a=np.lib.format.open_memmap(path,mode='w+',dtype=dtype,shape=(height,width))
            a[:]=fill;a.flush();del a
        np.save(progress,np.zeros((height//24,width//24),bool),allow_pickle=False)
    labels=np.load(labels_path,mmap_mode='r+',allow_pickle=False)
    confidence=np.load(confidence_path,mmap_mode='r+',allow_pickle=False)
    done=np.load(progress,allow_pickle=False)
    if patch.get('components'):
        for part in patch['components']:
            child=provider.get(part['id'])
            compute(provider,store,engine,child,batch_size)
            a,b=store.arrays(child);h,w=a.shape;r,c=part['row'],part['col']
            labels[r:r+h,c:c+w]=a;confidence[r:r+h,c:c+w]=b
        labels.flush();confidence.flush()
        return finish(store,patch,labels,confidence,
                      dict(duration_seconds=round(time.monotonic()-started,2),components=patch['components'],
                           device=str(engine.device),derived_from_completed_blocks=True))
    valid=provider.valid_mask(patch['id'])
    windows=[(r,c) for r in range(0,height,24) for c in range(0,width,24)
             if valid[r:r+24,c:c+24].any() and not done[r//24,c//24]]
    total=len(windows)
    for offset in range(0,total,batch_size):
        batch=windows[offset:offset+batch_size]
        inputs=torch.stack([preprocess(provider.window(patch['id'],r,c),patch['doy']) for r,c in batch])
        with torch.inference_mode():
            probability=engine.model(inputs.to(engine.device)).softmax(dim=1)
            conf,pred=probability.max(dim=1)
            pred=pred.cpu().numpy().astype(np.uint8);conf=conf.cpu().numpy()
        for i,(r,c) in enumerate(batch):
            mask=valid[r:r+24,c:c+24]
            labels[r:r+24,c:c+24]=np.where(mask,pred[i],255)
            confidence[r:r+24,c:c+24]=np.where(mask,conf[i],0)
            done[r//24,c//24]=True
        labels.flush();confidence.flush()
        temporary=progress.with_suffix('.tmp')
        with temporary.open('wb') as stream:np.save(stream,done,allow_pickle=False)
        temporary.replace(progress)
        if offset%32==0 or offset+len(batch)==total:
            print(json.dumps(dict(stage='prediction',region_id=patch['id'],completed=offset+len(batch),
                                  remaining=total-offset-len(batch),seconds=round(time.monotonic()-started,1))),flush=True)
    return finish(store,patch,labels,confidence,
                  dict(duration_seconds=round(time.monotonic()-started,2),device=str(engine.device),
                       windows_computed=total,observations=patch['acquisition_count'],
                       dates=patch['dates'],accuracy_validated=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,default=DATA)
    parser.add_argument('--region',type=int,default=900010)
    parser.add_argument('--batch-size',type=int,default=1,choices=range(1,9))
    args=parser.parse_args();engine=Engine();provider=PreparedProvider(args.data)
    compute(provider,PredictionStore(args.data,engine.sha256),engine,provider.get(args.region),args.batch_size)
