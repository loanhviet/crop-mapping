# Vùng Normandy liên tục 23,04 × 23,04 km

Mở rộng về phía tây, đông và phía nam của vùng cũ, giữ đường biên phía bắc để
không mở thêm quá nhiều ra biển. Chín khối 768×768 pixel tạo lưới 2304×2304
ở 10 m: **530,8416 km²** trước khi loại pixel không đủ chất lượng ảnh.
Khối cũ 900001 được dùng lại; tám khối còn lại có ID 900020, 900022–900028.
Vùng ghép có ID **900010** và hiện đầu tiên trong bộ chọn vùng.

Bản local ngày 17/10/2026 đã hoàn tất cả chín khối: **36–40 ngày thật/khối**,
8.281.130.112 byte mảng ảnh (~7,71 GiB, chưa gồm cache). Valid mask giữ
**521,9808 km²**; 8,8608 km² còn lại không đủ chính sách native/clear và được
để nodata. Prediction toàn vùng đã được tạo bằng checkpoint TSViT hiện có.

## Thu thập và chạy model

```bash
.venv/bin/python prepare_regions.py --plan
.venv/bin/python prepare_regions.py
.venv/bin/python precompute_regions.py --region 900010
docker compose up -d --build --force-recreate
```

Cấu hình: `preparation/regions_config.json`. Mỗi khối tối đa 40 ngày thật,
tối thiểu 30; cùng chất lượng/scale/offset và đúng tiền xử lý TSViT hiện có.
Ngày được chọn theo độ phủ mùa và chất lượng từng khối, không giả định mọi
khối có cùng ngày. Provenance mỗi khối được lưu và đưa vào kết quả xuất.
Không dùng dữ liệu nhãn làm prediction hay để mask kết quả web.

Hai khối được chuẩn bị song song, mỗi khối bốn HTTP reader. Từng ngày hoàn
tất có cache nguyên tử; chạy lại lệnh để tiếp tục sau lỗi mạng. Truyền thiếu
đoạn TIFF được đọc lại. Catalog cập nhật có khóa để không mất khối khi hai
worker kết thúc cùng lúc. Vùng ghép chỉ công bố sau khi chín khối hoàn tất.

Không ghép chín cube thành một file ảnh lớn thứ hai. Provider chọn đúng
khối và DOY cho mỗi cửa sổ 24×24; lưới khối chia hết cho 24 nên không xuất
hiện cửa sổ model cắt ngang hai lịch ảnh. Valid mask ghép theo tọa độ native.

Mảng float32 40×10×2304×2304 chiếm khoảng **7,91 GiB**, chưa gồm cache tải.
Giữ khoảng 20 GiB trống cho chuỗi ảnh, cache và đóng gói; HTTP traffic phụ
thuộc COG/retry và có thể lớn hơn dung lượng cuối. Dữ liệu được mmap khi đọc.

## Prediction và bản đồ

`precompute_regions.py` chạy checkpoint thật, lưu labels/confidence theo
cửa sổ và có thể tiếp tục từ cửa sổ đã hoàn tất. Có thể dùng môi trường
PyTorch CUDA tương thích với `CROP_DEVICE=cuda:0`; mặc định CPU. Bản web
không yêu cầu GPU. Batch mặc định 1, có tùy chọn `--batch-size` 1–8.

Prediction có khóa theo dataset version, checkpoint SHA, region ID và
pipeline version. File `ready.json` chỉ ghi sau khi hoàn tất các mảng và
GeoTIFF. Vùng lớn dùng lại prediction từng khối; không chạy model thêm lần
nữa. Thay dữ liệu/model làm vô hiệu kết quả cũ; không tự dùng prediction
khác checkpoint.

Web hiển thị classification bằng XYZ tile 256×256, nearest cho lớp rời rạc.
Nodata 255 trong suốt; background 0 vẫn là một lớp hợp lệ. Chỉ phần đang
nhìn thấy được đọc, và tile được cache. Bấm bản đồ để xem lớp/confidence.

Người dùng chọn vùng bất kỳ trong vùng ghép, kể cả qua nhiều khối, để lấy
thống kê và tải GeoTIFF/CSV/PNG/GeoJSON/ZIP từ prediction đã lưu. Nút **Whole
region** chọn toàn vùng. Vùng chọn nhỏ được cắt theo lưới native trước khi
xuất; GeoJSON được ghi từng polygon để giảm RAM cho vùng lớn. UI ghi rõ kết
quả là classification lưu sẵn. Không chạy lại model trong luồng xuất này.

Vùng chưa có prediction vẫn dùng luồng inference trực tiếp với giới hạn
256 cửa sổ/lượt như trước. Tám vùng PASTIS đối chiếu vẫn dùng được khi có ảnh thô.

## Gói EC2 gọn

```bash
.venv/bin/python package_deploy.py --predictions-only
```

Gói gồm code Docker, checkpoint, catalog ghép, mask, prediction, ảnh RGB
xem trước và provenance. **Không có cube chuỗi ảnh hoặc cache tải**. Mở bản
đồ, xem pixel, chọn vùng, tính diện tích và xuất file đều chạy offline với
dữ liệu này; basemap Esri cần Internet. Server kiểm tra checkpoint khớp
prediction khi khởi động. Muốn chạy lại model sau này cần giữ raw cube ở
máy chuẩn bị hoặc dùng gói đầy đủ bằng lệnh không có `--predictions-only`.

Các bước tạo EC2/Docker ở `README_DEPLOY.md`. Giữ thiết kế web hiện tại;
chưa tạo instance AWS hay công khai dịch vụ trong quá trình chuẩn bị local.

## Chạy thu thập trên Kaggle

Notebook độc lập: `preparation/prepare_regions_kaggle.ipynb`. Bật Internet,
CPU; không cần API key hoặc nhãn. Giữ output/cache khi kết thúc phiên nếu
chưa hoàn tất. Notebook này chuẩn bị ảnh; precompute chạy bằng công cụ trên.

## Kiểm tra

```bash
.venv/bin/python -m pytest -q test_regions.py test_cog_data.py test_pastis_demo.py test_app.py
```

Kiểm tra khối liền nhau với lịch ảnh khác nhau, nhãn/valid mask, GeoTIFF qua
ranh giới, loại cache khác dữ liệu/model, và API hoạt động khi đã bỏ raw cube
khỏi gói inference. Chất lượng phân loại toàn vùng mới chưa được benchmark
bằng nhãn; kiểm thử kỹ thuật không thay thế đánh giá độ chính xác.
