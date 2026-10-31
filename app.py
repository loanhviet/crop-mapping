"""HTTP boundary: serves the UI and delegates inference to one bounded worker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import io
import hashlib
from datetime import date
import json
import logging
from threading import Event, Lock
import time
import uuid
import zipfile

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
import numpy as np
from pydantic import BaseModel, field_validator
import httpx
import rasterio
from rasterio.warp import transform as project_points

from inference import DATA, RESULTS, ROOT, Engine, PastisProvider, export_result, preview, selection_mask, write_json
from imagery import Cancelled, GeodesProvider, ImageryError, new_grid, season_dates, setting
from predictions import PIPELINE_VERSION, PredictionStore

log = logging.getLogger('crop-map')


class AnalysisRequest(BaseModel):
    patch_id: int | None = None  # Legacy PASTIS requests remain reproducible.
    season: str = '2018–2019'
    geometry: dict

    @field_validator('geometry')
    @classmethod
    def validate_polygon(cls, value):
        try:
            ring = value['coordinates'][0]
            points = np.asarray(ring, dtype=float)
            valid = (value['type'] == 'Polygon' and len(value['coordinates']) == 1
                     and 4 <= len(ring) <= 100 and points.shape == (len(ring), 2)
                     and np.isfinite(points).all() and (np.abs(points[:, 0]) <= 180).all()
                     and (np.abs(points[:, 1]) <= 90).all() and ring[0] == ring[-1])
            if not valid:
                raise ValueError('Invalid polygon')
        except (KeyError, TypeError, ValueError, IndexError):
            raise ValueError('Supply a closed WGS84 Polygon with one ring.')
        return value


@asynccontextmanager
async def lifespan(app):
    RESULTS.mkdir(parents=True, exist_ok=True)
    app.state.provider = PastisProvider(DATA) if any(p.exists() for p in
        [DATA/'catalog.json',DATA/'cog/catalog.json']) else None
    app.state.imagery = GeodesProvider()
    app.state.source_mode = setting('CROP_SOURCE', 'prepared')
    if app.state.source_mode not in ('pastis','prepared','geodes'):
        raise RuntimeError('CROP_SOURCE must be prepared, pastis or geodes.')
    if app.state.source_mode != 'geodes' and (app.state.provider is None or not app.state.provider.public_catalog()['patches']):
        raise RuntimeError('No prepared imagery installed. Run prepare_cog.py or prepare_data.py first.')
    app.state.engine = Engine()
    app.state.predictions = PredictionStore(DATA,app.state.engine.sha256)
    if app.state.provider:
        for patch in app.state.provider.patches.values():
            if patch.get('prediction_only'):
                raise RuntimeError('Live inference requires raw satellite time series. Install the live-imagery bundle.')
    app.state.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='inference')
    app.state.lock = Lock()
    app.state.pending = {}
    app.state.completed = {}
    app.state.started = time.time()
    # Completed analyses persist across restarts; interrupted jobs become errors.
    for path in RESULTS.glob('*/status.json'):
        status = json.loads(path.read_text())
        if status['status'] in ('queued', 'running'):
            status.update(status='error', message='Analysis interrupted by a server restart. Please retry.')
            write_json(path, status)
        elif status['status']=='done' and status.get('cache_key'):
            app.state.completed[status['cache_key']]=status['id']
    yield
    with app.state.lock:
        for event in app.state.pending.values():
            event.set()
    app.state.executor.shutdown(wait=True, cancel_futures=False)


app = FastAPI(title='Crop Map', lifespan=lifespan)


@app.get('/api/health')
def health():
    return dict(status='ok', model='TSViT', device=str(app.state.engine.device),
                checkpoint_sha256=app.state.engine.sha256,
                available_patches=len(app.state.provider.patches) if app.state.provider else 0,
                source_mode=app.state.source_mode, imagery=source_status())


def source_status():
    if app.state.source_mode == 'geodes':
        return app.state.imagery.status()
    count = len(app.state.provider.public_catalog(app.state.source_mode!='pastis')['patches']) if app.state.provider else 0
    return dict(name='Prepared Sentinel‑2', configured=count > 0,
                available_regions=count, offline_imagery=True)


@app.get('/api/catalog')
def catalog():
    from inference import CLASSES
    if app.state.source_mode != 'geodes':
        local = app.state.provider.public_catalog(app.state.source_mode!='pastis') if app.state.provider else dict(patches=[])
        for patch in local['patches']:
            saved=None  # Interactive requests always run the model.
            patch['prediction_ready']=bool(saved)
            if saved:
                patch['prediction_created_at']=saved['created_at']
                patch['prediction_key']=saved['key']
        return dict(mode=app.state.source_mode, source=source_status(), classes=CLASSES,
                    seasons=[app.state.provider.catalog['season']] if app.state.provider else [],
                    patches=local['patches'])
    today = date.today()
    latest = today.year if today > date(today.year, 9, 30) else today.year-1
    return dict(mode='geodes', source=app.state.imagery.status(), classes=CLASSES,
                seasons=[f'{year-1}–{year}' for year in range(latest,2016,-1)])


@app.post('/api/imagery-plan')
def imagery_plan(request: AnalysisRequest):
    try:
        if request.patch_id is not None or app.state.source_mode != 'geodes':
            if app.state.provider is None:
                raise ValueError('No local PASTIS data is installed. Run prepare_data.py first.')
            patch, mask = app.state.provider.resolve(request.geometry, request.season, request.patch_id,
                                                    include_external=app.state.source_mode!='pastis')
            windows=selected_windows(mask)
            valid=mask&app.state.provider.valid_mask(patch['id'])
            if not valid.any():raise ValueError('This selection has insufficient valid imagery. Choose another area.')
            limit=None  # Whole-region inference is queued with progress and cancellation.
            saved=None  # Interactive requests always run the model.
            parts=selection_parts(app.state.provider,patch,mask)
            sources=[app.state.provider.get(p['id']) for p in parts]
            counts=[p['acquisition_count'] for p in sources]
            dates=sorted({d for p in sources for d in p['dates']})
            return dict(source=patch.get('source','PASTIS'), patch_id=patch['id'],
                        scenes=min(counts), model_observations=min(min(counts),60),
                        cached_scenes=min(counts), estimated_download_gb=0,
                        exceeds_download_limit=False, selected_area_ha=round(int(mask.sum())*.01,2),
                        preview_date=patch['preview_date'], first_date=min(dates),
                        last_date=max(dates), split=patch['split'], windows=len(windows),
                        valid_area_ha=round(int(valid.sum())*.01,2),
                        prediction_ready=bool(saved),blocks=len(parts),
                        observation_range=[min(counts),max(counts)],
                        max_analysis_windows=limit,exceeds_analysis_limit=bool(not saved and limit and len(windows)>limit))
        _, _, _, plan = app.state.imagery.plan(request.geometry, request.season)
        return plan
    except ValueError as error:
        raise HTTPException(422, str(error))
    except httpx.HTTPError:
        raise HTTPException(502, 'The GEODES catalogue is temporarily unavailable. Please retry.')


@app.get('/api/patches/{patch_id}/preview')
def image_preview(patch_id: int):
    try:
        payload, _ = preview(patch_id)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return Response(payload, media_type='image/png', headers={'Cache-Control': 'public, max-age=86400'})


@app.get('/api/patches/{patch_id}/preview-bounds')
def image_bounds(patch_id: int):
    try:
        _, bounds = preview(patch_id)
    except ValueError as error:
        raise HTTPException(404, str(error))
    return dict(bounds=bounds)


@app.get('/api/patches/{patch_id}/tiles/{z}/{x}/{y}.png')
def prediction_tile(patch_id:int,z:int,x:int,y:int,v:str|None=None):
    raise HTTPException(404, 'Select an area and run Analyze to create a classification.')


@app.get('/api/patches/{patch_id}/pixel')
def prepared_pixel(patch_id:int,lat:float=Query(ge=-90,le=90),lng:float=Query(ge=-180,le=180)):
    raise HTTPException(404, 'Select an area and run Analyze first.')


def job_directory(job_id):
    try:
        if str(uuid.UUID(job_id)) != job_id:
            raise ValueError()
    except ValueError:
        raise HTTPException(404, 'Analysis not found.')
    path = RESULTS / job_id
    if not (path / 'status.json').exists():
        raise HTTPException(404, 'Analysis not found.')
    return path


def selected_windows(mask):
    height,width=mask.shape
    return [(r,c) for r in range(0,height,24) for c in range(0,width,24) if mask[r:r+24,c:c+24].any()]


def selection_parts(provider,patch,mask):
    return [part for part in provider.parts(patch)
            if mask[part['row']:part['row']+provider.get(part['id'])['shape'][0],
                    part['col']:part['col']+provider.get(part['id'])['shape'][1]].any()]


def run_analysis(job_id, request, mask, cancel, cache_key=None):
    directory = RESULTS / job_id
    started = time.monotonic()
    status = dict(id=job_id, status='running', progress=0, started_at=time.time(),
                  cache_key=cache_key,message='Preparing satellite time series')
    def update(**values):
        status.update(values)
        write_json(directory / 'status.json', status)
    try:
        if cancel.is_set():
            raise Cancelled()
        if request.patch_id is None:
            patch, mask, metadata = app.state.imagery.prepare(request.geometry, request.season, directory, cancel, update)
            images = np.load(directory / 'imagery.npy', mmap_mode='r', allow_pickle=False)
            def window(row, col):
                return images[patch['frame_order'], :, row:row+24, col:col+24]
            progress_start = 70
        else:
            patch = app.state.provider.get(request.patch_id)
            selected_pixels=int(mask.sum())
            sources=[app.state.provider.get(p['id']) for p in selection_parts(app.state.provider,patch,mask)]
            mask=mask&app.state.provider.valid_mask(patch['id'])
            png, bounds = preview(patch['id'])
            (directory / 'preview.png').write_bytes(png)
            counts=[p['acquisition_count'] for p in sources]
            block_dates=[dict(region_id=p['id'],geometry=p['geometry'],dates=p['dates'],
                              model_dates=[p['dates'][i] for i in p['frame_order'][:60]]) for p in sources]
            metadata = dict(source=patch.get('source','PASTIS'), observations=min(min(counts),60),
                            available_observations=min(counts),
                            dates=sorted({d for p in sources for d in p['dates']}), split=patch['split'],
                            model_dates=block_dates[0]['model_dates'] if len(sources)==1 else None,
                            block_dates=block_dates,observation_range=[min(min(counts),60),min(max(counts),60)],
                            selected_area_ha=round(selected_pixels*.01,2),
                            excluded_pixels=selected_pixels-int(mask.sum()),
                            dataset_version=patch.get('dataset_version',patch.get('sha256')),
                            preview_bounds=bounds, preview_date=patch['preview_date'])
            def window(row, col):
                return app.state.provider.window(patch['id'], row, col)
            progress_start = 0
        height, width = mask.shape
        labels = np.zeros((height, width), dtype=np.uint8)
        confidence = np.zeros((height, width), dtype=np.float32)
        windows = selected_windows(mask)
        metadata['reused_prediction'] = False
        update(phase='inference', progress=progress_start)
        ordered_doy = ([patch['doy'][i] for i in patch['frame_order']]
                       if request.patch_id is None else patch.get('doy'))
        for index, (row, col) in enumerate(windows):
            if cancel.is_set():
                update(status='cancelled', message='Analysis cancelled')
                return
            doy=(ordered_doy if request.patch_id is None else
                 app.state.provider.window_doy(patch['id'],row,col))
            prediction, probability = app.state.engine.predict(window(row, col), doy)
            labels[row:row+24, col:col+24] = prediction
            confidence[row:row+24, col:col+24] = probability
            update(progress=progress_start+round((index+1) / len(windows) * (94-progress_start)),
                   message=f'Identifying crops · {index+1} / {len(windows)} windows')
        if cancel.is_set():
            update(status='cancelled', message='Analysis cancelled')
            return
        update(progress=95, phase='export', message='Preparing map and downloads')
        result = export_result(directory, patch, labels, confidence, mask,
                               dict(**metadata, id=job_id, patch_id=request.patch_id, season=request.season,
                                    geometry=request.geometry,
                                    checkpoint_sha256=app.state.engine.sha256,
                                    duration_seconds=round(time.monotonic()-started, 2)))
        message = 'Analysis complete' if result.get('excluded_pixels') else 'All selected pixels labeled'
        update(status='done', phase='done', progress=100, message=message, result=result)
        if cache_key:
            with app.state.lock:app.state.completed[cache_key]=job_id
    except Cancelled:
        update(status='cancelled', message='Analysis cancelled')
    except ImageryError as error:
        update(status='error', message=str(error))
    except Exception:
        if cancel.is_set():
            update(status='cancelled', message='Analysis cancelled')
        else:
            log.exception('Analysis %s failed', job_id)
            update(status='error', message='Analysis failed. Please retry or check the server log.')
    finally:
        if 'images' in locals():
            del images
        (directory / 'imagery.npy').unlink(missing_ok=True)
        with app.state.lock:
            app.state.pending.pop(job_id, None)


@app.post('/api/analyses', status_code=202)
def analyze(request: AnalysisRequest):
    cache_key=None
    try:
        if request.patch_id is None and app.state.source_mode != 'geodes':
            if app.state.provider is None:
                raise ValueError('No local PASTIS data is installed. Run prepare_data.py first.')
            patch, _ = app.state.provider.resolve(request.geometry, request.season,
                                                 include_external=app.state.source_mode!='pastis')
            request = request.model_copy(update={'patch_id':patch['id']})
        if request.patch_id is None:
            season_dates(request.season)
            _, mask = new_grid(request.geometry)
            if not app.state.imagery.status()['configured']:
                raise HTTPException(503, 'Connect THEIA / GEODES first: add GEODES_API_KEY to crop-map/.env, then retry. Create a key at geodes-portal.cnes.fr → My information → Generate.')
        else:
            if app.state.provider is None:
                raise ValueError('No local PASTIS data is installed.')
            if request.season != app.state.provider.catalog['season']:
                raise ValueError('No local PASTIS imagery is available for that season. Choose 2018–2019.')
            patch = app.state.provider.get(request.patch_id)
            mask = selection_mask(patch, request.geometry)
            limit=None  # Whole-region inference is queued with progress and cancellation.
            if limit and len(selected_windows(mask))>limit:
                raise ValueError(f'Select a smaller area: at most {limit} image windows per analysis.')
            if not (mask&app.state.provider.valid_mask(patch['id'])).any():
                raise ValueError('This selection has insufficient valid imagery. Choose another area.')
            identity=dict(request=request.model_dump(),checkpoint=app.state.engine.sha256,
                          dataset=patch.get('dataset_version',patch.get('sha256')),
                          inference_version=PIPELINE_VERSION,
                          export_version=2,
                          prediction_key=None)
            if identity['dataset']:
                cache_key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    except ValueError as error:
        raise HTTPException(422, str(error))
    with app.state.lock:
        cached=None  # A new Analyze click must perform a fresh model forward pass.
        if cached and (RESULTS/cached/'classification.tif').exists():
            return dict(id=cached,cached=True)
        if len(app.state.pending) >= 4:
            raise HTTPException(429, 'The analysis queue is full. Please try again shortly.')
        job_id = str(uuid.uuid4())
        directory = RESULTS / job_id
        directory.mkdir()
        write_json(directory / 'request.json', request.model_dump())
        write_json(directory / 'status.json', dict(id=job_id, status='queued', progress=0, message='Waiting to start analysis'))
        cancel = Event()
        app.state.pending[job_id] = cancel
        app.state.executor.submit(run_analysis, job_id, request, mask, cancel, cache_key)
    return dict(id=job_id,cached=False)


@app.get('/api/analyses/{job_id}')
def analysis_status(job_id: str):
    directory = job_directory(job_id)
    status = json.loads((directory / 'status.json').read_text())
    status['request'] = json.loads((directory / 'request.json').read_text())
    return status


@app.delete('/api/analyses/{job_id}')
def cancel_analysis(job_id: str):
    job_directory(job_id)
    with app.state.lock:
        cancel = app.state.pending.get(job_id)
        if cancel:
            cancel.set()
    return dict(id=job_id, cancellation_requested=bool(cancel))


def completed(job_id):
    directory = job_directory(job_id)
    status = json.loads((directory / 'status.json').read_text())
    if status['status'] != 'done':
        raise HTTPException(409, 'This analysis has no completed results yet.')
    return directory, status['result']


@app.get('/api/analyses/{job_id}/overlay.png')
def overlay(job_id: str):
    directory, _ = completed(job_id)
    return FileResponse(directory / 'overlay.png', media_type='image/png')


@app.get('/api/analyses/{job_id}/preview.png')
def acquired_preview(job_id: str):
    directory, _ = completed(job_id)
    if not (directory / 'preview.png').exists():
        raise HTTPException(404, 'No acquired preview for this analysis.')
    return FileResponse(directory / 'preview.png', media_type='image/png')


@app.get('/api/analyses/{job_id}/pixel')
def pixel(job_id: str, lat: float = Query(ge=-90, le=90), lng: float = Query(ge=-180, le=180)):
    directory, result = completed(job_id)
    x, y = project_points('EPSG:4326', result['crs'], [lng], [lat])
    with rasterio.open(directory / 'classification.tif') as raster:
        row, col = raster.index(x[0], y[0])
        if not (0 <= row < raster.height and 0 <= col < raster.width):
            raise HTTPException(404, 'Outside the analyzed area.')
        label = int(raster.read(1, window=((row, row+1), (col, col+1)))[0, 0])
    if label == 255:
        raise HTTPException(404, 'Outside the analyzed area.')
    from inference import CLASSES
    confidence = np.load(directory / 'confidence.npy', mmap_mode='r', allow_pickle=False)
    return dict(**CLASSES[label], confidence=round(float(confidence[row, col]), 4), row=row, col=col)


@app.get('/api/analyses/{job_id}/download/{format}')
def download(job_id: str, format: str, include: str = 'tif,csv,png,geojson'):
    directory, result = completed(job_id)
    names = dict(tif='classification.tif', csv='summary.csv', png='classification.png', geojson='classification.geojson')
    if format in names:
        return FileResponse(directory / names[format], filename=f"crop-map-{result.get('patch_id') or job_id}-{names[format]}")
    if format == 'zip':
        selected = set(include.split(','))
        if not selected or not selected.issubset(names):
            raise HTTPException(422, 'Choose known export formats: tif, csv, png, geojson.')
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in [*[name for key, name in names.items() if key in selected], 'result.json']:
                archive.write(directory / name, name)
        return Response(stream.getvalue(), media_type='application/zip',
                        headers={'Content-Disposition': f'attachment; filename="crop-map-{result.get("patch_id") or job_id}.zip"'})
    raise HTTPException(404, 'Unknown download format.')


app.mount('/', StaticFiles(directory=ROOT / 'web', html=True), name='web')
