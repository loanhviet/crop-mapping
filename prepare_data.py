"""Prepare GEODES imagery ahead of UI usage, or verified PASTIS references.

--geodes prepares a cropped cache from complete THEIA scene archives.
Default: fetch only required PASTIS members, never the entire 29 GB archive.
No remote pickle execution is used by the application or this preparation tool.
"""
import io
import json
import os
from datetime import datetime
from pathlib import Path
import urllib.request
import zipfile

import numpy as np
from pyproj import Transformer

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('CROP_DATA_DIR', ROOT / 'data'))
URL = 'https://zenodo.org/records/5012942/files/PASTIS.zip?download=1'
# Verified against every frame of the user's public PASTIS24 10000_0.pickle.
# DOY ties between years must retain the original NumPy conversion order.
FRAME_ORDER = [11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,
               31,32,33,34,35,36,37,38,39,40,0,1,2,3,41,4,42,5,6,7,8,9,10]
DEMO_PATCHES = (10003, 10010, 20000, 20004, 30001, 30004, 40002, 40005)
REGIONS = {'t30uxv': 'Normandy', 't31tfj': 'Provence',
           't31tfm': 'Rhône', 't32ulu': 'Alsace'}


class RemoteZip(io.RawIOBase):
    def __init__(self, url):
        self.url, self.pos = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method='HEAD'), timeout=60) as response:
            self.size = int(response.headers['Content-Length'])

    def seekable(self):
        return True

    def tell(self):
        return self.pos

    def seek(self, offset, whence=0):
        self.pos = offset if whence == 0 else self.pos + offset if whence == 1 else self.size + offset
        if self.pos < 0:
            raise ValueError('Negative seek')
        return self.pos

    def read(self, size=-1):
        size = min(self.size - self.pos, size if size >= 0 else self.size - self.pos)
        if size <= 0:
            return b''
        if size > 32 * 1024 * 1024:
            raise ValueError('Refusing a large archive member download')
        request = urllib.request.Request(self.url, headers={'Range': f'bytes={self.pos}-{self.pos+size-1}'})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.status != 206 or not response.headers.get('Content-Range', '').startswith(f'bytes {self.pos}-{self.pos+size-1}/'):
                raise RuntimeError('Server did not honor the requested byte range')
            payload = response.read(size)
        if len(payload) != size:
            raise RuntimeError('Incomplete download')
        self.pos += size
        return payload


def make_patch(feature, image_path, reference_dates):
    """The original 128px PASTIS acquisitions, cut with the PASTIS24 24px grid.

    Keep the verified historical NumPy tie order for the reference tile. Other
    calendars use an explicit stable DOY sort rather than a version-dependent
    quicksort; no exact parity with unavailable PASTIS24 pickles is claimed.
    """
    props = feature['properties']
    patch_id = int(props['ID_PATCH'])
    image = np.load(image_path, mmap_mode='r', allow_pickle=False)
    dates = [datetime.strptime(str(d), '%Y%m%d') for d in props['dates-S2'].values()]
    if image.shape != (len(dates), 10, 128, 128) or image.dtype != np.int16:
        raise ValueError(f'Unexpected original PASTIS image: {patch_id}, {image.shape}, {image.dtype}')
    doy = np.array([d.timetuple().tm_yday for d in dates])
    reference_order = list(props['dates-S2'].values()) == reference_dates
    order = FRAME_ORDER if reference_order else np.argsort(doy, kind='stable').tolist()
    tile = props['TILE'].lower()
    crs = f'EPSG:{32600 + int(tile[1:3])}'
    geometry = feature['geometry']
    ring = geometry['coordinates'][0][0] if geometry['type'] == 'MultiPolygon' else geometry['coordinates'][0]
    convert = Transformer.from_crs(2154, crs, always_xy=True)
    native = [convert.transform(*p) for p in ring]
    west, north = min(p[0] for p in native), max(p[1] for p in native)
    to_wgs = Transformer.from_crs(crs, 4326, always_xy=True)
    usable = [(west,north),(west+1200,north),(west+1200,north-1200),
              (west,north-1200),(west,north)]
    # Pick an actual mid-season frame for the RGB preview; no synthetic image.
    preview_index = min(range(len(dates)), key=lambda i: abs((dates[i]-datetime(2019,7,15)).days))
    return dict(id=patch_id, name=f'{REGIONS.get(tile,tile)} · {patch_id}',
                region=REGIONS.get(tile,tile), tile=tile, fold=props['Fold'],
                split='test' if props['Fold'] == 5 else 'validation' if props['Fold'] == 4 else 'training',
                crs=crs, origin=[west,north], shape=[120,120], usable_pixels=[120,120],
                geometry=dict(type='Polygon',coordinates=[[list(to_wgs.transform(*p)) for p in usable]]),
                frame_order=order, doy=doy[order].tolist(),
                frame_order_policy='verified-reference' if reference_order else 'stable-doy',
                dates=[d.date().isoformat() for d in dates],
                preview_index=preview_index, preview_date=dates[preview_index].date().isoformat(),
                first_date=min(dates).date().isoformat(), last_date=max(dates).date().isoformat(),
                acquisition_count=len(dates), model_observations=min(60,len(dates)),
                sha256=__import__('hashlib').sha256(image_path.read_bytes()).hexdigest())


def prepare(patch_ids=None):
    DATA.mkdir(parents=True, exist_ok=True)
    patch_ids = list(dict.fromkeys(patch_ids or DEMO_PATCHES))
    required = [('PASTIS/metadata.geojson', DATA / 'metadata.geojson')]
    required += [(f'PASTIS/DATA_S2/S2_{i}.npy', DATA / f'S2_{i}.npy') for i in patch_ids]
    missing = [(member, path) for member, path in required if not path.exists()]
    if missing:
        with zipfile.ZipFile(RemoteZip(URL)) as archive:
            for member, path in missing:
                print('Downloading', member, flush=True)
                payload = archive.read(member)
                path.with_suffix('.tmp').write_bytes(payload)
                path.with_suffix('.tmp').replace(path)
    metadata = json.loads((DATA / 'metadata.geojson').read_text())
    features = {f['properties']['ID_PATCH']: f for f in metadata['features']}
    reference_dates = list(features[10000]['properties']['dates-S2'].values())
    # Preserve previously installed references, but the web only advertises test patches.
    previous = DATA / 'catalog.json'
    old_ids = [p['id'] for p in json.loads(previous.read_text())['patches']] if previous.exists() else []
    ids = list(dict.fromkeys([*patch_ids,*old_ids]))
    patches = [make_patch(features[i], DATA/f'S2_{i}.npy', reference_dates)
               for i in ids if (DATA/f'S2_{i}.npy').exists()]
    catalog = dict(season='2018–2019', source=URL, patches=patches,
                   notes='120x120 usable pixels, 5x5 training-compatible 24x24 windows. Remaining 8-pixel edges excluded.')
    temporary = DATA / 'catalog.tmp'
    temporary.write_text(json.dumps(catalog, indent=2))
    temporary.replace(DATA / 'catalog.json')
    print('Ready:', ', '.join(p['name'] for p in patches))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--geodes', type=Path, help='WGS84 Polygon/Feature GeoJSON to prepare in the GEODES cache')
    parser.add_argument('--season', default='2018–2019')
    parser.add_argument('--plan', action='store_true', help='Show expected downloads without downloading imagery')
    parser.add_argument('--patches', type=int, nargs='+', help='Original PASTIS patch IDs to install; default: eight test patches across four tiles')
    arguments = parser.parse_args()
    if arguments.geodes:
        import tempfile
        import time
        from threading import Event
        from app import AnalysisRequest
        from imagery import GeodesProvider
        geometry = json.loads(arguments.geodes.read_text())
        if geometry.get('type') == 'Feature':
            geometry = geometry['geometry']
        request = AnalysisRequest(geometry=geometry, season=arguments.season)
        source = GeodesProvider()
        _, _, _, plan = source.plan(request.geometry, request.season)
        print(json.dumps(plan, ensure_ascii=False, indent=2), flush=True)
        if not arguments.plan:
            last_update = [0.0]
            def update(**values):
                now = time.monotonic()
                if 'message' in values or now-last_update[0] >= 5:
                    print(json.dumps(values, ensure_ascii=False), flush=True)
                    last_update[0] = now
            with tempfile.TemporaryDirectory(prefix='crop-map-preparation-') as temporary:
                _, _, metadata = source.prepare(request.geometry, request.season, temporary, Event(), update)
                print(f"Prepared {metadata['observations']} usable observations; the UI will reuse the imagery cache.", flush=True)
    else:
        if arguments.plan:
            parser.error('--plan requires --geodes <area.geojson>')
        prepare(arguments.patches)
