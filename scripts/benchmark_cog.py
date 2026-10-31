"""Experimental full-season COG benchmark; does not switch the app's provider.

Reads all AOI scene-classification windows, then 10 bands for both a uniformly
sampled 60-observation series and a quality-screened series. Runs the real
checkpoint, saves actual model inputs, exports and per-stage measurements.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
import html
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import rasterio
from rasterio.enums import Resampling
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_geom

from imagery import BANDS, new_grid, season_dates
from inference import DATA, Engine, export_result, grid, preprocess, write_json

API = 'https://earth-search.aws.element84.com/v1'
COLLECTION = 'sentinel-2-c1-l2a'
ASSETS = ('blue', 'green', 'red', 'rededge1', 'rededge2', 'rededge3',
          'nir', 'nir08', 'swir16', 'swir22')
ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',
           CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif', GDAL_HTTP_TIMEOUT='30',
           GDAL_HTTP_MAX_RETRY='2', GDAL_HTTP_RETRY_DELAY='1',
           CPL_CURL_VERBOSE=True)


def search(geometry, season):
    start, end = season_dates(season)
    ring = np.asarray(geometry['coordinates'][0])
    bbox = [float(ring[:, 0].min()), float(ring[:, 1].min()),
            float(ring[:, 0].max()), float(ring[:, 1].max())]
    # Collection-1 has gaps in the historical archive on this tile. Merge
    # the original catalog; prefer C1 where present and record every source.
    body = dict(collections=[COLLECTION, 'sentinel-2-l2a'], bbox=bbox,
                datetime=start+'/'+end, limit=100)
    items = {}
    with httpx.Client(timeout=60) as client:
        for _ in range(10):
            for attempt in range(3):
                response = client.post(API+'/search', json=body)
                if response.status_code not in (500, 502, 503, 504) or attempt == 2:
                    response.raise_for_status()
                    break
                time.sleep(2)
            result = response.json()
            for item in result['features']:
                items[(item['collection'], item['id'])] = item
            following = next((link for link in result.get('links', [])
                              if link.get('rel') == 'next'), None)
            if not following or not result['features']:
                break
            # Keep the query on the known API rather than following a new host.
            body = following['body']
        else:
            raise RuntimeError('Too many catalog pages for this benchmark.')
    return sorted(items.values(), key=lambda item: item['properties']['datetime'])


def containing_tile(items, patch, selected):
    tiles = {}
    for item in items:
        tiles.setdefault(item['properties']['grid:code'], []).append(item)
    candidates = []
    for tile, entries in tiles.items():
        footprint = transform_geom('EPSG:4326', patch['crs'], entries[0]['geometry'])
        coverage = geometry_mask([footprint], out_shape=tuple(patch['shape']),
                                 transform=grid(patch), invert=True)
        if coverage[selected].all():
            candidates.append((len(entries), tile, entries))
    if not candidates:
        raise RuntimeError('Benchmark AOI must be contained in one Sentinel-2 tile.')
    _, tile, entries = max(candidates, key=lambda candidate: candidate[0])
    # One actual calendar date per observation; processing duplicates are not
    # extra days. Prefer the latest reprocessing of a given acquisition day.
    dates = {}
    def rank(item):
        return (item['collection'] == COLLECTION,
                float(item['properties'].get('s2:processing_baseline', 0)),
                item['properties'].get('updated', ''))
    for item in entries:
        day = item['properties']['datetime'][:10]
        old = dates.get(day)
        if old is None or rank(item) > rank(old):
            dates[day] = item
    return tile, sorted(dates.values(), key=lambda item: item['properties']['datetime'])


def read_asset(item, key, patch, quality=False):
    asset = item['assets'][key]
    url = asset['href']
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname.endswith('.amazonaws.com')
            or not parsed.path.endswith('.tif') or asset.get('storage:requester_pays')):
        raise RuntimeError('Expected a public HTTPS COG asset.')
    band = asset['raster:bands'][0]
    nodata = band['nodata']
    height, width = patch['shape']
    with rasterio.Env(**ENV), rasterio.open(url) as source:
        with WarpedVRT(source, crs=patch['crs'], transform=grid(patch),
                       width=width, height=height, src_nodata=nodata,
                       nodata=nodata, dtype='float32',
                       resampling=Resampling.nearest if quality else Resampling.bilinear) as aligned:
            raw = aligned.read(1)
    valid = np.isfinite(raw) & (raw != nodata)
    if quality:
        return raw.astype(np.uint8), valid
    # Metadata scale/offset are authoritative, including Collection-1's BOA
    # offset. Convert physical reflectance to the checkpoint's DN scale.
    scale, offset = float(band['scale']), float(band.get('offset', 0))
    image = (raw*np.float32(scale)+np.float32(offset))*np.float32(10000)
    image[~valid] = 0
    return image, valid


def save_scene(path, **values):
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as handle:
        np.savez_compressed(handle, **values)
    temporary.replace(path)


def quality_scene(item, patch, selected, directory):
    started = time.monotonic()
    scl, native = read_asset(item, 'scl', patch, quality=True)
    clear = np.isin(scl, (4, 5, 6)) & native
    name = item['id']
    save_scene(directory/(name+'.npz'), scl=scl, native=native, clear=clear)
    return dict(id=name, date=item['properties']['datetime'][:10],
                tile_cloud_percent=item['properties']['eo:cloud_cover'],
                aoi_clear_fraction=round(float(clear[selected].mean()), 6),
                quality_seconds=round(time.monotonic()-started, 3))


def reflectance_scene(item, patch, directory):
    started = time.monotonic()
    bands, native = [], np.ones(tuple(patch['shape']), dtype=bool)
    for key in ASSETS:
        image, valid = read_asset(item, key, patch)
        bands.append(image)
        native &= valid
    save_scene(directory/(item['id']+'.npz'), image=np.stack(bands), native=native)
    return round(time.monotonic()-started, 3)


def sample(items, maximum=60):
    return [items[index] for index in np.linspace(0, len(items)-1,
                                                min(maximum, len(items)), dtype=int)]


def run_series(name, items, quality, patch, selected, directory, engine):
    started = time.monotonic()
    output = directory/name
    output.mkdir(exist_ok=True)
    dates = [item['properties']['datetime'][:10] for item in items]
    doys = [date(2001, day.month, min(day.day, 28) if day.month == 2 else day.day).timetuple().tm_yday
            for day in map(date.fromisoformat, dates)]
    order = sorted(range(len(items)), key=lambda index: (doys[index], dates[index]))
    series = np.empty((len(items), 10, *patch['shape']), dtype=np.float32)
    valid, clear_count = selected.copy(), np.zeros(tuple(patch['shape']), dtype=np.uint16)
    for index, item in enumerate(items):
        with np.load(directory/'reflectance'/(item['id']+'.npz'), allow_pickle=False) as data:
            series[index] = data['image']
            valid &= data['native']
        with np.load(directory/'quality'/(item['id']+'.npz'), allow_pickle=False) as data:
            valid &= data['native'] & (data['scl'] != 1)
            clear_count += data['clear']
    valid &= clear_count >= 3
    if not valid.any():
        raise RuntimeError(f'{name}: no native valid pixels with at least three clear observations.')
    series = series[order]
    ordered_doys = [doys[index] for index in order]
    ordered_dates = [dates[index] for index in order]
    np.save(output/'observations.npy', series, allow_pickle=False)
    height, width = patch['shape']
    windows = [(row, col) for row in range(0, height, 24) for col in range(0, width, 24)
               if valid[row:row+24, col:col+24].any()]
    row, col = windows[0]
    tensor = preprocess(series[:, :, row:row+24, col:col+24], ordered_doys).numpy()
    np.save(output/'model-input-window.npy', tensor, allow_pickle=False)
    prepared_seconds = time.monotonic()-started
    started = time.monotonic()
    labels, confidence = np.zeros((height, width), np.uint8), np.zeros((height, width), np.float32)
    for row, col in windows:
        labels[row:row+24, col:col+24], confidence[row:row+24, col:col+24] = engine.predict(
            series[:, :, row:row+24, col:col+24], ordered_doys)
    inference_seconds = time.monotonic()-started
    started = time.monotonic()
    metadata = dict(source='Earth Search / Sentinel-2 COG · experimental',
                    collections=sorted({item['collection'] for item in items}),
                    imagery_provenance=[dict(id=item['id'], collection=item['collection'],
                        date=item['properties']['datetime'],
                        processing_baseline=item['properties'].get('s2:processing_baseline'),
                        scaling={key:item['assets'][key]['raster:bands'][0] for key in ASSETS}) for item in items],
                    season=ARGS.season, observations=len(items),
                    padded_frames=60-len(items), dates=sorted(dates),
                    selected_pixels=int(selected.sum()), excluded_pixels=int((selected & ~valid).sum()),
                    checkpoint_sha256=engine.sha256, accuracy_validated=False,
                    quality_policy=quality, band_order=list(BANDS), reflectance_scale=10000,
                    frame_order='DOY, acquisition date', model_input_shape=list(tensor.shape))
    result = export_result(output, patch, labels, confidence, valid, metadata)
    export_seconds = time.monotonic()-started
    gaps = np.diff([date.fromisoformat(day).toordinal() for day in sorted(dates)])
    report = dict(observations=len(items), padded_frames=60-len(items), windows=len(windows),
                  imagery_ready_seconds=round(max((directory/'reflectance'/(item['id']+'.npz')).stat().st_mtime
                                                 for item in items)
                                              -(directory/'request.json').stat().st_mtime, 3),
                  first_date=min(dates), last_date=max(dates),
                  max_gap_days=int(gaps.max()) if len(gaps) else 0,
                  months=dict(sorted(Counter(day[:7] for day in dates).items())),
                  model_input_shape=list(tensor.shape), model_input_dtype=str(tensor.dtype),
                  padded_tensor_zero=bool((tensor[len(items):] == 0).all()),
                  model_frame_dates=ordered_dates, model_frame_doy=ordered_doys,
                  preparation_seconds=round(prepared_seconds, 3),
                  inference_seconds=round(inference_seconds, 3), export_seconds=round(export_seconds, 3),
                  labeled_pixels=int(valid.sum()), result_directory=str(output))
    return report, result


def contact_sheet(items, assessments, patch, directory, filename='observations-60.jpg'):
    cell_w, cell_h, columns = 132, 118, 10
    sheet = Image.new('RGB', (columns*cell_w, ((len(items)+columns-1)//columns)*cell_h), 'white')
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
    for index, item in enumerate(items):
        with np.load(directory/'reflectance'/(item['id']+'.npz'), allow_pickle=False) as data:
            rgb = np.uint8(np.clip(data['image'][[2, 1, 0]]/3000, 0, 1)**(1/1.3)*255)
        thumb = Image.fromarray(rgb.transpose(1, 2, 0))
        thumb.thumbnail((120, 86))
        x, y = index%columns*cell_w, index//columns*cell_h
        sheet.paste(thumb, (x+(cell_w-thumb.width)//2, y+16))
        assessment = assessments[item['id']]
        draw.text((x+4, y), assessment['date'], fill='#172b3a', font=font)
        color = '#176448' if assessment['aoi_clear_fraction'] >= .5 else '#a53030'
        draw.text((x+4, y+102), f"Clear {assessment['aoi_clear_fraction']:.0%}", fill=color, font=font)
    sheet.save(directory/filename, quality=92)


def progress(phase, **values):
    record = dict(phase=phase, **values)
    write_json(OUT/'progress.json', record)
    print(json.dumps(record), flush=True)


def main():
    started = time.monotonic()
    geometry = json.loads(ARGS.geometry.read_text())
    if geometry.get('type') == 'Feature':
        geometry = geometry['geometry']
    from app import AnalysisRequest
    geometry = AnalysisRequest(geometry=geometry, season=ARGS.season).geometry
    patch, selected = new_grid(geometry)
    write_json(OUT/'request.json', dict(geometry=geometry, season=ARGS.season, workers=ARGS.workers))
    items = search(geometry, ARGS.season)
    tile, items = containing_tile(items, patch, selected)
    if len(items) < 60:
        raise RuntimeError(f'Only {len(items)} distinct days in this season: cannot benchmark 60 real days.')
    write_json(OUT/'catalog.json', dict(tile=tile, features=items))
    catalog_seconds = time.monotonic()-started
    progress('catalog', days=len(items), area_ha=round(int(selected.sum())*.01, 2),
             seconds=round(catalog_seconds, 3), grid_shape=patch['shape'])
    phase_started = time.monotonic()
    assessments = {}
    with ThreadPoolExecutor(max_workers=ARGS.workers) as pool:
        tasks = {pool.submit(quality_scene, item, patch, selected, OUT/'quality'): item for item in items}
        for future in as_completed(tasks):
            assessment = future.result()
            assessments[assessment['id']] = assessment
            progress('quality', completed=len(assessments), total=len(items),
                     date=assessment['date'], clear=assessment['aoi_clear_fraction'])
    quality_seconds = time.monotonic()-phase_started
    raw_items = sample(items)
    screened = sample([item for item in items if assessments[item['id']]['aoi_clear_fraction'] >= .5])
    if len(screened) < 3:
        raise RuntimeError('Too few usable dates in a complete season.')
    needed = {item['id']: item for item in raw_items+screened}
    write_json(OUT/'assessments.json', dict(items=[assessments[item['id']] for item in items],
                                         raw_ids=[item['id'] for item in raw_items],
                                         screened_ids=[item['id'] for item in screened]))
    progress('reflectance', raw_days=len(raw_items), usable_days=len(screened), total=len(needed))
    phase_started = time.monotonic()
    scene_seconds = {}
    with ThreadPoolExecutor(max_workers=ARGS.workers) as pool:
        tasks = {pool.submit(reflectance_scene, item, patch, OUT/'reflectance'): item for item in needed.values()}
        for future in as_completed(tasks):
            item = tasks[future]
            scene_seconds[item['id']] = future.result()
            progress('reflectance', completed=len(scene_seconds), total=len(needed),
                     date=item['properties']['datetime'][:10],
                     elapsed_seconds=round(time.monotonic()-phase_started, 1))
    acquisition_seconds = time.monotonic()-phase_started
    progress('inference', message='Loading real checkpoint and running both time series')
    phase_started = time.monotonic()
    engine = Engine()
    model_load_seconds = time.monotonic()-phase_started
    raw_report, _ = run_series('raw-60', raw_items, '60 real days; cloudy frames retained for latency test',
                               patch, selected, OUT, engine)
    screened_report, _ = run_series('quality-screened', screened,
                                    'AOI clear fraction >=50%; SCL 4/5/6; no imputation',
                                    patch, selected, OUT, engine)
    cold_seconds = time.monotonic()-started
    # Cache replay: disk reads, preprocessing, inference and exports; same
    # acquisitions and same AOI, with no remote reads and no second model load.
    replay_started = time.monotonic()
    replay, _ = run_series('cache-replay', screened, 'Same screened series from local AOI files',
                           patch, selected, OUT, engine)
    replay_seconds = time.monotonic()-replay_started
    contact_sheet(raw_items, assessments, patch, OUT)
    contact_sheet(screened, assessments, patch, OUT, 'observations-quality.jpg')
    log = (OUT/'http.log').read_text(errors='replace')
    ranges = re.findall(r'< Content-Range: bytes (\d+)-(\d+)/(\d+)', log, re.I)
    payload_bytes = sum(int(last)-int(first)+1 for first, last, _ in ranges)
    report = dict(source='Earth Search Sentinel-2 L2A COG',
                  collections=sorted({item['collection'] for item in items}),
                  experimental=True, accuracy_validated=False,
                  production_provider_changed=False, season=ARGS.season, tile=tile,
                  area_ha=round(int(selected.sum())*.01, 2), grid_shape=patch['shape'], workers=ARGS.workers,
                  catalog_distinct_days=len(items), band_order=list(BANDS),
                  quality_mask='SCL nearest; 4 vegetation, 5 bare soil, 6 water counted clear',
                  radiometry='Per-asset raster:bands scale/offset, then reflectance x10000',
                  selected_clear_threshold=.5, benchmark_downloaded_days=len(needed),
                  range_requests=len(ranges), range_payload_mib=round(payload_bytes/1024**2, 2),
                  network_measurement='Sum of HTTP Content-Range payloads; includes masks/retries, excludes headers/TLS/catalog',
                  catalog_seconds=round(catalog_seconds, 3), quality_scan_seconds=round(quality_seconds, 3),
                  ten_band_acquisition_seconds=round(acquisition_seconds, 3),
                  model_load_seconds=round(model_load_seconds, 3), cold_total_seconds=round(cold_seconds, 3),
                  cache_replay_total_seconds=round(replay_seconds, 3),
                  raw_60=raw_report, quality_screened=screened_report, cache_replay=replay,
                  per_scene_seconds=scene_seconds, checkpoint_sha256=engine.sha256)
    write_json(OUT/'report.json', report)
    write_report(report)
    progress('done', report=str(OUT/'report.json'), cold_seconds=report['cold_total_seconds'],
             transfer_mib=report['range_payload_mib'], usable_days=len(screened), pad=60-len(screened))


def write_report(report):
    raw, screened = report['raw_60'], report['quality_screened']
    rows = ''.join(f'<tr><td>{month}</td><td>{raw["months"].get(month, 0)}</td><td>{screened["months"].get(month, 0)}</td></tr>'
                   for month in sorted(set(raw['months']) | set(screened['months'])))
    document = f'''<!doctype html><meta charset="utf-8"><title>TSViT full-season COG benchmark</title>
<style>body{{font:16px system-ui;max-width:1100px;margin:32px auto;padding:0 20px;color:#23313b}}
table{{border-collapse:collapse;display:block;overflow-x:auto}}td,th{{padding:8px 20px;border:1px solid #ddd}}img{{max-width:100%}}code{{background:#eee;padding:3px}}</style>
<h1>TSViT: thử cả mùa {html.escape(report['season'])}</h1>
<p>Vùng {report['area_ha']} ha · {report['catalog_distinct_days']} ngày chụp · 10 kênh · 4 worker.</p>
<p>Tải/căn chỉnh/lọc mây và chạy hai chuỗi: <b>{report['cold_total_seconds']:.1f} giây</b>.
Payload HTTP: <b>{report['range_payload_mib']:.2f} MiB</b>.
Chạy lại chuỗi đã lọc từ cache: <b>{report['cache_replay_total_seconds']:.2f} giây</b>.</p>
<p>Đọc {report['benchmark_downloaded_days']} ngày riêng biệt để so sánh hai chuỗi; không phải một yêu cầu phân tích luôn cần tải từng đó ngày.</p>
<table><tr><th>Đầu vào</th><th>Ảnh thật</th><th>Pad</th><th>Ảnh sẵn sàng từ đầu phép thử</th><th>Inference CPU</th><th>Khoảng trống lớn nhất</th></tr>
<tr><td>Đủ 60 ngày, còn ảnh mây; đo latency</td><td>{raw['observations']}</td><td>{raw['padded_frames']}</td><td>{raw['imagery_ready_seconds']/60:.1f} phút</td><td>{raw['inference_seconds']:.2f}s</td><td>{raw['max_gap_days']} ngày</td></tr>
<tr><td>Vùng chọn rõ ≥50%; SCL 4/5/6</td><td>{screened['observations']}</td><td>{screened['padded_frames']}</td><td>{screened['imagery_ready_seconds']/60:.1f} phút</td><td>{screened['inference_seconds']:.2f}s</td><td>{screened['max_gap_days']} ngày</td></tr></table>
<p>Tensor mỗi ô: <code>60 × 24 × 24 × 11</code>. Kênh cuối là DOY; pad toàn zero.
File <a href="raw-60/model-input-window.npy">tensor đủ 60 ngày</a>,
<a href="quality-screened/model-input-window.npy">tensor sau lọc mây</a>, <a href="report.json">báo cáo JSON</a>.</p>
<h2>Phân bố quan sát theo tháng</h2><table><tr><th>Tháng</th><th>Chuỗi 60</th><th>Sau lọc mây</th></tr>{rows}</table>
<h2>60 ảnh thật trải qua mùa</h2><p>Clear là tỷ lệ SCL rõ tại vùng chọn; ảnh RGB chỉ để quan sát.</p>
<img src="observations-60.jpg" alt="60 actual dated RGB windows">
<h2>{screened['observations']} ảnh thực sau lọc mây; pad {screened['padded_frames']} vị trí</h2>
<img src="observations-quality.jpg" alt="Actual quality-screened observations">
<h2>Kết quả chạy checkpoint</h2><img src="quality-screened/classification.png" style="width:360px;image-rendering:pixelated">
<p>Thử nghiệm nguồn Sen2Cor/COG khác THEIA/MAJA; chưa kiểm định độ chính xác bằng nhãn thật.
Chuỗi đủ 60 ngày còn mây chỉ dùng đo latency. Chưa thay nguồn mặc định của ứng dụng.</p>'''
    (OUT/'report.html').write_text(document)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--season', default='2018–2019')
    parser.add_argument('--workers', type=int, choices=(1, 2, 4), default=4)
    parser.add_argument('--output', type=Path, required=True)
    ARGS = parser.parse_args()
    OUT = ARGS.output.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    for name in ('quality', 'reflectance'):
        (OUT/name).mkdir()
    # Capture native GDAL HTTP diagnostics for actual ranged-transfer accounting.
    # Public URLs only: this script never reads or sends the GEODES key.
    import os
    with (OUT/'http.log').open('w') as trace:
        os.dup2(trace.fileno(), 2)
        try:
            main()
        except Exception as error:
            write_json(OUT/'progress.json', dict(phase='error', message=str(error)))
            raise
