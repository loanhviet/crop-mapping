"""THEIA/GEODES acquisition and alignment. No HTTP/UI or model dependency.

GEODES exposes whole-scene ZIPs and charges each download request to quota.
Download once per scene, crop locally, and cache aligned AOI arrays. The model
and UI can use a different provider later without changing tensor/export code.
"""
from __future__ import annotations

from datetime import date
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import time
from urllib.parse import quote, urljoin, urlsplit
import xml.etree.ElementTree as ET
import zipfile

import httpx
import numpy as np
from pyproj import Geod, Transformer
import rasterio
from rasterio.enums import Resampling
from rasterio.features import is_valid_geom
from rasterio.transform import array_bounds
from rasterio.warp import transform_bounds, transform_geom
from rasterio.vrt import WarpedVRT

from inference import DATA, ROOT, grid, selection_mask, web_png, write_json

PORTAL = 'https://geodes-portal.cnes.fr'
COLLECTION = 'THEIA_REFLECTANCE_SENTINEL2_L2A'
BANDS = ('B2', 'B3', 'B4', 'B5', 'B6', 'B7', 'B8', 'B8A', 'B11', 'B12')


class ImageryError(ValueError):
    """Safe, actionable messages that can be sent to the UI."""


class Cancelled(Exception):
    pass


def check_cancel(cancel):
    if cancel.is_set():
        raise Cancelled()


def setting(name, default=''):
    """Read simple KEY=value settings without executing a user's .env as code."""
    if name in os.environ:
        return os.environ[name]
    path = ROOT / '.env'
    if path.exists():
        for line in path.read_text().splitlines():
            if line.strip().startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key.strip() == name:
                return value.strip().strip('\"\'')
    return default


def season_dates(season):
    match = re.fullmatch(r'(20\d{2})[–-](20\d{2})', season)
    if not match:
        raise ImageryError('Choose a season in YYYY–YYYY format.')
    start, end = map(int, match.groups())
    if end != start+1 or start < 2016 or date(end, 9, 30) >= date.today():
        raise ImageryError('Choose a completed season from 2016–2017 onwards.')
    return f'{start}-10-01T00:00:00Z', f'{end}-09-30T23:59:59Z'


def new_grid(geometry):
    ring = np.asarray(geometry['coordinates'][0], dtype=float)
    if not is_valid_geom(geometry) or not (-80 <= ring[:, 1].min() <= ring[:, 1].max() <= 84):
        raise ImageryError('Choose a non-empty area between 80°S and 84°N.')
    if np.ptp(ring[:, 0]) > 1 or np.ptp(ring[:, 1]) > 1:
        raise ImageryError('Choose a smaller area for local analysis.')
    area, _ = Geod(ellps='WGS84').polygon_area_perimeter(ring[:, 0], ring[:, 1])
    if abs(area) < 100:
        raise ImageryError('Select an area of at least 100 m².')
    lon, lat = ring[:-1].mean(axis=0)
    zone = min(60, max(1, math.floor((lon+180)/6)+1))
    crs = f'EPSG:{(32600 if lat >= 0 else 32700)+zone}'
    projected = np.asarray(transform_geom('EPSG:4326', crs, geometry)['coordinates'][0])
    # Canonical 24-pixel cells let nearby selections reuse identical crops.
    west = math.floor((projected[:, 0].min()+1e-6)/240)*240
    north = math.ceil((projected[:, 1].max()-1e-6)/240)*240
    width = max(1, math.ceil((projected[:, 0].max()-west-1e-6)/240))*24
    height = max(1, math.ceil((north-projected[:, 1].min()-1e-6)/240))*24
    maximum = int(setting('CROP_MAX_GRID_PIXELS', '160000'))
    if width*height > maximum:
        raise ImageryError(f'Choose a smaller area: the bounding grid can cover up to {maximum*.01:g} ha on this local server.')
    convert = Transformer.from_crs(crs, 4326, always_xy=True)
    corners = [(west,north),(west+width*10,north),(west+width*10,north-height*10),
               (west,north-height*10),(west,north)]
    patch = dict(origin=[west,north], shape=[height,width], crs=crs,
                 geometry=dict(type='Polygon', coordinates=[[convert.transform(*p) for p in corners]]))
    return patch, selection_mask(patch, geometry)


def safe_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not (parts.hostname == 'cnes.fr' or (parts.hostname or '').endswith('.cnes.fr')):
        raise ImageryError('The imagery service returned an unsupported download host.')
    return parts._replace(path=quote(parts.path, safe='/%')).geturl()


class Download:
    """Bound network traffic and keep API credentials on the GEODES host."""
    def __init__(self, client, key, cancel, update):
        self.client, self.key, self.cancel, self.update = client, key, cancel, update
        self.transferred = 0
        self.limit = int(float(setting('GEODES_MAX_DOWNLOAD_GB', '64'))*1024**3)

    def get(self, url, headers=None):
        url = safe_url(url)
        retries, redirects, quota_waits = 0, 0, 0
        while True:
            check_cancel(self.cancel)
            request_headers = dict(headers or {})
            if urlsplit(url).hostname == urlsplit(PORTAL).hostname:
                request_headers['X-API-Key'] = self.key
            response = self.client.send(self.client.build_request('GET', url, headers=request_headers), stream=True)
            if response.is_redirect:
                destination = response.headers.get('location', '')
                response.close()
                url = safe_url(urljoin(url, destination))
                redirects += 1
                if redirects > 5:
                    raise ImageryError('GEODES returned too many download redirects.')
                continue
            if response.status_code >= 400:
                fragments, size = [], 0
                for fragment in response.iter_bytes(1024):
                    fragments.append(fragment)
                    size += len(fragment)
                    if size >= 8192: break
                message = b''.join(fragments).decode('utf-8',errors='replace').lower()
                retry_header = response.headers.get('retry-after','3600')
                response.close()
                if response.status_code == 429 or 'quota' in message or 'too many requests' in message:
                    quota_waits += 1
                    if quota_waits > 2:
                        raise ImageryError('GEODES download quota is still exhausted. Retry later; downloaded AOI data has been cached.')
                    seconds = min(3600,max(1,int(retry_header))) if retry_header.isdigit() else 3600
                    retry_at = time.time()+seconds
                    self.update(phase='quota', retry_at=retry_at,
                        message='GEODES download quota reached · waiting for the next available slot. You can cancel and retry later.')
                    while time.time() < retry_at:
                        if self.cancel.wait(min(60,retry_at-time.time())): raise Cancelled()
                    self.update(phase='imagery', retry_at=None, message='Retrying the GEODES image download')
                    continue
                if response.status_code in (500,502,503,504) and retries < 2:
                    retries += 1
                    self.update(message=f'GEODES temporarily unavailable · retrying download ({retries}/2)')
                    if self.cancel.wait(10): raise Cancelled()
                    continue
            if response.status_code in (401, 403):
                response.close()
                raise ImageryError('GEODES rejected the API key or download access. Check your account and GEODES_API_KEY in crop-map/.env.')
            if response.status_code >= 400:
                response.close()
                raise ImageryError('GEODES could not download this product. Check the key and product availability, then retry.')
            return response

    def chunks(self, response):
        scene_bytes = 0
        total = int(response.headers.get('content-length','0'))
        started = time.monotonic()
        try:
            for chunk in response.iter_bytes(1024*1024):
                check_cancel(self.cancel)
                self.transferred += len(chunk)
                scene_bytes += len(chunk)
                if self.transferred > self.limit:
                    raise ImageryError('Download limit reached. Raise GEODES_MAX_DOWNLOAD_GB in .env or choose a different season. No partial prediction was published.')
                self.update(downloaded_mb=round(self.transferred/1024**2, 1),
                    scene_download_percent=round(scene_bytes/total*100,1) if total else None,
                    download_mbps=round(scene_bytes/1024**2/max(time.monotonic()-started,.01),2))
                yield chunk
        finally:
            response.close()


def open_archive(download, url, temporary):
    # One GET per complete scene. Range requests also consume GEODES quota,
    # and seeking a DEFLATE member requires decompressing preceding data.
    response = download.get(url, {'Accept-Encoding': 'identity'})
    path = Path(temporary) / 'scene.zip'
    expected = response.headers.get('content-length')
    if expected and int(expected) > download.limit-download.transferred:
        response.close()
        raise ImageryError('This archive exceeds the remaining download limit. Adjust GEODES_MAX_DOWNLOAD_GB or use cached imagery.')
    with path.open('wb') as stream:
        for chunk in download.chunks(response):
            stream.write(chunk)
    if expected and path.stat().st_size != int(expected):
        raise ImageryError('The satellite archive download was incomplete.')
    download.update(scene_download_percent=100)
    return zipfile.ZipFile(path)


def cache_path(product, patch, reflectance):
    properties = product['properties']
    identity = repr((product['id'],properties.get('version'),properties.get('datetime'),
                     patch['crs'],patch['origin'],patch['shape'],reflectance,'alignment-v1'))
    digest = hashlib.sha256(identity.encode()).hexdigest()
    return DATA / 'imagery' / (digest+'.npz')


def archive_names(archive, reflectance):
    names = archive.namelist()
    chosen = {}
    for band in BANDS:
        pattern = rf'_{reflectance}_B0?{band[1:]}\.tiff?$'
        matches = [name for name in names if re.search(pattern, name, re.I)]
        if len(matches) != 1:
            raise ImageryError(f'THEIA archive must contain exactly one {reflectance} {band} band.')
        chosen[band] = matches[0]
    for mask in ('CLM_R1', 'EDG_R1', 'SAT_R1', 'SAT_R2', 'MG2_R1'):
        matches = [name for name in names if re.search(rf'_{mask}\.tiff?$', name, re.I)]
        if len(matches) != 1:
            raise ImageryError(f'THEIA archive is missing its {mask} quality mask.')
        chosen[mask] = matches[0]
    xml = [name for name in names if re.search(r'_MTD_ALL\.xml$', name, re.I)]
    if len(xml) != 1:
        raise ImageryError('THEIA reflectance metadata is missing.')
    member = archive.getinfo(xml[0])
    if member.file_size > 4*1024**2:
        raise ImageryError('Unexpectedly large THEIA metadata.')
    root = ET.fromstring(archive.read(xml[0]))
    values = {}
    for node in root.iter():
        tag = node.tag.split('}')[-1]
        if tag == 'REFLECTANCE_QUANTIFICATION_VALUE':
            values['quantification'] = node.text
        elif tag == 'SPECIAL_VALUE' and node.attrib.get('name','').lower() == 'nodata':
            values['nodata'] = node.text
    try:
        quantification = float(values['quantification'])
        nodata = float(values['nodata'])
        if not np.isfinite(quantification) or quantification <= 0 or not np.isfinite(nodata):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ImageryError('Invalid THEIA reflectance scaling or nodata metadata.')
    return chosen, quantification, nodata


def read_aligned(archive, name, patch, resampling, nodata):
    """GDAL reads a small AOI through the seekable ZIP member, then reprojects."""
    height, width = patch['shape']
    destination = np.full((height,width), nodata, dtype=np.float32)
    opener = lambda path, mode='rb': archive.open(path)
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'), rasterio.open(name, opener=opener) as source:
        if source.crs is None:
            raise ImageryError('A satellite band has no CRS.')
        bounds = array_bounds(height, width, grid(patch))
        source_bounds = transform_bounds(patch['crs'], source.crs, *bounds, densify_pts=21)
        # Reject an entirely non-overlapping tile before creating a VRT.
        if (source_bounds[2] <= source.bounds.left or source_bounds[0] >= source.bounds.right
                or source_bounds[3] <= source.bounds.bottom or source_bounds[1] >= source.bounds.top):
            return destination
        with WarpedVRT(source, crs=patch['crs'], transform=grid(patch), width=width,
                       height=height, src_nodata=nodata, nodata=nodata,
                       resampling=resampling, dtype='float32') as aligned:
            destination[:] = aligned.read(1)
    return destination


def read_scene(archive, patch, reflectance='FRE'):
    names, quantification, nodata = archive_names(archive, reflectance)
    image = np.stack([read_aligned(archive, names[band], patch, Resampling.bilinear, nodata)
                      for band in BANDS])
    native_valid = np.isfinite(image).all(axis=0) & (image != nodata).all(axis=0)
    # Input DN scale matches the PASTIS normalization constants.
    image *= np.float32(10000/quantification)
    masks = {mask: read_aligned(archive, names[mask], patch, Resampling.nearest, 255).astype(np.uint8)
             for mask in ('CLM_R1', 'EDG_R1', 'SAT_R1', 'SAT_R2', 'MG2_R1')}
    native_valid &= masks['EDG_R1'] == 0
    clear = (native_valid & (masks['CLM_R1'] == 0) & (masks['SAT_R1'] == 0)
             & (masks['SAT_R2'] == 0) & ((masks['MG2_R1'] & 4) == 0))
    image[:, ~native_valid] = 0
    return image, native_valid, clear


class GeodesProvider:
    def status(self):
        return dict(name='THEIA / GEODES', configured=bool(setting('GEODES_API_KEY')),
                    setup_url='https://geodes.cnes.fr/support/api/')

    def search(self, client, geometry, season, cancel):
        start, end = season_dates(season)
        ring = np.asarray(geometry['coordinates'][0])
        bbox = [float(ring[:,0].min()),float(ring[:,1].min()),float(ring[:,0].max()),float(ring[:,1].max())]
        products = {}
        for page in range(1, 51):
            check_cancel(cancel)
            response = client.post(PORTAL+'/api/stac/items', json=dict(page=page, limit=80, bbox=bbox,
                query={'dataset': {'in':[COLLECTION]}, 'start_datetime': {'gte':start,'lte':end},
                       'eo:cloud_cover': {'lte': float(setting('GEODES_MAX_CLOUD_PERCENT','30'))}},
                sortBy=[{'direction':'asc','field':'start_datetime'}]))
            response.raise_for_status()
            features = response.json().get('features', [])
            for feature in features:
                properties = feature['properties']
                # Newest version for an acquisition/tile, not duplicate processing.
                identity = (properties.get('grid:code'), properties['start_datetime'])
                previous = products.get(identity)
                if previous is None or properties.get('datetime','') > previous['properties'].get('datetime',''):
                    products[identity] = feature
            if len(features) < 80:
                return sorted(products.values(), key=lambda item:item['properties']['start_datetime'])
        raise ImageryError('Too many matching products. Choose a smaller area.')

    def plan(self, geometry, season, cancel=None, client=None):
        from threading import Event
        cancel = cancel or Event()
        if client is None:
            with httpx.Client(timeout=httpx.Timeout(60, connect=15)) as connection:
                return self.plan(geometry,season,cancel,connection)
        patch, selected = new_grid(geometry)
        reflectance = setting('GEODES_REFLECTANCE','FRE').upper()
        if reflectance not in ('FRE','SRE'):
            raise ImageryError('GEODES_REFLECTANCE must be FRE or SRE.')
        products = self.search(client, geometry, season, cancel)
        if not products:
            raise ImageryError('No THEIA Sentinel‑2 L2A imagery covers this area and season. Choose a different area or season.')
        # First version handles one tile; a small selection can be moved away
        # from tile boundaries. Never silently omit adjacent-tile pixels.
        tiles = {}
        for product in products:
            code = product['properties'].get('grid:code')
            tiles.setdefault(code, []).append(product)
        containing = []
        for code, items in tiles.items():
            footprint = transform_geom('EPSG:4326', patch['crs'], items[0]['geometry'])
            coverage = rasterio.features.geometry_mask([footprint], out_shape=tuple(patch['shape']),
                                                      transform=grid(patch), invert=True)
            if coverage[selected].all():
                containing.append((len(items),code,items))
        if not containing:
            raise ImageryError('This selection crosses Sentinel‑2 tile coverage. Choose a smaller area within one tile for this version.')
        _, tile, products = max(containing, key=lambda entry:entry[0])
        online = []
        for product in products:
            assets = [asset for name, asset in product['assets'].items()
                      if name.lower().endswith('.zip') and 'data' in asset.get('roles', [])]
            if len(assets) != 1:
                raise ImageryError('The imagery catalogue returned an unsupported archive format.')
            asset = assets[0]
            if 'is online: false' in asset.get('description','').lower():
                continue
            online.append((product,asset))
        if len(online) < 3:
            raise ImageryError('Fewer than three online acquisitions are available. Historical products may need restoration in GEODES before analysis.')
        # Bounded 60-frame input, sample across the full season if necessary.
        if len(online) > 60:
            online = [online[i] for i in np.linspace(0,len(online)-1,60,dtype=int)]
        cached, estimated, unknown = 0, 0, 0
        for product,asset in online:
            if cache_path(product,patch,reflectance).exists():
                cached += 1
                continue
            size = re.search(r'File size:\s*(\d+)\s*bytes',asset.get('description',''),re.I)
            if size: estimated += int(size[1])
            else: unknown += 1
        limit = float(setting('GEODES_MAX_DOWNLOAD_GB','64'))*1024**3
        summary = dict(source='THEIA / GEODES',tile=tile,scenes=len(online),cached_scenes=cached,
            estimated_download_gb=round(estimated/1024**3,2),unknown_sizes=unknown,
            exceeds_download_limit=estimated>limit,download_limit_gb=round(limit/1024**3,2))
        return patch,selected,online,summary

    def prepare(self, geometry, season, directory, cancel, update):
        patch, selected = new_grid(geometry)
        key = setting('GEODES_API_KEY')
        if not key:
            raise ImageryError('Connect THEIA / GEODES first: add GEODES_API_KEY to crop-map/.env, then retry. Create a key at geodes-portal.cnes.fr → My information → Generate.')
        reflectance = setting('GEODES_REFLECTANCE', 'FRE').upper()
        if reflectance not in ('FRE', 'SRE'):
            raise ImageryError('GEODES_REFLECTANCE must be FRE or SRE.')
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            update(progress=2, phase='search', message='Finding Sentinel‑2 L2A acquisitions for your area and season')
            patch, selected, online, plan = self.plan(geometry,season,cancel,client)
            tile = plan['tile']
            if plan['exceeds_download_limit']:
                raise ImageryError(f"This season requires approximately {plan['estimated_download_gb']:.2f} GB of whole-scene downloads, above the {plan['download_limit_gb']:g} GB local limit. Prepare imagery in advance or raise GEODES_MAX_DOWNLOAD_GB deliberately.")
            download = Download(client, key, cancel, update)
            image_path = Path(directory)/'imagery.npy'
            stack = np.lib.format.open_memmap(image_path, mode='w+', dtype='float32',
                                              shape=(len(online),10,*patch['shape']))
            dates, provenance = [], []
            count = 0
            all_native = np.ones(tuple(patch['shape']),dtype=bool)
            clear_count = np.zeros(tuple(patch['shape']),dtype=np.uint16)
            best_clear, preview_image, preview_date = -1, None, None
            try:
                for index, (product,asset) in enumerate(online):
                    check_cancel(cancel)
                    timestamp = product['properties']['start_datetime']
                    progress = 5+round(index/len(online)*60)
                    cache = cache_path(product,patch,reflectance)
                    if cache.exists():
                        update(progress=progress, phase='imagery', scene_download_percent=None,
                               message=f'Reusing prepared imagery · {index+1} / {len(online)} · {timestamp[:10]}')
                        with np.load(cache,allow_pickle=False) as cached:
                            image,native,clear = cached['image'],cached['native'],cached['clear']
                    else:
                        update(progress=progress, phase='imagery', scene_download_percent=0,
                               message=f'Downloading scene · {index+1} / {len(online)} · {timestamp[:10]}')
                        with tempfile.TemporaryDirectory(prefix='crop-map-scene-') as temporary:
                            with open_archive(download, asset['href'], temporary) as archive:
                                check_cancel(cancel)
                                update(message=f'Aligning 10 bands and quality masks · {index+1} / {len(online)}',
                                       scene_download_percent=None)
                                image, native, clear = read_scene(archive, patch, reflectance)
                        cache.parent.mkdir(parents=True,exist_ok=True)
                        temporary_cache = cache.with_suffix('.tmp')
                        with temporary_cache.open('wb') as handle:
                            np.savez_compressed(handle,image=image,native=native,clear=clear)
                        temporary_cache.replace(cache)
                    # Keep raw observations as in PASTIS, reject mostly cloudy AOIs.
                    clear_fraction = float(clear[selected].mean())
                    if clear_fraction < .5:
                        continue
                    stack[count] = image
                    count += 1
                    all_native &= native
                    clear_count += clear
                    dates.append(timestamp[:10])
                    properties = product['properties']
                    provenance.append(dict(id=product['id'], date=timestamp, tile=tile,
                        version=properties.get('version'), processing=properties.get('processing_context'),
                        reflectance=reflectance, clear_fraction=round(clear_fraction,4)))
                    if clear_fraction > best_clear:
                        best_clear = clear_fraction
                        preview_image, preview_date = image[[2,1,0]].copy(), timestamp[:10]
                if count < 3:
                    raise ImageryError('Fewer than three usable acquisitions remain after quality checks. Try another season or area.')
                valid = selected & all_native & (clear_count >= 3)
                if not valid.any():
                    raise ImageryError('Selected pixels have insufficient clear, valid observations. No classification was produced.')
                # Calendar DOY in the checkpoint has 365 embedding slots.
                # Map leap-year dates to a no-leap calendar, merging Feb 29/28.
                doy = []
                for value in dates:
                    d = date.fromisoformat(value)
                    doy.append(date(2001,d.month,min(d.day,28) if d.month == 2 else d.day).timetuple().tm_yday)
                order = sorted(range(count), key=lambda i:(doy[i],dates[i]))
                stack.flush()
                patch.update(dates=dates, doy=doy, frame_order=order, acquisition_count=count, tile=tile)
                rgb = np.uint8(np.clip(preview_image/3000,0,1)**(1/1.3)*255)
                rgba = np.concatenate([rgb,np.uint8(selected[None])*255])
                png, preview_bounds = web_png(rgba, patch['crs'], grid(patch), Resampling.bilinear)
                (Path(directory)/'preview.png').write_bytes(png)
                metadata = dict(source='THEIA / GEODES', collection=COLLECTION, tile=tile,
                    observations=count, dates=sorted(dates), imagery_provenance=provenance,
                    preview_bounds=preview_bounds, preview_date=preview_date,
                    selected_area_ha=round(int(selected.sum())*.01,2), selected_pixels=int(selected.sum()),
                    excluded_pixels=int((selected & ~valid).sum()), downloaded_mb=round(download.transferred/1024**2,1),
                    preprocessing=dict(reflectance=reflectance, band_order=list(BANDS),
                        reflectance_scale=10000, resampling='bilinear', quality='strict CLM, EDG, SAT, snow',
                        frame_order='DOY, acquisition date', leap_days='no-leap calendar',
                        max_frames=60, selection='uniform dates if >60; AOI clear fraction >=0.5',
                        max_tile_cloud_percent=float(setting('GEODES_MAX_CLOUD_PERCENT','30')),
                        min_clear_observations=3, tensor='60 × 24 × 24 × 11'))
                write_json(Path(directory)/'imagery.json',metadata)
                update(progress=68, phase='preprocess', message='Time series aligned · normalizing bands and preparing 24 × 24 windows')
                return patch, valid, metadata
            finally:
                del stack
