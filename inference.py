"""PASTIS provider, training-compatible preprocessing, inference and map exports.

This module has no dependency on HTTP or the UI. A new data provider or worker
can call the same preprocessing/model/export functions.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.features import geometry_mask, shapes
from rasterio.transform import from_origin
from rasterio.warp import Resampling, calculate_default_transform, reproject, transform_geom
import torch
import yaml

from model import TSViT

ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv('CROP_DATA_DIR', ROOT / 'data'))
WEIGHTS = Path(os.getenv('CROP_WEIGHTS_DIR', ROOT / 'weights'))
RESULTS = Path(os.getenv('CROP_RESULTS_DIR', DATA / 'results'))
MEAN = np.array([1165.9398193359375, 1375.6534423828125, 1429.2191162109375,
                 1764.798828125, 2719.273193359375, 3063.61181640625,
                 3205.90185546875, 3319.109619140625, 2422.904296875,
                 1639.370361328125], dtype=np.float32)[None, :, None, None]
STD = np.array([1942.6156005859375, 1881.9234619140625, 1959.3798828125,
                1867.2239990234375, 1754.5850830078125, 1769.4046630859375,
                1784.860595703125, 1767.7100830078125, 1458.963623046875,
                1299.2833251953125], dtype=np.float32)[None, :, None, None]
CLASS_NAMES = ['Background', 'Meadow', 'Soft winter wheat', 'Corn', 'Winter barley',
               'Winter rapeseed', 'Spring barley', 'Sunflower', 'Grapevine', 'Beet',
               'Winter triticale', 'Winter durum wheat', 'Fruits, vegetables, flowers',
               'Potatoes', 'Leguminous fodder', 'Soybeans', 'Orchard', 'Mixed cereal', 'Sorghum']
COLORS = ['#89969b', '#78a754', '#f6ce42', '#56af69', '#69afe4', '#ddd85a',
          '#a4cee8', '#f3974b', '#8e72aa', '#d57e9e', '#bdb169', '#e3b53e',
          '#ce9bd6', '#b5896b', '#52aa9b', '#8bbd70', '#487e53', '#b89c72', '#b46955']
CLASSES = [dict(id=i, name=n, color=COLORS[i]) for i, n in enumerate(CLASS_NAMES)]


def write_json(path, value):
    """Atomic status/result writes, so polling never reads a partial file."""
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


class PreparedProvider:
    """Local PASTIS references and completed continuous Sentinel-2 cubes."""
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        catalogs = [json.loads(p.read_text()) for p in
                    [self.directory/'cog/catalog.json', self.directory/'catalog.json'] if p.exists()]
        self.catalog = dict(season='2018–2019',patches=[])
        self.patches = {}
        mosaics = []
        for catalog in catalogs:
            if catalog['season'] != self.catalog['season']:
                raise ValueError('Prepared catalog season mismatch')
            for patch in catalog['patches']:
                if 'components' in patch:
                    mosaics.append(patch)
                    continue
                cached_only=(patch.get('prediction_only') and
                             self.data_path(patch['prediction_manifest_path']).is_file() and
                             self.data_path(patch['preview_image_path']).is_file())
                if self.image_path(patch).is_file() or cached_only:
                    if patch['id'] in self.patches:
                        raise ValueError('Duplicate prepared region ID')
                    self.patches[patch['id']] = patch
        for patch in mosaics:
            if patch['id'] in self.patches:raise ValueError('Duplicate prepared region ID')
            self._validate_mosaic(patch)
            self.patches[patch['id']] = patch
        # Prefer a continuous parent region for automatic geometry resolution.
        self.patches = dict(sorted(self.patches.items(), key=lambda pair: not bool(pair[1].get('components'))))
        self.catalog['patches'] = list(self.patches.values())

    def _validate_mosaic(self, patch):
        height,width=patch['shape']
        covered=np.zeros((height,width),bool)
        for part in patch['components']:
            child=self.get(part['id']);r,c=part['row'],part['col'];h,w=child['shape']
            expected=[patch['origin'][0]+c*10,patch['origin'][1]-r*10]
            if (child.get('components') or child['crs']!=patch['crs'] or
                child['season']!=patch['season'] or child['origin']!=expected or
                r<0 or c<0 or r%24 or c%24 or h%24 or w%24 or r+h>height or c+w>width or
                covered[r:r+h,c:c+w].any()):
                raise ValueError('Invalid or overlapping mosaic component')
            covered[r:r+h,c:c+w]=True
        if not covered.all():raise ValueError('Mosaic contains a gap')

    def parts(self, patch):
        return patch.get('components',[dict(id=patch['id'],row=0,col=0)])

    def window_source(self, patch_id, row, col):
        patch=self.get(patch_id)
        if not patch.get('components'):return patch,row,col
        for part in patch['components']:
            child=self.get(part['id']);h,w=child['shape'];r,c=part['row'],part['col']
            if r<=row and row+24<=r+h and c<=col and col+24<=c+w:
                return child,row-r,col-c
        raise ValueError('Window crosses an unaligned acquisition block')

    def data_path(self, relative):
        path=(self.directory/relative).resolve()
        if not path.is_relative_to(self.directory.resolve()):
            raise ValueError('Prepared data path must stay inside the data directory')
        return path

    def image_path(self, patch):
        return self.data_path(patch.get('image_path',f"S2_{patch['id']}.npy"))

    def get(self, patch_id):
        if patch_id not in self.patches:
            raise ValueError('This area has no prepared imagery. Choose an available region.')
        return self.patches[patch_id]

    def image(self, patch_id):
        return np.load(self.image_path(self.get(patch_id)), mmap_mode='r', allow_pickle=False)

    def window(self, patch_id, row, col):
        p,row,col=self.window_source(patch_id,row,col)
        return self.image(p['id'])[p['frame_order'], :, row:row+24, col:col+24]

    def window_doy(self,patch_id,row,col):
        return self.window_source(patch_id,row,col)[0]['doy']

    def valid_mask(self, patch_id):
        patch=self.get(patch_id)
        if patch.get('components'):
            mask=np.zeros(patch['shape'],bool)
            for part in patch['components']:
                child=self.valid_mask(part['id']);r,c=part['row'],part['col'];h,w=child.shape
                mask[r:r+h,c:c+w]=child
            return mask
        if 'valid_mask_path' not in patch:
            return np.ones(patch.get('shape',(120,120)),dtype=bool)
        mask=np.load(self.data_path(patch['valid_mask_path']),mmap_mode='r',allow_pickle=False)
        if mask.shape!=tuple(patch['shape']) or mask.dtype!=np.bool_:
            raise ValueError('Invalid prepared quality mask')
        return mask

    def public_catalog(self, include_external=True):
        return dict(season=self.catalog['season'], classes=CLASSES,
                    patches=[{k: v for k, v in p.items() if k not in
                              ('frame_order','sha256','image_path','valid_mask_path',
                               'prediction_manifest_path','preview_image_path')}
                             for p in self.patches.values() if not p.get('mosaic_parent') and
                             (p['split']=='test' or (include_external and p['split']=='external'))])

    def resolve(self, geometry, season, patch_id=None, include_external=True):
        if season != self.catalog['season']:
            raise ValueError('No prepared imagery is available for that season. Choose 2018–2019.')
        if patch_id is not None:
            patch = self.get(patch_id)
            return patch, selection_mask(patch, geometry)
        for patch in self.patches.values():
            if patch['split'] != 'test' and not (include_external and patch['split']=='external'):
                continue
            try:
                return patch, selection_mask(patch, geometry)
            except ValueError:
                continue
        raise ValueError('Select an area inside one outlined region. Choose another available region to move the map.')


# Backward-compatible import for the original PASTIS tools/tests.
PastisProvider = PreparedProvider


def preprocess(image, doy):
    """Exactly Normalize → TileDates → CutOrPad → ToTHWC from training.

    Frame order is established by the provider, including DOY ties from the
    original PASTIS24 conversion. Padded time steps remain all-zero.
    """
    image = np.asarray(image, dtype=np.float32)
    doy = np.asarray(doy, dtype=np.float32)
    if image.ndim != 4 or image.shape[1:] != (10, 24, 24) or len(image) != len(doy):
        raise ValueError('Expected [T, 10, 24, 24] imagery and one DOY per frame.')
    if not np.isfinite(image).all() or not np.isfinite(doy).all() or ((doy < 1) | (doy > 365)).any():
        raise ValueError('Invalid reflectance values or dates for this checkpoint.')
    normalized = (image[:60] - MEAN) / STD
    out = np.zeros((60, 24, 24, 11), dtype=np.float32)
    out[:len(normalized), :, :, :10] = normalized.transpose(0, 2, 3, 1)
    out[:len(normalized), :, :, 10] = (doy[:60] / np.float32(365.0001))[:, None, None]
    return torch.from_numpy(out)


class Engine:
    def __init__(self):
        torch.set_num_threads(int(os.getenv('CROP_THREADS', '4')))
        requested = os.getenv('CROP_DEVICE', 'cpu')
        if requested.startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('CUDA requested but this PyTorch installation has no available GPU.')
        self.device = torch.device(requested)
        self.config = yaml.safe_load((WEIGHTS / 'config.yaml').read_text())['MODEL']
        required = dict(img_res=24, num_channels=11, num_classes=19, max_seq_len=60)
        if any(self.config.get(key) != value for key, value in required.items()):
            raise RuntimeError('Checkpoint configuration does not match this PASTIS24 inference pipeline.')
        self.model = TSViT(self.config).to(self.device)
        checkpoint = torch.load(WEIGHTS / 'best.pth', map_location='cpu', weights_only=True)
        state = checkpoint.get('model_state_dict', checkpoint)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        self.sha256 = hashlib.sha256((WEIGHTS / 'best.pth').read_bytes()).hexdigest()

    @torch.inference_mode()
    def predict(self, image, doy):
        probabilities = self.model(preprocess(image, doy)[None].to(self.device)).softmax(dim=1)
        confidence, labels = probabilities.max(dim=1)
        return labels[0].cpu().numpy().astype(np.uint8), confidence[0].cpu().numpy()


def grid(patch):
    return from_origin(patch['origin'][0], patch['origin'][1], 10, 10)


def selection_mask(patch, geometry):
    """Use pixel centres on the native 10 m grid; no ground-truth masking."""
    projected = transform_geom('EPSG:4326', patch['crs'], geometry)
    height, width = patch.get('shape', (120, 120))
    west, north = patch['origin']
    for x, y in projected['coordinates'][0]:
        if not (west - 0.02 <= x <= west + width*10 + .02 and north - height*10 - .02 <= y <= north + .02):
            raise ValueError('Keep the selection inside the outlined area with available imagery.')
    mask = geometry_mask([projected], out_shape=(height, width), transform=grid(patch), invert=True)
    if not mask.any():
        raise ValueError('Select an area containing at least one 10 m pixel centre.')
    return mask


def web_png(array, crs, transform, resampling=Resampling.nearest):
    """Reproject pixels to Web Mercator before drawing them with Leaflet.

    A plain imageOverlay of the native UTM rectangle would rotate/misplace it.
    Transparent nodata preserves the actual footprint.
    """
    if array.ndim == 2:
        array = array[None]
    height, width = array.shape[1:]
    bounds = rasterio.transform.array_bounds(height, width, transform)
    dst_transform, w, h = calculate_default_transform(crs, 'EPSG:3857', width, height, *bounds)
    destination = np.zeros((array.shape[0], h, w), dtype=array.dtype)
    reproject(array, destination, src_transform=transform, src_crs=crs,
              dst_transform=dst_transform, dst_crs='EPSG:3857', resampling=resampling)
    west, south, east, north = rasterio.transform.array_bounds(h, w, dst_transform)
    converter = Transformer.from_crs(3857, 4326, always_xy=True)
    sw, ne = converter.transform(west, south), converter.transform(east, north)
    stream = io.BytesIO()
    Image.fromarray(destination.transpose(1, 2, 0)).save(stream, format='PNG')
    return stream.getvalue(), [[sw[1], sw[0]], [ne[1], ne[0]]]


@lru_cache(maxsize=8)
def preview(patch_id):
    provider = PreparedProvider(DATA)
    patch = provider.get(patch_id)
    height, width = patch.get('shape', patch.get('usable_pixels', (120,120)))
    rgb=np.zeros((3,height,width),np.uint8)
    for part in provider.parts(patch):
        child=provider.get(part['id'])
        h,w=child.get('shape',(120,120));r,c=part['row'],part['col']
        if child.get('preview_image_path'):
            with Image.open(provider.data_path(child['preview_image_path'])) as source:
                rgb[:,r:r+h,c:c+w]=np.asarray(source.convert('RGB')).transpose(2,0,1)
        else:
            image=provider.image(child['id'])[child['preview_index'],[2,1,0],:h,:w].astype(np.float32)
            rgb[:,r:r+h,c:c+w]=np.uint8(np.clip(image/3000,0,1)**(1/1.3)*255)
    alpha=np.uint8(provider.valid_mask(patch_id))[None]*255
    rgba = np.concatenate([rgb, alpha])
    return web_png(rgba, patch['crs'], grid(patch), Resampling.bilinear)


def export_result(directory, patch, labels, confidence, mask, metadata):
    """Write all exports from one native label grid; nodata is 255, class 0 valid."""
    directory = Path(directory)
    nodata_labels = np.where(mask, labels, 255).astype(np.uint8)
    transform = grid(patch)
    height, width = labels.shape
    with rasterio.open(directory / 'classification.tif', 'w', driver='GTiff', width=width,
                       height=height, count=1, dtype='uint8', crs=patch['crs'],
                       transform=transform, nodata=255, compress='deflate') as raster:
        raster.write(nodata_labels, 1)
        raster.write_colormap(1, {i: (*ImageColor(c), 255) for i, c in enumerate(COLORS)} | {255: (0, 0, 0, 0)})
        raster.update_tags(model='TSViT', season=metadata.get('season', '2018–2019'),
                           source=metadata.get('source', 'PASTIS'), checkpoint_sha256=metadata['checkpoint_sha256'])
    np.save(directory / 'confidence.npy', confidence, allow_pickle=False)
    palette = np.array([ImageColor(c) for c in COLORS], dtype=np.uint8)
    rgba = np.concatenate([palette[labels].transpose(2, 0, 1), np.uint8(mask[None]) * 255])
    Image.fromarray(rgba.transpose(1, 2, 0)).save(directory / 'classification.png')
    png, bounds = web_png(rgba, patch['crs'], transform)
    (directory / 'overlay.png').write_bytes(png)
    rows = []
    for item in CLASSES:
        count = int(((labels == item['id']) & mask).sum())
        if count:
            rows.append(dict(**item, pixels=count, area_ha=round(count * .01, 2),
                             percent=round(count / mask.sum() * 100, 2)))
    rows.sort(key=lambda r: -r['pixels'])
    with (directory / 'summary.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=['id', 'name', 'color', 'pixels', 'area_ha', 'percent'])
        writer.writeheader()
        writer.writerows(rows)
    # Stream polygons instead of retaining the entire large-region vector map in RAM.
    vector_path=directory/'classification.geojson'
    temporary=vector_path.with_suffix('.tmp')
    with temporary.open('w') as stream:
        stream.write('{"type":"FeatureCollection","features":[')
        first=True
        for geom,value in shapes(nodata_labels,mask=mask,transform=transform):
            class_id=int(value)
            if not first:stream.write(',')
            json.dump(dict(type='Feature',geometry=transform_geom(patch['crs'],'EPSG:4326',geom),
                           properties=dict(class_id=class_id,crop=CLASS_NAMES[class_id],color=COLORS[class_id])),stream)
            first=False
        stream.write(']}')
    temporary.replace(vector_path)
    metadata.update(classes=rows, area_ha=round(int(mask.sum()) * .01, 2),
                    pixels=int(mask.sum()), overlay_bounds=bounds,
                    mean_confidence=round(float(confidence[mask].mean()), 4), crs=patch['crs'],
                    pixel_size_m=10, footprint=patch['geometry'])
    write_json(directory / 'result.json', metadata)
    return metadata


def ImageColor(color):
    return tuple(int(color[i:i+2], 16) for i in (1, 3, 5))
