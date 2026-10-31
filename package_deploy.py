"""Bundle the runnable app, checkpoint and completed local imagery for EC2.

Uses an explicit allowlist: no .env, tokens, train samples, results, DINOv3
weights, virtual environments or task-2 dataset are included.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
from copy import deepcopy

from predictions import PredictionStore

ROOT = Path(__file__).resolve().parent


def file_hash(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(8*1024**2),b''):h.update(chunk)
    return h.hexdigest()


def prediction_catalog(catalog,store):
    result=deepcopy(catalog)
    keep=[]
    for patch in result['patches']:
        if not store.ready(patch):continue
        if not patch.get('components'):
            directory=store.directory(patch)
            if not (directory/'preview-rgb.png').is_file():
                raise ValueError('Run precompute_regions.py to create the native RGB preview')
            patch.update(prediction_only=True,
                prediction_manifest_path=(directory/'ready.json').relative_to(ROOT/'data').as_posix(),
                preview_image_path=(directory/'preview-rgb.png').relative_to(ROOT/'data').as_posix())
        keep.append(patch)
    result['patches']=keep
    kept={p['id'] for p in keep}
    if any(part['id'] not in kept for p in keep for part in p.get('components',[])):
        raise ValueError('Complete predictions for every acquisition block before packaging')
    return result


def package(destination,predictions_only=False,live=False):
    path=ROOT/'data/catalog.json'
    catalog = json.loads(path.read_text()) if path.exists() else dict(season='2018–2019',patches=[])
    catalog['patches'] = [p for p in catalog['patches'] if p['split'] == 'test']
    cog_path=ROOT/'data/cog/catalog.json'
    cog_catalog=json.loads(cog_path.read_text()) if cog_path.exists() else dict(season='2018–2019',patches=[])
    if live:
        catalog['patches']=[]
    checkpoint=file_hash(ROOT/'weights/best.pth')
    store=PredictionStore(ROOT/'data',checkpoint)
    if predictions_only:
        cog_catalog=prediction_catalog(cog_catalog,store)
        catalog['patches']=[]
    if not catalog['patches'] and not cog_catalog['patches']:
        raise ValueError('Prepare local imagery first.')
    names = ['Dockerfile','compose.yaml','.dockerignore','.env.example','requirements.txt',
             'app.py','inference.py','imagery.py','model.py','predictions.py','run.sh','prepare_data.py',
             'README.md','README_DEPLOY.md','README_GEODES.md','package_deploy.py',
             'README_COG.md','README_REGIONS.md','cog_data.py','prepare_cog.py','validate_cog.py',
             'prepare_regions.py','precompute_regions.py','preparation/regions_config.json','preparation/cog_config.json',
             'preparation/prepare_continuous_kaggle.ipynb',
             'preparation/prepare_regions_kaggle.ipynb',
             'weights/best.pth','weights/config.yaml','weights/LICENSE.txt',
             'docs/ASSETS.md','docs/ARCHITECTURE.md','docs/TESTING.md','docs/VALIDATION.md',
             'docs/BRANCHING.md','docs/MIGRATION.md','deployment/README.md',
             'assets/model-manifest.json','scripts/verify_assets.py','weights/README.md','data/README.md']
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT/'web').rglob('*')
              if p.is_file() and 'benchmarks' not in p.relative_to(ROOT/'web').parts]
    names += [f"data/S2_{p['id']}.npy" for p in catalog['patches']]
    for patch in cog_catalog['patches']:
        if patch.get('components'):continue
        keys=['valid_mask_path'] if predictions_only else ['image_path','valid_mask_path']
        for key in keys:
            relative=Path(patch[key])
            if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='cog':
                raise ValueError('Unsafe COG dataset path')
            names.append('data/'+relative.as_posix())
        directory=(ROOT/'data'/patch['image_path']).parent
        for filename in ['report.json','config.json','clear-count.npy','reference-probe.json','overlap-validation.json']:
            p=directory/filename
            if p.exists():names.append(p.relative_to(ROOT).as_posix())
    for patch in cog_catalog['patches']:
        if not live and store.ready(patch):
            for name in ['labels.npy','confidence.npy','classification.tif','ready.json','preview-rgb.png']:
                path=store.directory(patch)/name
                if path.is_file():names.append(path.relative_to(ROOT).as_posix())
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(),
                    sources=['https://zenodo.org/records/5012942']+
                            (['https://earth-search.aws.element84.com/v1'] if cog_catalog['patches'] else []),
                    season=catalog['season'], test_patch_ids=[p['id'] for p in catalog['patches']],
                    continuous_region_ids=[p['id'] for p in cog_catalog['patches']],
                    model='TSViT', predictions_only=predictions_only, files={})
    catalog_bytes = json.dumps(catalog, indent=2).encode()
    generated={'data/catalog.json':catalog_bytes}
    if cog_catalog['patches']:generated['data/cog/catalog.json']=json.dumps(cog_catalog,indent=2).encode()
    for name,content in generated.items():
        manifest['files'][name] = dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        raise FileExistsError(f'Refusing to overwrite {destination}')
    temporary = destination.with_suffix(destination.suffix+'.part')
    with tarfile.open(temporary,'w:gz') as archive:
        for name in sorted(set(names)):
            path = ROOT/name
            if not path.is_file() or path.is_symlink():
                raise ValueError(f'Required regular file missing: {name}')
            digest = file_hash(path)
            manifest['files'][name] = dict(bytes=path.stat().st_size, sha256=digest)
            archive.add(path,arcname='crop-map/'+name,recursive=False)
        for name, content in [*generated.items(),('deployment-manifest.json',json.dumps(manifest,indent=2).encode())]:
            info = tarfile.TarInfo('crop-map/'+name)
            info.size=len(content);info.mode=0o644
            archive.addfile(info,io.BytesIO(content))
    temporary.replace(destination)
    digest = file_hash(destination)
    destination.with_suffix(destination.suffix+'.sha256').write_text(f'{digest}  {destination.name}\n')
    print('Bundle:',destination)
    print('MiB:',round(destination.stat().st_size/1024**2,2))
    print('Test patches:',manifest['test_patch_ids'])
    print('Continuous regions:',manifest['continuous_region_ids'])
    return destination


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true',help='Ship real time-series imagery without saved classifications')
    parser.add_argument('--predictions-only',action='store_true',help='Ship saved model predictions and previews, without raw time-series cubes')
    parser.add_argument('--output',type=Path,default=ROOT/'deployment/bundles'/
                        f"crop-map-demo-{datetime.now().strftime('%Y%m%d-%H%M%S')}.tar.gz")
    args=parser.parse_args()
    if args.live and args.predictions_only:
        parser.error('--live and --predictions-only cannot be combined')
    package(args.output.resolve(),args.predictions_only,args.live)
