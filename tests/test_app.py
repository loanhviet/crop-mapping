"""Checks for georeferencing, valid background/nodata, real inference and exports."""
import io
import json
import time
import zipfile
from threading import Event
from types import SimpleNamespace

from fastapi.testclient import TestClient
import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.io import MemoryFile
import torch
import httpx

import app as api_module
import imagery
from inference import DATA, CLASSES, PastisProvider, export_result, grid, preprocess, selection_mask


@pytest.fixture
def provider():
    return PastisProvider()


def test_metadata_preserves_native_grid(provider):
    patch = provider.get(10003)
    convert = Transformer.from_crs(4326, patch['crs'], always_xy=True)
    points = [convert.transform(*p) for p in patch['geometry']['coordinates'][0]]
    assert points[1][0] - points[0][0] == pytest.approx(1200, abs=1e-5)
    assert points[0][1] - points[3][1] == pytest.approx(1200, abs=1e-5)
    assert points[1][1] == pytest.approx(points[0][1], abs=1e-5)
    mask = selection_mask(patch, patch['geometry'])
    assert mask.all() and mask.sum() * .01 == 144


def test_preprocessing_dates_padding_and_validation(provider):
    patch = provider.get(10000)
    image = provider.window(10000, 0, 0)
    tensor = preprocess(image, patch['doy'])
    assert tensor.shape == (60, 24, 24, 11)
    assert tensor.dtype == torch.float32
    assert torch.count_nonzero(tensor[43:]) == 0
    recovered_doy = (tensor[:43, 0, 0, 10] * 365.0001).round().to(torch.int64).tolist()
    assert recovered_doy == patch['doy']
    with pytest.raises(ValueError):
        preprocess(image[:, :9], patch['doy'])
    invalid = image.astype(float)
    invalid[0, 0, 0, 0] = np.nan
    with pytest.raises(ValueError):
        preprocess(invalid, patch['doy'])


def test_selection_outside_coverage_rejected(provider):
    patch = provider.get(10003)
    geometry = json.loads(json.dumps(patch['geometry']))
    for point in geometry['coordinates'][0]:
        point[0] += .1
    with pytest.raises(ValueError, match='outlined area'):
        selection_mask(patch, geometry)


def test_exports_keep_background_and_mask_consistent(tmp_path, provider):
    patch = provider.get(10003)
    labels = np.zeros((120, 120), dtype=np.uint8)
    labels[:10, :10] = 2
    mask = np.zeros_like(labels, dtype=bool)
    mask[:24, :24] = True
    result = export_result(tmp_path, patch, labels, np.ones_like(labels, dtype=np.float32), mask,
                           {'checkpoint_sha256': 'test'})
    assert result['area_ha'] == 5.76
    assert sum(r['pixels'] for r in result['classes']) == 576
    assert next(r for r in result['classes'] if r['id'] == 0)['pixels'] == 476
    with rasterio.open(tmp_path / 'classification.tif') as raster:
        exported = raster.read(1)
        assert raster.nodata == 255
        assert raster.crs.to_string() == patch['crs']
        assert raster.transform == grid(patch)
        assert (exported[~mask] == 255).all()
        assert np.array_equal(exported[mask], labels[mask])
    features = json.loads((tmp_path / 'classification.geojson').read_text())['features']
    assert {f['properties']['class_id'] for f in features} == {0, 2}


def test_real_checkpoint_api_download_and_pixel(tmp_path, monkeypatch, provider):
    monkeypatch.setattr(api_module, 'RESULTS', tmp_path)
    patch = provider.get(10003)
    west, north = patch['origin']
    converter = Transformer.from_crs(patch['crs'], 4326, always_xy=True)
    ring = [converter.transform(*p) for p in [(west,north),(west+240,north),
            (west+240,north-240),(west,north-240),(west,north)]]
    geometry = {'type': 'Polygon', 'coordinates': [ring]}
    with TestClient(api_module.app) as client:
        assert client.get('/api/health').json()['status'] == 'ok'
        request = {'patch_id': 10003, 'geometry': geometry}
        assert client.post('/api/analyses', json={**request, 'season': '2025–2026'}).status_code == 422
        assert client.post('/api/analyses', json={**request, 'patch_id': 999999}).status_code == 422
        response = client.post('/api/analyses', json=request)
        assert response.status_code == 202
        job_id = response.json()['id']
        for _ in range(100):
            status = client.get(f'/api/analyses/{job_id}').json()
            if status['status'] in ('done', 'error'):
                break
            time.sleep(.1)
        assert status['status'] == 'done', status
        assert status['result']['area_ha'] == 5.76
        assert sum(r['area_ha'] for r in status['result']['classes']) == pytest.approx(5.76)
        tif = client.get(f'/api/analyses/{job_id}/download/tif')
        with MemoryFile(tif.content) as file, file.open() as raster:
            assert (raster.read(1)[:24, :24] <= 18).all()
            assert (raster.read(1)[24:] == 255).all()
        longitude, latitude = converter.transform(west+5, north-5)
        response = client.get(f'/api/analyses/{job_id}/pixel', params={'lat': latitude, 'lng': longitude})
        assert response.status_code == 200
        assert response.json()['row'] == response.json()['col'] == 0
        assert 0 <= response.json()['confidence'] <= 1
        bundle = client.get(f'/api/analyses/{job_id}/download/zip?include=tif,csv')
        assert set(zipfile.ZipFile(io.BytesIO(bundle.content)).namelist()) == {'classification.tif', 'summary.csv', 'result.json'}
        assert client.get(f'/api/analyses/{job_id}/download/zip?include=unknown').status_code == 422
        assert client.get('/api/analyses/../../weights/best.pth').status_code == 404


def live_geometry():
    converter = Transformer.from_crs(32630, 4326, always_xy=True)
    ring = [converter.transform(*point) for point in [(690000,5460000),(690480,5460000),
            (690480,5459760),(690000,5459760),(690000,5460000)]]
    return {'type':'Polygon', 'coordinates':[ring]}


def scene_archive():
    """Small MUSCATE format fixture, not downloaded/validated GEODES imagery."""
    from rasterio.transform import from_origin
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('scene_MTD_ALL.xml', '<root><REFLECTANCE_QUANTIFICATION_VALUE>20000</REFLECTANCE_QUANTIFICATION_VALUE>'
            '<Special_Values_List><SPECIAL_VALUE name="nodata">-10000</SPECIAL_VALUE></Special_Values_List></root>')
        for index, name in enumerate([*imagery.BANDS,'CLM_R1','EDG_R1','SAT_R1','SAT_R2','MG2_R1']):
            resolution = 20 if name in ('B5','B6','B7','B8A','B11','B12','SAT_R2') else 10
            array = np.full((480//resolution,480//resolution),2000+index*100 if index<10 else 0,
                            dtype='int16' if index<10 else 'uint8')
            if name == 'CLM_R1':
                array[0,0] = 1  # Always cloudy: must be exported as nodata.
            with MemoryFile() as memory:
                with memory.open(driver='GTiff',width=array.shape[1],height=array.shape[0],count=1,
                                 dtype=array.dtype,crs='EPSG:32630',transform=from_origin(690000,5460000,resolution,resolution)) as raster:
                    raster.write(array,1)
                archive.writestr('scene_'+('FRE_' if index<10 else '')+name+'.tif',memory.read())
    return stream.getvalue()


def test_live_grid_and_completed_seasons():
    patch, mask = imagery.new_grid(live_geometry())
    assert patch['shape'] == [24,48]
    assert patch['crs'] == 'EPSG:32630'
    assert mask.all() and mask.sum()*.01 == 11.52
    assert imagery.season_dates('2018–2019') == ('2018-10-01T00:00:00Z','2019-09-30T23:59:59Z')
    for season in ('2015–2016','2018–2020','2098–2099','yesterday'):
        with pytest.raises(imagery.ImageryError):
            imagery.season_dates(season)
    large = {'type':'Polygon','coordinates':[[[-.5,49.5],[-.3,49.5],[-.3,49.3],[-.5,49.3],[-.5,49.5]]]}
    with pytest.raises(imagery.ImageryError, match='smaller'):
        imagery.new_grid(large)


def test_theia_band_scaling_alignment_and_quality():
    patch, _ = imagery.new_grid(live_geometry())
    with zipfile.ZipFile(io.BytesIO(scene_archive())) as archive:
        image, native, clear = imagery.read_scene(archive, patch)
    assert image.shape == (10,24,48)
    assert np.array_equal(image[:,12,12],np.arange(1000,1500,50,dtype=np.float32))
    assert native.all() and clear.sum() == 24*48-1
    assert not clear[0,0]


def test_one_archive_download_redirect_auth_and_cancellation(tmp_path):
    payload = scene_archive()
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.host == 'geodes-portal.cnes.fr':
            return httpx.Response(302,headers={'location':'https://s3.datalake.cnes.fr/scene.zip'})
        assert 'range' not in request.headers
        return httpx.Response(200,content=payload)
    cancel = Event()
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        download = imagery.Download(client,'private-test-key',cancel,lambda **values:None)
        with imagery.open_archive(download,'https://geodes-portal.cnes.fr/api/download/a:b',tmp_path) as archive:
            assert archive.read('scene_MTD_ALL.xml').startswith(b'<root>')
        assert len(requests) == 2  # One portal request, one redirect; no range probes.
        assert all(request.headers.get('x-api-key') == 'private-test-key' for request in requests if request.url.host == 'geodes-portal.cnes.fr')
        assert all('x-api-key' not in request.headers for request in requests if request.url.host == 's3.datalake.cnes.fr')
        cancel.set()
        with pytest.raises(imagery.Cancelled):
            download.get('https://geodes-portal.cnes.fr/file')
    with pytest.raises(imagery.ImageryError):
        imagery.safe_url('https://untrusted.example/archive.zip')


def test_full_archive_fallback_is_streamed(tmp_path):
    payload = scene_archive()
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,content=payload))) as client:
        download = imagery.Download(client,'test-key',Event(),lambda **values:None)
        with imagery.open_archive(download,'https://geodes-portal.cnes.fr/scene.zip',tmp_path) as archive:
            assert len(archive.namelist()) == 16
        assert (tmp_path/'scene.zip').read_bytes() == payload


def test_quota_wait_is_visible_and_cancellable():
    cancel = Event()
    updates = []
    def update(**values):
        updates.append(values)
        if values.get('phase') == 'quota':cancel.set()
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(429,
            json={'error':'Download quota exhausted'},headers={'Retry-After':'3600'}))) as client:
        download = imagery.Download(client,'test-key',cancel,update)
        with pytest.raises(imagery.Cancelled):
            download.get('https://geodes-portal.cnes.fr/scene.zip')
    assert updates[0]['phase'] == 'quota' and updates[0]['retry_at'] > time.time()


def test_live_api_requires_key_without_creating_a_job(tmp_path,monkeypatch):
    monkeypatch.setenv('CROP_SOURCE','geodes')
    monkeypatch.setattr(api_module,'RESULTS',tmp_path)
    monkeypatch.setenv('GEODES_API_KEY','')
    with TestClient(api_module.app) as client:
        catalog = client.get('/api/catalog').json()
        assert 'patches' not in catalog
        assert catalog['source']['configured'] is False
        response = client.post('/api/analyses',json={'geometry':live_geometry()})
        assert response.status_code == 503
        assert 'GEODES_API_KEY' in response.json()['detail']
        assert list(tmp_path.iterdir()) == []


def test_live_acquisition_to_real_model_and_exports(tmp_path,monkeypatch):
    monkeypatch.setenv('CROP_SOURCE','geodes')
    monkeypatch.setattr(api_module,'RESULTS',tmp_path)
    monkeypatch.setenv('GEODES_API_KEY','private-test-key')
    monkeypatch.setattr(imagery,'DATA',tmp_path/'source-cache')
    payload = scene_archive()
    acquired = ['2018-10-04T11:17:00Z','2019-03-02T11:17:00Z','2019-07-03T11:17:00Z']
    footprint = {'type':'Polygon','coordinates':[[[-2,50],[0,50],[0,48],[-2,48],[-2,50]]]}
    calls = []
    def handler(request):
        calls.append(str(request.url))
        if request.method == 'POST':
            query = json.loads(request.content)
            assert query['query']['start_datetime']['gte'].startswith('2018-10-01')
            assert 'datetime' not in query['query']
            return httpx.Response(200,json={'features':[dict(id=f'scene-{i}',geometry=footprint,
                properties={'grid:code':'T30UXV','start_datetime':timestamp,'datetime':'2026-01-01','version':'4.0'},
                assets={'scene.zip':{'href':f'https://geodes-portal.cnes.fr/scene-{i}.zip',
                                    'roles':['data'],'description':'Is online: true'}}) for i,timestamp in enumerate(acquired)]})
        assert request.headers['x-api-key'] == 'private-test-key'
        assert 'range' not in request.headers
        return httpx.Response(200,content=payload)
    original_client = httpx.Client
    monkeypatch.setattr(imagery,'httpx',SimpleNamespace(Timeout=httpx.Timeout,
        Client=lambda **kwargs:original_client(transport=httpx.MockTransport(handler),**kwargs)))
    with TestClient(api_module.app) as client:
        plan = client.post('/api/imagery-plan',json={'geometry':live_geometry(),'season':'2018–2019'}).json()
        assert plan['scenes'] == 3 and plan['cached_scenes'] == 0
        response = client.post('/api/analyses',json={'geometry':live_geometry(),'season':'2018–2019'})
        assert response.status_code == 202
        job = response.json()['id']
        for _ in range(100):
            status = client.get(f'/api/analyses/{job}').json()
            if status['status'] in ('done','error'):break
            time.sleep(.05)
        assert status['status'] == 'done',status
        result = status['result']
        assert result['source'] == 'THEIA / GEODES' and result['patch_id'] is None
        assert result['observations'] == 3 and result['excluded_pixels'] == 1
        assert result['area_ha'] == 11.51 and result['selected_area_ha'] == 11.52
        assert 'private-test-key' not in json.dumps(status)
        assert client.get(f'/api/analyses/{job}/preview.png').headers['content-type'] == 'image/png'
        with rasterio.open(tmp_path/job/'classification.tif') as raster:
            assert (raster.width,raster.height) == (48,24)
            assert raster.read(1)[0,0] == 255
            assert raster.tags()['source'] == 'THEIA / GEODES'
        assert not (tmp_path/job/'imagery.npy').exists()
        assert len([call for call in calls if '/api/stac/items' in call]) == 2
        assert len([call for call in calls if call.endswith('.zip')]) == 3
        plan = client.post('/api/imagery-plan',json={'geometry':live_geometry(),'season':'2018–2019'}).json()
        assert plan['cached_scenes'] == 3 and plan['estimated_download_gb'] == 0
        second = tmp_path/'repeat'
        second.mkdir()
        patch,mask,metadata = api_module.app.state.imagery.prepare(live_geometry(),'2018–2019',second,Event(),lambda **values:None)
        assert metadata['downloaded_mb'] == 0 and mask.sum() == 1151
        assert len([call for call in calls if call.endswith('.zip')]) == 3  # Cache avoids all new downloads.


def test_cog_boa_offset_and_nodata(tmp_path, monkeypatch):
    """A PB05 DN of 2000 means reflectance 0.1, not 0.2; nodata stays invalid."""
    from scripts import benchmark_cog
    from rasterio.transform import from_origin
    path = tmp_path/'band.tif'
    raw = np.full((24,24),2000,dtype=np.uint16)
    raw[0,0] = 0
    with rasterio.open(path,'w',driver='GTiff',height=24,width=24,count=1,
                       dtype='uint16',crs='EPSG:32630',
                       transform=from_origin(600000,5500000,10,10),nodata=0) as raster:
        raster.write(raw,1)
    original_open = rasterio.open
    monkeypatch.setattr(benchmark_cog.rasterio,'open',lambda url:original_open(path))
    asset = dict(href='https://example.s3.amazonaws.com/B04.tif',
                 **{'raster:bands':[dict(nodata=0,scale=.0001,offset=-.1)]})
    patch = dict(crs='EPSG:32630',origin=[600000,5500000],shape=[24,24])
    image, valid = benchmark_cog.read_asset(dict(assets={'red':asset}),'red',patch)
    np.testing.assert_allclose(image[valid],1000,rtol=1e-6)
    assert not valid[0,0] and image[0,0] == 0 and valid.sum() == 575

