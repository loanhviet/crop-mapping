"""Download a continuous Sentinel-2 demo region; rerun the same command to resume."""
import argparse
import json
import os
from pathlib import Path

from cog_data import prepare, validate_config

if __name__=='__main__':
    root=Path(__file__).resolve().parent
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=root/'preparation/cog_config.json')
    parser.add_argument('--data',type=Path,default=Path(os.getenv('CROP_DATA_DIR',root/'data')))
    parser.add_argument('--plan',action='store_true')
    args=parser.parse_args();config=json.loads(args.config.read_text());validate_config(config)
    if args.plan:
        print(json.dumps(dict(config=config,raw_image_bytes=config['observations']*10*config['shape'][0]*config['shape'][1]*4,
                             note='Disk array estimate; HTTP traffic, masks and caches are additional.'),indent=2))
    else:prepare(config,args.data)
