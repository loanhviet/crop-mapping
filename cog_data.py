"""Prepare a continuous, georeferenced Sentinel-2 cube before web inference.

No torch, web server, labels or credentials required. Completed scene files
are atomic and reusable after interruption. Only completed cubes are published.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import hashlib
import fcntl
import json
from pathlib import Path
import time
import tarfile
from urllib.parse import urlsplit

import httpx
import numpy as np
from pyproj import Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom

API = 'https://earth-search.aws.element84.com/v1'
ASSETS = ['blue','green','red','rededge1','rededge2','rededge3','nir','nir08','swir16','swir22']
BANDS = ['B2','B3','B4','B5','B6','B7','B8','B8A','B11','B12']
ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',
           GDAL_HTTP_TIMEOUT='45', GDAL_HTTP_CONNECTTIMEOUT='15',
           GDAL_HTTP_MAX_RETRY='2', GDAL_HTTP_RETRY_DELAY='2')


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(path)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024**2), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def grid(config):
    return from_origin(*config['origin'],10,10)


def rectangle(config, row=0, col=0, height=None, width=None):
    height = config['shape'][0] if height is None else height
    width = config['shape'][1] if width is None else width
    west,north = config['origin'][0]+col*10, config['origin'][1]-row*10
    convert = Transformer.from_crs(config['crs'],4326,always_xy=True)
    ring = [(west,north),(west+width*10,north),(west+width*10,north-height*10),
            (west,north-height*10),(west,north)]
    return dict(type='Polygon',coordinates=[[list(convert.transform(*point)) for point in ring]])


def validate_config(c):
    if not isinstance(c['id'],int) or c['id'] < 900000:
        raise ValueError('Use a distinct COG region ID >= 900000.')
    if not c['slug'] or any(x not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for x in c['slug']):
        raise ValueError('Unsafe region slug')
    if any(not isinstance(n,int) or n<24 or n>1536 or n%24 for n in c['shape']):
        raise ValueError('Shape must be 24-pixel multiples, at most 1536 per side.')
    if not 1 <= c['minimum_observations'] <= c['observations'] <= 60:
        raise ValueError('Require 1 <= minimum_observations <= observations <= 60.')
    if not 1<=c['workers']<=8:
        raise ValueError('Use 1–8 workers.')
    if any(not 0<=c[key]<=1 for key in ['minimum_clear_fraction','minimum_native_fraction']):
        raise ValueError('Quality fractions must be between 0 and 1.')
    if not 1<=c['minimum_clear_observations']<=c['minimum_observations']:
        raise ValueError('Invalid per-pixel clear observation requirement.')
    if not 24<=c['default_selection_pixels']<=min(c['shape']) or c['default_selection_pixels']%24:
        raise ValueError('Invalid default selection size.')
    if date.fromisoformat(c['start_date'])>=date.fromisoformat(c['end_date']):
        raise ValueError('Invalid date interval')


def search(config):
    ring = np.array(rectangle(config)['coordinates'][0])
    query = dict(collections=['sentinel-2-c1-l2a','sentinel-2-l2a'],limit=100,
                 bbox=[float(ring[:,0].min()),float(ring[:,1].min()),
                       float(ring[:,0].max()),float(ring[:,1].max())],
                 datetime=config['start_date']+'T00:00:00Z/'+config['end_date']+'T23:59:59Z')
    found = {}
    with httpx.Client(timeout=60) as client:
        for _ in range(30):
            for attempt in range(3):
                response=client.post(API+'/search',json=query)
                if response.status_code not in (429,500,502,503,504) or attempt==2:break
                time.sleep(2)
            response.raise_for_status()
            body=response.json()
            for item in body['features']:
                if all(a in item.get('assets',{}) for a in ASSETS+['scl']):
                    found[(item['collection'],item['id'])]=item
            following=next((x for x in body.get('links',[]) if x.get('rel')=='next'),None)
            if not following:break
            query=following['body']
        else:raise RuntimeError('Too many catalog pages')
    # Full-region footprint coverage, and one real date per observation.
    tiles={}
    for item in found.values():
        footprint=transform_geom('EPSG:4326',config['crs'],item['geometry'])
        inside=geometry_mask([footprint],out_shape=tuple(config['shape']),transform=grid(config),invert=True)
        if inside.all():tiles.setdefault(item['properties']['grid:code'],[]).append(item)
    if not tiles:raise RuntimeError('Choose a region covered by one Sentinel-2 tile.')
    tile,entries=max(tiles.items(),key=lambda pair:len({x['properties']['datetime'][:10] for x in pair[1]}))
    chosen={}
    def rank(item):
        p=item['properties']
        return (item['collection']=='sentinel-2-c1-l2a',float(p.get('s2:processing_baseline',0)),p.get('updated',''))
    for item in entries:
        day=item['properties']['datetime'][:10]
        if day not in chosen or rank(item)>rank(chosen[day]):chosen[day]=item
    return dict(tile=tile,features=sorted(chosen.values(),key=lambda x:x['properties']['datetime']))


def read_asset(item,key,config):
    # Successful HTTP status can still carry a truncated TIFF byte range.
    # Reopening with a cleared per-URL cache retries the actual band read.
    for attempt in range(3):
        try:
            with rasterio.Env(CPL_VSIL_CURL_NON_CACHED='/vsicurl/'+item['assets'][key]['href']):
                return _read_asset_once(item,key,config)
        except rasterio.errors.RasterioIOError:
            if attempt==2:raise
            time.sleep(1+attempt)


def _read_asset_once(item,key,config):
    asset=item['assets'][key]
    parsed=urlsplit(asset['href'])
    if (parsed.scheme!='https' or not parsed.hostname or not parsed.hostname.endswith('.amazonaws.com')
            or not parsed.path.endswith('.tif') or asset.get('storage:requester_pays')):
        raise ValueError('Expected a public Sentinel-2 HTTPS COG asset.')
    info=asset.get('raster:bands',[{}])[0]
    with rasterio.Env(**ENV),rasterio.open(asset['href']) as source:
        nodata=info.get('nodata',source.nodata)
        if nodata is None:raise ValueError('Missing nodata metadata')
        with WarpedVRT(source,crs=config['crs'],transform=grid(config),
                       height=config['shape'][0],width=config['shape'][1],
                       src_nodata=nodata,nodata=nodata,dtype='float32',
                       resampling=Resampling.nearest if key=='scl' else Resampling.bilinear) as vrt:
            raw=vrt.read(1)
    native=np.isfinite(raw)&(raw!=nodata)
    if key=='scl':return raw.astype(np.uint8),native
    if 'scale' not in info:raise ValueError('Missing reflectance scale metadata')
    image=(raw*np.float32(info['scale'])+np.float32(info.get('offset',0)))*np.float32(10000)
    image[~native]=0
    return image,native


def save_scene(path,**values):
    temporary=path.with_suffix('.tmp')
    with temporary.open('wb') as stream:np.savez_compressed(stream,**values)
    temporary.replace(path)


def select_dates(items,assessments,config):
    eligible=[x for x in items if assessments[x['id']]['clear_fraction']>=config['minimum_clear_fraction']
              and assessments[x['id']]['native_fraction']>=config['minimum_native_fraction']]
    if len(eligible)<config['minimum_observations']:
        raise RuntimeError(f'Only {len(eligible)} suitable dates; minimum is {config["minimum_observations"]}. '
                           'Keep the quality thresholds explicit; do not invent observations.')
    count=min(config['observations'],len(eligible))
    start=date.fromisoformat(config['start_date']).toordinal()
    end=date.fromisoformat(config['end_date']).toordinal()
    remaining=list(eligible);chosen=[]
    # Allocate across the entire actual season; quality is the tie-breaker.
    for target in np.linspace(start,end,count):
        best=min(remaining,key=lambda x:(abs(date.fromisoformat(x['properties']['datetime'][:10]).toordinal()-target),
                    -assessments[x['id']]['clear_fraction'],x['id']))
        remaining.remove(best);chosen.append(best)
    return sorted(chosen,key=lambda x:x['properties']['datetime'])


def prepare(config,data_dir):
    validate_config(config)
    data_dir=Path(data_dir)
    output=data_dir/'cog'/config['slug']
    output.mkdir(parents=True,exist_ok=True)
    effective=output/'config.json'
    semantic={k:v for k,v in config.items() if k!='workers'}
    if effective.exists() and {k:v for k,v in json.loads(effective.read_text()).items() if k!='workers'}!=semantic:
        raise ValueError('Configuration changed. Use a new slug to keep datasets separate.')
    write_json(effective,config)
    def emit(stage,**values):
        row=dict(stage=stage,**values)
        write_json(output/'progress.json',row)
        print(json.dumps(row),flush=True)
    report_path=output/'report.json'
    published=data_dir/'cog/catalog.json'
    if report_path.exists() and published.exists():
        report=json.loads(report_path.read_text())
        entries=json.loads(published.read_text())['patches']
        if any(p['id']==config['id'] and p.get('dataset_version')==report['dataset_version'] for p in entries):
            if all((output/name).is_file() and (output/name).stat().st_size==s['bytes']
                   and digest(output/name)==s['sha256'] for name,s in report['files'].items()):
                emit('ready',region_id=config['id'],area_ha=report['area_ha'],observations=report['observations'],cached=True)
                return report
    started=time.monotonic()
    catalog_file=output/'catalog-source.json'
    if not catalog_file.exists():write_json(catalog_file,search(config))
    catalog=json.loads(catalog_file.read_text());items=catalog['features']
    emit('catalog',dates=len(items),tile=catalog['tile'],shape=config['shape'])
    quality=output/'cache-quality';quality.mkdir(exist_ok=True)
    scenes=output/'cache-scenes';scenes.mkdir(exist_ok=True)
    assessments={}
    def quality_date(item):
        path=quality/(item['id']+'.npz')
        if not path.exists():
            scl,native=read_asset(item,'scl',config)
            save_scene(path,scl=scl,native=native)
        with np.load(path,allow_pickle=False) as d:
            native=d['native']&(d['scl']!=1)
            clear=np.isin(d['scl'],[4,5,6])&native
            return dict(id=item['id'],date=item['properties']['datetime'][:10],
                        clear_fraction=float(clear.mean()),native_fraction=float(native.mean()))
    errors=[]
    with ThreadPoolExecutor(max_workers=config['workers']) as pool:
        futures={pool.submit(quality_date,item):item for item in items}
        for future in as_completed(futures):
            item=futures[future]
            try:assessments[item['id']]=future.result()
            except Exception as error:
                errors.append(item['id']);emit('quality_error',id=item['id'],error=str(error))
            if (len(assessments)+len(errors))%8==0:
                emit('quality',completed=len(assessments),total=len(items),errors=len(errors))
    if errors:raise RuntimeError(f'{len(errors)} quality reads failed. Run the same command to resume.')
    selected=select_dates(items,assessments,config)
    selection=dict(items=[x['id'] for x in selected],assessments=assessments)
    write_json(output/'selection.json',selection)
    emit('selected',observations=len(selected),dates=[x['properties']['datetime'][:10] for x in selected])
    for i,item in enumerate(selected):
        path=scenes/(item['id']+'.npz')
        if not path.exists():
            bands=[None]*10
            with np.load(quality/(item['id']+'.npz'),allow_pickle=False) as q:
                native=q['native']&(q['scl']!=1);scl=q['scl'].copy()
            with ThreadPoolExecutor(max_workers=config['workers']) as pool:
                pending={pool.submit(read_asset,item,key,config):b for b,key in enumerate(ASSETS)}
                try:
                    for future in as_completed(pending):
                        b=pending[future];bands[b],valid=future.result();native&=valid
                except Exception:
                    for f in pending:f.cancel()
                    raise
            save_scene(path,image=np.stack(bands),native=native,scl=scl)
        emit('imagery',completed=i+1,total=len(selected),date=item['properties']['datetime'][:10])
    dates=[x['properties']['datetime'][:10] for x in selected]
    doy=[date.fromisoformat(d).timetuple().tm_yday for d in dates]
    order=np.argsort(doy,kind='stable').tolist()
    cube_path=output/'observations.npy'
    temporary=output/'observations.pending.npy'
    cube=np.lib.format.open_memmap(temporary,mode='w+',dtype='float32',shape=(len(selected),10,*config['shape']))
    valid=np.ones(config['shape'],dtype=bool)
    clear_count=np.zeros(config['shape'],dtype=np.uint16)
    for i,item in enumerate(selected):
        with np.load(scenes/(item['id']+'.npz'),allow_pickle=False) as d:
            if d['image'].shape!=(10,*config['shape']) or not np.isfinite(d['image']).all():
                raise ValueError('Corrupt scene cache')
            cube[i]=d['image'];valid&=d['native']
            clear_count+=np.isin(d['scl'],[4,5,6])&d['native']
    cube.flush();del cube
    temporary.replace(cube_path)
    valid&=clear_count>=config['minimum_clear_observations']
    if not valid.any():raise RuntimeError('No pixels meet the native/clear observation policy')
    np.save(output/'valid-mask.npy',valid,allow_pickle=False)
    np.save(output/'clear-count.npy',clear_count,allow_pickle=False)
    # One real low-cloud acquisition for the full-region preview.
    best=max(range(len(selected)),key=lambda i:assessments[selected[i]['id']]['clear_fraction'])
    h,w=config['shape'];side=config['default_selection_pixels']
    image_hash=digest(cube_path);mask_hash=digest(output/'valid-mask.npy')
    version=fingerprint(dict(image=image_hash,valid=mask_hash,config=semantic))
    patch=dict(id=config['id'],name=config['name'],region='Normandy',source='Sentinel-2 COG',
               split='external',season=config['season'],crs=config['crs'],origin=config['origin'],
               shape=config['shape'],geometry=rectangle(config),
               default_geometry=rectangle(config,(h-side)//2,(w-side)//2,side,side),
               image_path=f'cog/{config["slug"]}/observations.npy',
               valid_mask_path=f'cog/{config["slug"]}/valid-mask.npy',
               frame_order=order,doy=[doy[i] for i in order],dates=dates,
               acquisition_count=len(selected),model_observations=len(selected),
               preview_index=best,preview_date=dates[best],first_date=min(dates),last_date=max(dates),
               max_analysis_windows=config['max_analysis_windows'],sha256=image_hash,dataset_version=version)
    gaps=np.diff([date.fromisoformat(d).toordinal() for d in dates])
    report=dict(source=API,accuracy_validated=False,region_id=config['id'],area_ha=h*w*.01,
                observations=len(selected),dates=dates,band_order=BANDS,frame_order=order,
                max_gap_days=int(max(gaps,default=0)),valid_fraction=float(valid.mean()),
                minimum_clear_observations=config['minimum_clear_observations'],
                cloud_policy='Whole-date clear fraction threshold; remaining cloudy reflectances retained. No imputation.',
                reflectance='asset scale/offset then x10000; bilinear bands, nearest SCL',
                dataset_version=version,elapsed_seconds=round(time.monotonic()-started,2),
                files={name:dict(bytes=(output/name).stat().st_size,sha256=digest(output/name))
                       for name in ['observations.npy','valid-mask.npy','clear-count.npy']},
                provenance=selected)
    write_json(output/'report.json',report)
    # Atomic publication: the app never advertises an unfinished cube.
    published=data_dir/'cog/catalog.json'
    with (published.parent/'catalog.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        previous=json.loads(published.read_text()) if published.exists() else dict(patches=[])
        previous['patches']=[p for p in previous['patches'] if p['id']!=patch['id']]+[patch]
        previous['season']=config['season']
        write_json(published,previous)
    emit('ready',region_id=config['id'],area_ha=h*w*.01,observations=len(selected),valid_fraction=report['valid_fraction'])
    return report


def export_dataset(data_dir,destination,include_cache=False):
    """Completed deploy data, or a resumable preparation checkpoint, as tar.gz."""
    data_dir=Path(data_dir);destination=Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix(destination.suffix+'.part')
    files=[]
    for path in (data_dir/'cog').rglob('*'):
        if not path.is_file() or path.is_symlink() or path.name.endswith(('.tmp','.part')) or '.pending.' in path.name:
            continue
        if not include_cache and any(p.startswith('cache-') for p in path.parts):continue
        files.append(path)
    if not files:raise ValueError('No COG data to export')
    with tarfile.open(temporary,'w:gz') as archive:
        for path in sorted(files):archive.add(path,arcname=path.relative_to(data_dir).as_posix(),recursive=False)
    temporary.replace(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(f'{digest(destination)}  {destination.name}\n')
    return destination


def restore_dataset(source,data_dir):
    """Support both a Kaggle auto-extracted directory and an archive."""
    import shutil
    source=Path(source);data_dir=Path(data_dir)
    if (data_dir/'cog').exists():raise ValueError('Restore only into a fresh data directory')
    data_dir.mkdir(parents=True,exist_ok=True)
    if source.is_dir():
        if not (source/'cog').is_dir():raise ValueError('Choose the directory containing cog/')
        shutil.copytree(source/'cog',data_dir/'cog')
    else:
        with tarfile.open(source) as archive:
            for member in archive.getmembers():
                path=(data_dir/member.name).resolve()
                if not path.is_relative_to(data_dir.resolve()) or not (member.isfile() or member.isdir()):
                    raise ValueError('Unsafe archive member')
            archive.extractall(data_dir,filter='data')
