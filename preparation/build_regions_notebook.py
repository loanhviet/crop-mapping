"""Build a self-contained nine-block acquisition notebook, using the real modules."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def md(text):return dict(cell_type='markdown',metadata={},source=text.splitlines(keepends=True))
def code(text):
    ast.parse(text)
    return dict(cell_type='code',metadata={},source=text.splitlines(keepends=True),outputs=[],execution_count=None)


cells=[md('''# Crop Map: Normandy 23,04 × 23,04 km

Chín khối liền nhau, 10 band, tối đa 40 ngày thật/khối mùa 2018–2019.
Bật Internet; CPU đủ, không cần token hoặc nhãn. Dữ liệu ảnh khoảng 7,91 GiB
chưa gồm cache. Giữ phiên đủ dung lượng và lưu output trước khi kết thúc.
Notebook thu thập ảnh; chạy precompute_regions.py bằng checkpoint để tạo
classification cho web. Không biến nhãn hay ảnh nền bản đồ thành prediction.
'''),code('''import importlib.util,subprocess,sys
needed={'numpy':'numpy>=1.26,<3','httpx':'httpx>=0.27,<1',
        'rasterio':'rasterio>=1.4,<2','pyproj':'pyproj>=3.6,<4'}
missing=[spec for name,spec in needed.items() if importlib.util.find_spec(name) is None]
if missing:subprocess.check_call([sys.executable,'-m','pip','install',*missing])
from pathlib import Path
import json
'''),md('## Code và cấu hình gốc'),code(
    '\n'.join(f'Path({name!r}).write_text({(ROOT/name).read_text()!r})'
              for name in ['cog_data.py','prepare_regions.py'])+
    '\nPath("preparation").mkdir(exist_ok=True)\n'+
    '\n'.join(f'Path({name!r}).write_text({(ROOT/name).read_text()!r})'
              for name in ['preparation/cog_config.json','preparation/regions_config.json'])+
    '''
from prepare_regions import run
from cog_data import export_dataset,restore_dataset
CONFIG=json.loads(Path('preparation/regions_config.json').read_text())
IS_KAGGLE=Path('/kaggle/working').is_dir()
DATA=Path('/kaggle/temp/crop-map-regions/data') if IS_KAGGLE else Path('/content/crop-map-regions/data')
EXPORT=Path('/kaggle/working/submission') if IS_KAGGLE else Path('/content/submission')
DATA.mkdir(parents=True,exist_ok=True);EXPORT.mkdir(parents=True,exist_ok=True)
print('Scratch:',DATA,'Output:',EXPORT)
'''),md('''## Phục hồi tùy chọn

RESTORE_PATH là archive của lần trước hoặc thư mục đã giải nén chứa cog/.
Chỉ phục hồi vào scratch mới. Giữ đúng cấu hình để tái sử dụng ngày hoàn tất.
'''),code('''RESTORE_PATH=None
if RESTORE_PATH:restore_dataset(RESTORE_PATH,DATA)
'''),md('## Thu thập hai khối song song; lỗi mạng thì chạy lại cell'),code('''region=run(CONFIG,DATA)
print('Ready:',region['name'],region['shape'])
'''),md('''## Lưu dữ liệu

Sau hoàn tất để INCLUDE_CACHE=False. Nếu phải dừng sớm, chọn True để mang
theo cache và chạy tiếp phiên sau. Gói lớn; kiểm tra dung lượng output của
phiên đang dùng. Giữ archive trước khi tắt phiên. Có thể đặt EXPORT lên
Google Drive đã mount trên Colab. Giải nén vào crop-map/data trên máy chuẩn
bị, rồi chạy precompute_regions.py và package_deploy.py --predictions-only.
'''),code('''INCLUDE_CACHE=False
archive=export_dataset(DATA,EXPORT/'normandy-regions.tar.gz',include_cache=INCLUDE_CACHE)
print(archive,round(archive.stat().st_size/1024**3,2),'GiB')
''')]
for i,cell in enumerate(cells):cell['id']=f'regions-{i:02d}'
notebook=dict(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
                                  'language_info':{'name':'python'}},nbformat=4,nbformat_minor=5)
path=ROOT/'preparation/prepare_regions_kaggle.ipynb'
path.write_text(json.dumps(notebook,indent=1,ensure_ascii=False));print(path)
