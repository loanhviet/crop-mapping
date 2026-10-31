"""Continuous-cube resume, quality masking, analysis limits and cache identity."""
from copy import deepcopy
import io
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from rasterio.io import MemoryFile

import app as api_module
import cog_data
import inference


@pytest.fixture
def config():
    c=json.loads((inference.ROOT/'preparation/cog_config.json').read_text())
    c.update(shape=[48,48],observations=3,minimum_observations=3,
             minimum_clear_observations=2,default_selection_pixels=24,max_analysis_windows=1)
    return c


@pytest.fixture
def prepared(config,tmp_path,monkeypatch):
    items=[dict(id='scene-'+str(i),collection='sentinel-2-c1-l2a',
                properties={'datetime':day+'T11:00:00Z'})
           for i,day in enumerate(['2018-10-04','2019-04-12','2019-09-21'])]
    calls=[]
    monkeypatch.setattr(cog_data,'search',lambda c:dict(tile='test',features=items))
    def read(item,key,c):
        calls.append((item['id'],key))
        valid=np.ones(c['shape'],bool);valid[0,0]=False
        if key=='scl':
            a=np.full(c['shape'],4,np.uint8);a[0,1]=9
        else:a=np.full(c['shape'],1000+cog_data.ASSETS.index(key)*100,np.float32)
        return a,valid
    monkeypatch.setattr(cog_data,'read_asset',read)
    report=cog_data.prepare(config,tmp_path)
    return tmp_path,report,calls


def test_resume_and_atomic_published_cube(config,prepared):
    data,report,calls=prepared
    assert len(calls)==33
    mask=np.load(data/'cog'/config['slug']/'valid-mask.npy')
    assert not mask[0,0] and not mask[0,1] and mask[1:,1:].all()
    count=len(calls)
    again=cog_data.prepare({**config,'workers':2},data)
    assert len(calls)==count and again['dataset_version']==report['dataset_version']
    provider=inference.PreparedProvider(data)
    image=provider.window(config['id'],0,0)
    assert image.shape==(3,10,24,24) and image.dtype==np.float32
    assert provider.public_catalog()['patches'][0]['split']=='external'
    assert provider.public_catalog(include_external=False)['patches']==[]
    bad={**config,'observations':4}
    with pytest.raises(ValueError,match='Configuration changed'):cog_data.prepare(bad,data)


def test_archive_round_trip_and_no_cache_in_deploy(config,prepared,tmp_path):
    data,_,_=prepared
    destination=tmp_path/'export.tar.gz'
    cog_data.export_dataset(data,destination)
    import tarfile
    with tarfile.open(destination) as t:
        assert not any('/cache-' in n for n in t.getnames())
    restored=tmp_path/'restored'
    cog_data.restore_dataset(destination,restored)
    assert inference.PreparedProvider(restored).get(config['id'])['shape']==[48,48]
    malicious=tmp_path/'bad.tar'
    with tarfile.open(malicious,'w') as t:
        info=tarfile.TarInfo('../outside');info.size=1;t.addfile(info,io.BytesIO(b'x'))
    with pytest.raises(ValueError,match='Unsafe'):cog_data.restore_dataset(malicious,tmp_path/'unsafe')


def test_quality_selection_rejects_too_few_real_days(config):
    items=[dict(id=str(i),properties={'datetime':day+'T11:00:00Z'})
           for i,day in enumerate(['2018-10-04','2019-04-12','2019-09-21'])]
    scores={i['id']:dict(clear_fraction=1,native_fraction=1) for i in items}
    assert len(cog_data.select_dates(items,scores,config))==3
    scores['0']['clear_fraction']=0
    with pytest.raises(RuntimeError,match='Only 2 suitable'):cog_data.select_dates(items,scores,config)


def test_cog_metadata_scale_offset_and_nodata(config,tmp_path,monkeypatch):
    import rasterio
    path=tmp_path/'band.tif'
    raw=np.full(config['shape'],2000,np.uint16);raw[0,0]=0
    with rasterio.open(path,'w',driver='GTiff',height=48,width=48,count=1,dtype='uint16',
                       crs=config['crs'],transform=cog_data.grid(config),nodata=0) as raster:
        raster.write(raw,1)
    real_open=rasterio.open
    monkeypatch.setattr(cog_data.rasterio,'open',lambda url:real_open(path))
    asset={'href':'https://example.s3.amazonaws.com/B04.tif',
           'raster:bands':[{'nodata':0,'scale':.0001,'offset':-.1}]}
    image,native=cog_data.read_asset({'assets':{'red':asset}},'red',config)
    np.testing.assert_allclose(image[native],1000,rtol=1e-6)
    assert not native[0,0] and image[0,0]==0


def test_truncated_cog_read_reopens_before_retry(config,monkeypatch):
    attempts=[]
    def read(item,key,config):
        attempts.append(key)
        assert cog_data.rasterio.env.get_gdal_config('CPL_VSIL_CURL_NON_CACHED').startswith('/vsicurl/https://')
        if len(attempts)==1:raise cog_data.rasterio.errors.RasterioIOError('truncated TIFF range')
        return np.zeros(config['shape']),np.ones(config['shape'],bool)
    monkeypatch.setattr(cog_data,'_read_asset_once',read)
    monkeypatch.setattr(cog_data.time,'sleep',lambda seconds:None)
    cog_data.read_asset({'assets':{'red':{'href':'https://example.s3.amazonaws.com/B04.tif'}}},'red',config)
    assert attempts==['red','red']


def test_prepared_api_limits_mask_cache_and_restart(config,prepared,monkeypatch,tmp_path):
    data,_,_=prepared
    monkeypatch.setenv('CROP_SOURCE','prepared')
    monkeypatch.setattr(api_module,'DATA',data)
    monkeypatch.setattr(inference,'DATA',data)
    monkeypatch.setattr(api_module,'RESULTS',tmp_path/'jobs')
    inference.preview.cache_clear()
    patch=inference.PreparedProvider(data).get(config['id'])
    request=dict(patch_id=patch['id'],geometry=cog_data.rectangle(config,0,0,24,24),season=config['season'])
    with TestClient(api_module.app) as client:
        full={**request,'geometry':patch['geometry']}
        assert not client.post('/api/imagery-plan',json=full).json()['exceeds_analysis_limit']
        plan=client.post('/api/imagery-plan',json=request).json()
        assert plan['windows']==1 and plan['valid_area_ha']==5.74
        response=client.post('/api/analyses',json=request);job=response.json()['id']
        for _ in range(100):
            status=client.get('/api/analyses/'+job).json()
            if status['status'] in ('done','error'):break
            time.sleep(.05)
        assert status['status']=='done',status
        assert status['result']['source']=='Sentinel-2 COG'
        assert status['result']['excluded_pixels']==2
        with MemoryFile(client.get(f'/api/analyses/{job}/download/tif').content) as f,f.open() as raster:
            assert (raster.read(1)[0,:2]==255).all()
        cached=client.post('/api/analyses',json=request).json()
        assert cached['id']!=job and not cached['cached']
    with TestClient(api_module.app) as client:
        assert client.post('/api/analyses',json=request).json()['id']!=job
    # Version changes invalidate prior predictions even for the same geometry.
    catalog_path=data/'cog/catalog.json';catalog=json.loads(catalog_path.read_text())
    catalog['patches'][0]['dataset_version']='new-version'
    catalog_path.write_text(json.dumps(catalog))
    with TestClient(api_module.app) as client:
        assert client.post('/api/analyses',json=request).json()['id']!=job
    inference.preview.cache_clear()
