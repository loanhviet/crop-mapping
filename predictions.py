"""Versioned model predictions shared by map tiles and selected-area exports."""
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_bounds
from rasterio.vrt import WarpedVRT

from inference import COLORS, ImageColor

PIPELINE_VERSION = 3


class PredictionStore:
    def __init__(self, data, checkpoint):
        self.root=Path(data)/'predictions'
        self.checkpoint=checkpoint

    def key(self,patch):
        identity=dict(dataset=patch.get('dataset_version',patch.get('sha256')),
                      checkpoint=self.checkpoint,pipeline=PIPELINE_VERSION,region=patch['id'])
        return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()

    def directory(self,patch):
        return self.root/self.key(patch)

    def ready(self,patch):
        path=self.directory(patch)/'ready.json'
        if not path.is_file():return None
        report=json.loads(path.read_text())
        if report.get('key')!=self.key(patch) or report.get('shape')!=patch['shape']:
            return None
        for name,record in report['files'].items():
            file=path.parent/name
            if not file.is_file() or file.stat().st_size!=record['bytes']:return None
        return report

    def arrays(self,patch):
        if not self.ready(patch):raise ValueError('No completed prediction for this data and model')
        directory=self.directory(patch)
        return tuple(np.load(directory/name,mmap_mode='r',allow_pickle=False)
                     for name in ['labels.npy','confidence.npy'])

    def tile(self,patch,z,x,y):
        if not self.ready(patch):raise ValueError('Prediction is not ready')
        return render_tile(str(self.directory(patch)/'classification.tif'),z,x,y)


@lru_cache(maxsize=512)
def render_tile(path,z,x,y):
    """Read only the requested Web-Mercator tile; class labels use nearest."""
    radius=20037508.342789244
    span=2*radius/(2**z)
    west,north=-radius+x*span,radius-y*span
    transform=from_bounds(west,north-span,west+span,north,256,256)
    with rasterio.open(path) as source, WarpedVRT(source,crs='EPSG:3857',
            transform=transform,width=256,height=256,src_nodata=255,nodata=255,
            resampling=Resampling.nearest) as vrt:
        labels=vrt.read(1)
    palette=np.array([ImageColor(c) for c in COLORS]+[(0,0,0)]*(256-len(COLORS)),np.uint8)
    rgba=np.dstack([palette[labels],np.uint8(labels!=255)*255])
    output=io.BytesIO();Image.fromarray(rgba).save(output,format='PNG')
    return output.getvalue()
