"""Local demo must run real inference without any imagery network request."""
import io
import json
import time
from copy import deepcopy

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app as api_module
from inference import DATA, PastisProvider
from prepare_data import make_patch


def test_local_catalog_plan_preview_and_real_prediction(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, 'RESULTS', tmp_path)
    monkeypatch.setenv('CROP_SOURCE', 'pastis')
    monkeypatch.setenv('GEODES_API_KEY', '')
    def no_network(*args, **kwargs):
        raise AssertionError('The local PASTIS demo must not request GEODES imagery')
    monkeypatch.setattr(api_module.GeodesProvider, 'plan', no_network)
    monkeypatch.setattr(api_module.GeodesProvider, 'prepare', no_network)
    with TestClient(api_module.app) as client:
        catalog = client.get('/api/catalog').json()
        assert catalog['mode'] == 'pastis' and catalog['source']['configured']
        assert catalog['seasons'] == ['2018–2019']
        assert all(p['split'] == 'test' for p in catalog['patches'])
        assert 10000 not in [p['id'] for p in catalog['patches']]
        patch = next(p for p in catalog['patches'] if p['id'] == 10003)
        image = client.get('/api/patches/10003/preview')
        assert image.status_code == 200
        with Image.open(io.BytesIO(image.content)) as rgb:
            assert max(rgb.size) < 140  # preview cropped to the usable footprint
        # No patch ID: resolve a small selection to its downloaded source patch.
        geometry = deepcopy(patch['geometry'])
        points = np.array(geometry['coordinates'][0])
        centre = points[:4].mean(axis=0)
        geometry['coordinates'] = [(centre+(points-centre)*.15).tolist()]
        request = dict(geometry=geometry, season='2018–2019')
        plan = client.post('/api/imagery-plan', json=request)
        assert plan.status_code == 200, plan.text
        assert plan.json()['patch_id'] == 10003
        assert plan.json()['cached_scenes'] == plan.json()['scenes']
        assert plan.json()['estimated_download_gb'] == 0
        assert client.post('/api/imagery-plan', json={**request,'season':'2023–2024'}).status_code == 422
        outside = deepcopy(geometry)
        outside['coordinates'] = [[[x+3,y] for x,y in outside['coordinates'][0]]]
        assert client.post('/api/analyses', json={**request,'geometry':outside}).status_code == 422
        response = client.post('/api/analyses', json=request)
        assert response.status_code == 202
        job = response.json()['id']
        for _ in range(100):
            status = client.get(f'/api/analyses/{job}').json()
            if status['status'] in ('done','error'): break
            time.sleep(.05)
        assert status['status'] == 'done', status
        result = status['result']
        assert result['patch_id'] == 10003 and result['split'] == 'test'
        assert result['source'] == 'PASTIS' and result['observations'] == 43
        assert result['preview_bounds']
        assert client.get(f'/api/analyses/{job}/preview.png').status_code == 200
        assert sum(c['pixels'] for c in result['classes']) == result['pixels']


def test_prepare_other_tile_polygon_and_doy_order(tmp_path):
    features = json.loads((DATA/'metadata.geojson').read_text())['features']
    feature = deepcopy(next(f for f in features if f['properties']['ID_PATCH'] == 20000))
    feature['properties']['dates-S2'] = {'0':20191001,'1':20190102,'2':20181001}
    image_path = tmp_path/'S2_20000.npy'
    np.save(image_path, np.zeros((3,10,128,128), dtype=np.int16))
    patch = make_patch(feature, image_path, reference_dates=[])
    assert patch['crs'] == 'EPSG:32631'
    assert patch['frame_order'] == [1,0,2] and patch['doy'] == [2,274,274]
    assert patch['shape'] == [120,120] and patch['split'] == 'test'
    assert patch['geometry']['type'] == 'Polygon'
    from inference import selection_mask
    assert selection_mask(patch, patch['geometry']).sum() == 14400


def test_catalog_does_not_advertise_missing_imagery(tmp_path):
    catalog = {'season':'2018–2019','patches':[{'id':123,'split':'test'}]}
    (tmp_path/'catalog.json').write_text(json.dumps(catalog))
    assert PastisProvider(tmp_path).public_catalog()['patches'] == []
