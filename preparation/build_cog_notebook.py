"""Build a standalone Kaggle/Colab notebook from the actual acquisition module."""
import ast
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def markdown(text):return dict(cell_type='markdown',metadata={},source=text.splitlines(keepends=True))
def code(text):
    ast.parse(text)
    return dict(cell_type='code',metadata={},source=text.splitlines(keepends=True),outputs=[],execution_count=None)


cells=[
 markdown('''# Bộ dữ liệu liên tục cho Crop Map

Chuẩn bị vùng Normandy 7,68 × 7,68 km, 10 kênh và tối đa 40 ngày thật phủ mùa
2018–2019. Tải các cửa sổ COG qua mạng, kiểm tra SCL, chuẩn hóa thang phản xạ
bằng scale/offset. Không cần GPU, nhãn hoặc API key. Bật Internet.

Chỉ công bố vùng khi hoàn tất. Ngày ít hơn mục tiêu chỉ được chấp nhận nếu
đủ ngưỡng tối thiểu đã cấu hình. Giữ cấu hình khi resume; có thể đổi workers.
Đây là chuẩn bị ảnh, chưa xác nhận độ chính xác model trên Kaggle.
'''),
 code('''import importlib.util, subprocess, sys
needed={'numpy':'numpy>=1.26,<3','httpx':'httpx>=0.27,<1',
        'rasterio':'rasterio>=1.4,<2','pyproj':'pyproj>=3.6,<4'}
missing=[spec for name,spec in needed.items() if importlib.util.find_spec(name) is None]
if missing:subprocess.check_call([sys.executable,'-m','pip','install',*missing])
from pathlib import Path
import json, shutil
'''),
 markdown('## Code độc lập, cùng nguồn với công cụ local'),
 code('MODULE_SOURCE = '+repr((ROOT/'cog_data.py').read_text())+'''
Path('cog_data.py').write_text(MODULE_SOURCE)
from cog_data import prepare, export_dataset, restore_dataset
'''),
 markdown('## Cấu hình và thư mục'),
 code('CONFIG = json.loads('+repr((ROOT/'preparation/cog_config.json').read_text())+''')
IS_KAGGLE=Path('/kaggle/working').is_dir()
DATA=Path('/kaggle/temp/crop-map-continuous/data') if IS_KAGGLE else Path('/content/crop-map-continuous/data')
EXPORT=Path('/kaggle/working/submission') if IS_KAGGLE else Path('/content/submission')
DATA.mkdir(parents=True,exist_ok=True);EXPORT.mkdir(parents=True,exist_ok=True)
print(json.dumps(CONFIG,indent=2,ensure_ascii=False))
print('Raw image estimate (MiB):',CONFIG['observations']*10*CONFIG['shape'][0]*CONFIG['shape'][1]*4/1024**2)
print('Scratch:',DATA,'Saved output:',EXPORT)
'''),
 markdown('''## Phục hồi tùy chọn

Thêm bản checkpoint trước vào Input. RESTORE_PATH có thể là `.tar.gz` hoặc
thư mục sau khi Kaggle tự giải nén, thư mục đó phải chứa `cog/`. Chỉ phục hồi
vào phiên scratch mới. Dữ liệu scratch không được giữ tự động giữa các phiên.
'''),
 code('''RESTORE_PATH=None
if RESTORE_PATH:restore_dataset(RESTORE_PATH,DATA)
'''),
 markdown('''## Thu thập

Mỗi ngày hoàn tất được lưu cache nguyên tử. Nếu lỗi mạng, chạy lại cell này;
không cần đọc lại ngày đã hoàn tất. SCL cần được đọc xong trước khi chốt ngày
ảnh. Chỉ đọc đủ 10 kênh cho những ngày được chọn, không tải toàn cảnh.
'''),
 code('''report=prepare(CONFIG,DATA)
print(json.dumps({k:report[k] for k in ['area_ha','observations','max_gap_days','valid_fraction']},indent=2))
'''),
 markdown('''## Lưu archive dữ liệu để chuyển về web

Khi hoàn tất, để INCLUDE_CACHE=False cho gói inference gọn hơn. Nếu buộc phải
dừng giữa chừng, chạy cell này với INCLUDE_CACHE=True để giữ các ngày đã tải
và chạy tiếp sau. Không đóng gói file observations.pending chưa hoàn tất.
Save Version với Output hoặc tải archive về trước khi kết thúc phiên.

Giải nén gói inference vào `crop-map/data/`, rồi restart ứng dụng để nạp catalog.
Trên Colab có thể đặt EXPORT sang thư mục Google Drive đã mount để lưu bền.
'''),
 code('''INCLUDE_CACHE=False
archive=export_dataset(DATA,EXPORT/'continuous-cog.tar.gz',include_cache=INCLUDE_CACHE)
print('Archive:',archive,'MiB:',round(archive.stat().st_size/1024**2,2))
''')]
for i,cell in enumerate(cells):cell['id']=f'cog-{i:02d}'
notebook=dict(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},
                                  'language_info':{'name':'python'}},nbformat=4,nbformat_minor=5)
path=ROOT/'preparation/prepare_continuous_kaggle.ipynb'
path.write_text(json.dumps(notebook,indent=1,ensure_ascii=False))
print(path)
