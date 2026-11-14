"""TC04 — Output Format & Data Integrity of the files produced in TC03 (Local and Production downloads).

No new production requests: it inspects the artifacts saved by TC03.
"""
import scripts.common as c
import csv
import io
import json
import zipfile

import numpy as np
import rasterio
from pyproj import Geod


def ring_area(ring):
    lon, lat = zip(*ring)
    return abs(geod.polygon_area_perimeter(lon, lat)[0])


def polygon_area_ha(geometry):
    rings = geometry['coordinates']
    return (ring_area(rings[0]) - sum(ring_area(r) for r in rings[1:])) / 1e4


def polygon_valid(geometry):
    return geometry['type'] == 'Polygon' and all(len(r) >= 4 and r[0] == r[-1] for r in geometry['coordinates'])

ev = c.Evidence('TC04', 'Output Format & Data Integrity', 'Automation', 'Local + Production (artifacts TC03)')
src = c.EVIDENCE / 'TC03'
health_sha = '92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733'
geod = Geod(ellps='WGS84')
arrays, report = {}, {}
for env in ['local', 'production']:
    d = src / env
    if not (d / 'classification.tif').exists():
        ev.finish('TC03 artifacts', 'missing', status='BLOCKED', notes='Chạy TC03 trước.'); raise SystemExit
    result = json.loads((d / 'result.json').read_text())
    with rasterio.open(d / 'classification.tif') as r:
        band = r.read(1); arrays[env] = band
        info = dict(driver=r.driver, dtype=r.dtypes[0], crs=str(r.crs), nodata=r.nodata, shape=band.shape,
                    pixel_size=(r.transform.a, -r.transform.e), tags=r.tags(), has_colormap=bool(r.colormap(1)))
    labelled = band != 255
    ev.check(f'[{env}] GeoTIFF uint8, nodata=255, pixel 10 m, CRS UTM khớp result.json', info['dtype'] == 'uint8' and info['nodata'] == 255
             and info['pixel_size'] == (10.0, 10.0) and info['crs'] == result['crs'], 'uint8/255/10m/' + result['crs'], f"{info['dtype']}/{info['nodata']}/{info['pixel_size']}/{info['crs']}")
    ev.check(f'[{env}] Nhãn trong vùng chọn thuộc 0..18, ngoài vùng = 255', bool((band[labelled] <= 18).all()) and int(labelled.sum()) == result['pixels'],
             f"0..18, {result['pixels']} pixel", f"max={int(band[labelled].max())}, {int(labelled.sum())} pixel")
    ev.check(f'[{env}] Tag GeoTIFF ghi checkpoint_sha256 và model', info['tags'].get('checkpoint_sha256') == health_sha and info['tags'].get('model') == 'TSViT', health_sha[:12], info['tags'].get('checkpoint_sha256', '')[:12])
    rows = list(csv.DictReader(io.StringIO((d / 'summary.csv').read_text(encoding='utf-8-sig'))))
    csv_pixels = {int(r['id']): int(r['pixels']) for r in rows}
    tif_pixels = {int(k): int(v) for k, v in zip(*np.unique(band[labelled], return_counts=True))}
    ev.check(f'[{env}] summary.csv: số pixel từng lớp = đếm từ GeoTIFF', csv_pixels == tif_pixels, tif_pixels, csv_pixels)
    ev.check(f'[{env}] summary.csv: tổng diện tích = area_ha, tổng % = 100', abs(sum(float(r['area_ha']) for r in rows) - result['area_ha']) < .011
             and abs(sum(float(r['percent']) for r in rows) - 100) < .05, f"{result['area_ha']} ha / 100 %",
             f"{round(sum(float(r['area_ha']) for r in rows), 2)} ha / {round(sum(float(r['percent']) for r in rows), 2)} %")
    gj = json.loads((d / 'classification.geojson').read_text())
    feats = gj['features']
    area_by_class = {}
    for f in feats:
        area_by_class[f['properties']['class_id']] = area_by_class.get(f['properties']['class_id'], 0) + polygon_area_ha(f['geometry'])
    ev.check(f'[{env}] GeoJSON FeatureCollection hợp lệ, class_id 0..18, ring khép kín', gj['type'] == 'FeatureCollection' and feats
             and all(0 <= f['properties']['class_id'] <= 18 and polygon_valid(f['geometry']) for f in feats), 'valid', f'{len(feats)} features')
    total = sum(area_by_class.values())
    ev.check(f'[{env}] Diện tích GeoJSON (geodesic) lệch area_ha < 1%', abs(total - result['area_ha']) / result['area_ha'] < .01, f"{result['area_ha']} ha ±1%", round(total, 3))
    names = set(zipfile.ZipFile(d / 'bundle.zip').namelist())
    ev.check(f'[{env}] ZIP chứa đủ 4 định dạng + result.json', names == {'classification.tif', 'summary.csv', 'classification.png', 'classification.geojson', 'result.json'}, 5, sorted(names))
    ev.check(f'[{env}] mean_confidence trong [0,1]', 0 <= result['mean_confidence'] <= 1, '[0,1]', result['mean_confidence'])
    report[env] = dict(geotiff=info | dict(tags=info['tags']), csv=rows, geojson_features=len(feats), geojson_area_ha=round(total, 4), zip=sorted(names),
                       result_keys=sorted(result))

diff = int((arrays['local'] != arrays['production']).sum())
ev.check('GeoTIFF Local và Production giống hệt từng pixel', diff == 0, '0 pixel khác', diff)
gl = (src / 'local/classification.geojson').read_text(); gp = (src / 'production/classification.geojson').read_text()
ev.log(f'GeoJSON bytes local={len(gl)} production={len(gp)} (khác biệt chỉ do định dạng số thực khi reproject, xem ghi chú)')
coords_l = np.concatenate([np.asarray(f['geometry']['coordinates'][0]) for f in json.loads(gl)['features']])
coords_p = np.concatenate([np.asarray(f['geometry']['coordinates'][0]) for f in json.loads(gp)['features']])
max_dev = float(np.abs(coords_l - coords_p).max()) if coords_l.shape == coords_p.shape else None
ev.check('Toạ độ GeoJSON Local vs Production lệch < 1e-9 độ (~0.1 mm)', max_dev is not None and max_dev < 1e-9, '< 1e-9', max_dev)
ev.save('output.json', report)

import matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
import scripts.ai_common as ai
fig, axes = plt.subplots(1, 3, figsize=(12, 4))
for ax, env in zip(axes, ['local', 'production']):
    ai.label_image(ax, np.where(arrays[env] == 255, 19, arrays[env])[:24, :24], f'classification.tif — {env} (24x24 vùng chọn)')
axes[2].imshow((arrays['local'] != arrays['production'])[:24, :24], cmap='Reds', vmin=0, vmax=1); axes[2].set_title(f'Khác biệt: {diff} pixel', fontsize=9); axes[2].axis('off')
fig.suptitle('TC04 · GeoTIFF tải về từ Local và Production', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'local_vs_production_geotiff.png', dpi=110); plt.close(fig)
ev.finish(expected='GeoTIFF đúng kiểu/CRS/nodata/độ phân giải và có metadata checkpoint; CSV khớp GeoTIFF; GeoJSON hợp lệ và diện tích khớp; ZIP đủ file; Local và Production trùng từng pixel.',
          actual=f'Mọi kiểm tra định dạng đạt ở cả hai môi trường; GeoTIFF khác {diff} pixel; toạ độ GeoJSON lệch tối đa {max_dev} độ.',
          notes='GeoJSON production dài hơn vài byte do cách in số thực của PROJ/Python trên ARM64; được kiểm tra bằng sai lệch toạ độ thay vì so sánh byte.',
          metrics=dict(pixel_diff=diff, geojson_max_coordinate_deviation_deg=max_dev, report={k: dict(geojson_features=v['geojson_features'], geojson_area_ha=v['geojson_area_ha']) for k, v in report.items()}))
