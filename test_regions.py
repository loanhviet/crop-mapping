"""Adjacent blocks must retain their dates, georeferencing and model cache identity."""
from copy import deepcopy
import io
import json
import time

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image
import pytest
from rasterio.io import MemoryFile

import app as api_module
from cog_data import rectangle,write_json
import inference
from predictions import PredictionStore
from precompute_regions import compute


@pytest.fixture
def mosaic(tmp_path):
    data=tmp_path/'data';directory=data/'cog';directory.mkdir(parents=True)
    children=[]
    for index in range(2):
        origin=[690000+index*240,5460000]
        image=np.full((3-index,10,24,24),900+index*500,np.float32)
        mask=np.ones((24,24),bool)
        if index==0:mask[0,0]=False
        np.save(directory/f'image-{index}.npy',image)
        np.save(directory/f'mask-{index}.npy',mask)
        patch=dict(id=900100+index,split='external',season='2018–2019',source='Sentinel-2 COG',
                   region='test',name=f'block-{index}',crs='EPSG:32630',origin=origin,shape=[24,24],
                   image_path=f'cog/image-{index}.npy',valid_mask_path=f'cog/mask-{index}.npy',
                   frame_order=[2,0,1],doy=[10+index,100+index,280+index],
                   dates=['2019-04-10','2018-10-07','2019-01-10'],acquisition_count=3,
                   preview_index=0,preview_date='2019-04-10',first_date='2018-10-07',last_date='2019-04-10',
                   max_analysis_windows=1,dataset_version=f'dataset-{index}',mosaic_parent=900110)
        patch['geometry']=rectangle(patch);children.append(patch)
        if index:
            patch.update(frame_order=[1,0],doy=[11,101],
                         dates=patch['dates'][:2],acquisition_count=2)
    parent=dict(id=900110,name='test mosaic',region='test',source='Sentinel-2 COG',split='external',
                season='2018–2019',crs='EPSG:32630',origin=children[0]['origin'],shape=[24,48],
                components=[dict(id=p['id'],row=0,col=i*24) for i,p in enumerate(children)],
                acquisition_count=2,observation_range=[2,3],preview_date='Per block',
                first_date='2018-10-07',last_date='2019-04-10',dates=children[0]['dates'],
                max_analysis_windows=1,dataset_version='mosaic-v1')
    parent['geometry']=rectangle(parent);parent['default_geometry']=parent['geometry']
    write_json(directory/'catalog.json',dict(season='2018–2019',patches=[parent,*children]))
    return data,parent,children


def test_native_window_dates_masks_and_mosaic_validation(mosaic):
    data,parent,children=mosaic
    provider=inference.PreparedProvider(data)
    assert [p['id'] for p in provider.public_catalog()['patches']]==[parent['id']]
    assert provider.window(parent['id'],0,0).mean()==900
    assert provider.window(parent['id'],0,24).mean()==1400
    assert provider.window_doy(parent['id'],0,24)==children[1]['doy']
    assert provider.valid_mask(parent['id']).sum()==24*48-1
    resolved,mask=provider.resolve(parent['geometry'],parent['season'])
    assert resolved['id']==parent['id'] and mask.all()
    catalog=json.loads((data/'cog/catalog.json').read_text())
    catalog['patches'][0]['components'][1]['col']=0
    write_json(data/'cog/catalog.json',catalog)
    with pytest.raises(ValueError,match='Invalid or overlapping'):
        inference.PreparedProvider(data)


def test_precompute_real_model_and_cross_block_exports(mosaic,monkeypatch,tmp_path):
    data,parent,children=mosaic
    provider=inference.PreparedProvider(data)
    monkeypatch.setenv('CROP_THREADS','1');monkeypatch.setenv('CROP_DEVICE','cpu')
    engine=inference.Engine();store=PredictionStore(data,engine.sha256)
    compute(provider,store,engine,parent)
    # Check exact native grid and time order against separate direct model calls.
    labels,confidence=store.arrays(parent)
    for index,child in enumerate(children):
        expected,probability=engine.predict(provider.window(child['id'],0,0),child['doy'])
        valid=provider.valid_mask(child['id'])
        np.testing.assert_array_equal(labels[:,index*24:(index+1)*24][valid],expected[valid])
        np.testing.assert_allclose(confidence[:,index*24:(index+1)*24][valid],probability[valid])
    assert labels[0,0]==255 and confidence[0,0]==0
    assert PredictionStore(data,'different-model').ready(parent) is None
    assert store.ready({**parent,'dataset_version':'different-data'}) is None
    def forbidden(*args,**kwargs):raise AssertionError('Completed predictions must avoid model inference')
    monkeypatch.setattr(engine.model,'forward',forbidden)
    compute(provider,store,engine,parent)  # Resume is a cache hit.
    monkeypatch.setattr(api_module,'DATA',data)
    monkeypatch.setattr(inference,'DATA',data)
    monkeypatch.setattr(api_module,'RESULTS',tmp_path/'results')
    monkeypatch.setenv('CROP_SOURCE','prepared')
    inference.preview.cache_clear()
    with TestClient(api_module.app) as client:
        calls=[]
        actual=api_module.app.state.engine.predict
        def track(images,doy):
            calls.append(list(doy))
            return actual(images,doy)
        monkeypatch.setattr(api_module.app.state.engine,'predict',track)
        catalog=client.get('/api/catalog').json()
        assert not catalog['patches'][0]['prediction_ready']
        assert not calls
        assert client.get(f'/api/patches/{parent["id"]}/tiles/14/1/1.png').status_code==404
        body=dict(patch_id=parent['id'],season=parent['season'],geometry=parent['geometry'])
        plan=client.post('/api/imagery-plan',json=body).json()
        assert plan['blocks']==2 and not plan['prediction_ready'] and not plan['exceeds_analysis_limit']
        jobs=[]
        for run in range(2):
            response=client.post('/api/analyses',json=body)
            assert response.status_code==202 and not response.json()['cached']
            job=response.json()['id'];jobs.append(job)
            for _ in range(200):
                status=client.get('/api/analyses/'+job).json()
                if status['status'] in ('done','error'):break
                time.sleep(.02)
            assert status['status']=='done',status
            assert not status['result']['reused_prediction']
            assert len(calls)==(run+1)*2
            assert len(status['result']['block_dates'])==2
            with MemoryFile(client.get(f'/api/analyses/{job}/download/tif').content) as f,f.open() as raster:
                np.testing.assert_array_equal(raster.read(1),labels)
        assert jobs[0]!=jobs[1]
        assert calls==[children[0]['doy'],children[1]['doy']]*2
    inference.preview.cache_clear()
