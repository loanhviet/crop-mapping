"""Prepare nine adjacent cubes, then publish one continuous virtual region.

Each acquisition block remains independently resumable. No duplicate 8 GiB
image mosaic is created: inference routes native 24-pixel windows to a cube.
"""
import argparse
from copy import deepcopy
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import time
from multiprocessing import get_context

import httpx
import rasterio

from cog_data import fingerprint, prepare, rectangle, write_json

ROOT = Path(__file__).resolve().parent


def block_configs(config):
    base = config['block']
    size = base['shape'][0]
    for row in range(config['rows']):
        for col in range(config['cols']):
            block = deepcopy(base)
            block.update(id=config['first_block_id'] + row*config['cols'] + col,
                         slug=f"{config['slug']}-r{row}-c{col}",
                         name=f"Normandy block {row+1}/{col+1}",
                         origin=[config['origin'][0]+col*size*10,
                                 config['origin'][1]-row*size*10])
            reuse = config.get('reuse', {}).get(f'{row},{col}')
            if reuse:
                block = json.loads((ROOT/reuse).read_text())
                expected=[config['origin'][0]+col*size*10,config['origin'][1]-row*size*10]
                if block['shape']!=base['shape'] or block['origin']!=expected or block['crs']!=base['crs']:
                    raise ValueError('Reused cube does not align with the mosaic grid')
            yield row, col, block


def publish(config, data):
    path=Path(data)/'cog/catalog.json'
    catalog=json.loads(path.read_text())
    entries={p['id']:p for p in catalog['patches']}
    parts=[]
    size=config['block']['shape'][0]
    for row,col,c in block_configs(config):
        if c['id'] not in entries:raise ValueError(f"Block {c['id']} is not ready")
        p=entries[c['id']]
        if p['origin']!=c['origin'] or p['shape']!=c['shape'] or p['crs']!=c['crs']:
            raise ValueError('Published block is not aligned')
        parts.append(dict(id=p['id'],row=row*size,col=col*size))
    shape=[config['rows']*size,config['cols']*size]
    dates=sorted({d for part in parts for d in entries[part['id']]['dates']})
    counts=[entries[p['id']]['acquisition_count'] for p in parts]
    patch=dict(id=config['id'],name=config['name'],region='Normandy',source='Sentinel-2 COG',
               split='external',season=config['block']['season'],crs=config['block']['crs'],
               origin=config['origin'],shape=shape,components=parts,
               acquisition_count=min(counts),observation_range=[min(counts),max(counts)],
               model_observations=min(counts),dates=dates,first_date=min(dates),last_date=max(dates),
               preview_date='Per block',max_analysis_windows=256,
               dataset_version=fingerprint([entries[p['id']]['dataset_version'] for p in parts]))
    patch['geometry']=rectangle(patch)
    patch['default_geometry']=rectangle(patch,shape[0]//2-96,shape[1]//2-96,192,192)
    # Hide internal blocks from the dropdown while keeping old explicit IDs usable.
    for part in parts:entries[part['id']]['mosaic_parent']=config['id']
    catalog['patches']=[patch]+[p for p in entries.values() if p['id']!=patch['id']]
    write_json(path,catalog)
    write_json(Path(data)/'cog'/config['slug']/'report.json',
               dict(region_id=patch['id'],area_km2=shape[0]*shape[1]/10000,
                    blocks=len(parts),observation_range=patch['observation_range'],
                    dataset_version=patch['dataset_version'],components=parts))
    return patch


def acquire(entry,data):
    row,col,block=entry
    print(json.dumps(dict(stage='block',row=row,col=col,id=block['id'])),flush=True)
    for attempt in range(3):
        try:
            return prepare(block,data)
        except (rasterio.errors.RasterioIOError,httpx.HTTPError) as error:
            if attempt==2:raise
            print(json.dumps(dict(stage='block_retry',id=block['id'],error=str(error))),flush=True)
            time.sleep(2)


def run(config,data,parallel_blocks=2):
    # Bound both parallel regions and the four HTTP readers inside each region.
    # Separate processes also isolate GDAL's global HTTP cache between blocks.
    errors=[]
    if parallel_blocks not in (1,2,3):raise ValueError('Use 1–3 parallel acquisition blocks')
    with ProcessPoolExecutor(max_workers=parallel_blocks,mp_context=get_context('spawn')) as pool:
        futures={pool.submit(acquire,entry,data):entry[2]['id'] for entry in block_configs(config)}
        for future in as_completed(futures):
            try:future.result()
            except Exception as error:
                errors.append(futures[future])
                print(json.dumps(dict(stage='block_error',id=futures[future],error=str(error))),flush=True)
    if errors:raise RuntimeError(f'Blocks {errors} failed; rerun the same command to resume.')
    patch=publish(config,data)
    print(json.dumps(dict(stage='mosaic_ready',id=patch['id'],shape=patch['shape'])),flush=True)
    return patch


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'preparation/regions_config.json')
    parser.add_argument('--data',type=Path,default=ROOT/'data')
    parser.add_argument('--plan',action='store_true')
    parser.add_argument('--parallel-blocks',type=int,default=2,choices=(1,2,3))
    args=parser.parse_args();config=json.loads(args.config.read_text())
    if args.plan:
        print(json.dumps([dict(row=r,col=c,config=b) for r,c,b in block_configs(config)],indent=2))
    else:run(config,args.data,args.parallel_blocks)
