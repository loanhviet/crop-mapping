# Crop Map

Web theo Figma/slide 3 hiện tại: chọn vùng và mùa → chạy checkpoint TSViT thật
→ bản đồ phân loại, thống kê diện tích, tra pixel và xuất kết quả. Nguồn mặc
định là **ảnh Sentinel-2 đã chuẩn bị trên máy**, không cần tài khoản GEODES để demo.

**Vùng liên tục:** [README_REGIONS.md](README_REGIONS.md) mở rộng Normandy
thành **23,04×23,04 km (~531 km²)** từ chín khối ảnh thật. Chuẩn bị chuỗi ảnh
và chạy TSViT trước một lần; web hiển thị lớp phân loại toàn vùng bằng map
tile, cho phép chọn vùng qua nhiều khối để thống kê/xuất. Gói EC2 có thể chỉ
chứa prediction và RGB preview, không cần mang gần 8 GiB chuỗi ảnh.
Bản một khối ban đầu ở [README_COG.md](README_COG.md); tám patch PASTIS
bên dưới vẫn là nguồn đối chiếu khi chạy với dữ liệu đầy đủ.

## Chạy local

```bash
./run.sh
```

Mở **http://127.0.0.1:8000**. Chọn vùng bằng **Available region** ở góc bản đồ.
Web tự zoom theo vùng, hiện ảnh Sentinel-2 thực và classification nếu đã
chuẩn bị. Bấm **Select area** để khoanh vùng hoặc **Whole region** để chọn
toàn vùng đã có prediction. **Analyze selected area** thống kê/xuất prediction
đã lưu; vùng chưa có prediction chạy mô hình trực tiếp trong giới hạn mỗi
lượt. Không dùng nhãn thật làm kết quả.

Giao diện giữ panel, màu/font/icon, bản đồ, tiến độ, lớp phủ, bảng diện tích,
tra pixel và hộp xuất file của thiết kế đã có. Chỉ thêm lựa chọn vùng có dữ
liệu, đường bao phủ và thay lời hướng dẫn theo nguồn ảnh local.

## Dữ liệu demo

```bash
.venv/bin/python prepare_data.py
```

Công cụ tải riêng các thành viên cần thiết từ PASTIS.zip chính thức bằng
HTTP Range; không tải toàn bộ archive. Mặc định tám patch **fold 5/test**:

| Khu vực | Patch | Số quan sát gốc mỗi patch |
| --- | --- | --- |
| Normandy / T30UXV | 10003, 10010 | 43 |
| Provence / T31TFJ | 20000, 20004 | 61 |
| Rhône / T31TFM | 30001, 30004 | 46 |
| Alsace / T32ULU | 40002, 40005 | 38 |

Mỗi patch gốc 128×128 được dùng phần 120×120: 25 cửa sổ 24×24 không chồng
lấn, diện tích khả dụng **144 ha/patch**, tám patch là **1.152 ha rời nhau**.
Đây không phải một vùng liên tục hoặc khả năng dự đoán trên toàn bản đồ.
Tám pixel mép phải/dưới bị bỏ theo cách cắt PASTIS24; preview và đường bao
cũng dùng đúng phần 120×120.

Không cần tải lại cả bộ PASTIS24 trên Drive. Dùng các chuỗi PASTIS gốc làm
nguồn, cắt theo lưới PASTIS24 lúc dự đoán; tọa độ lấy từ metadata chính thức.
Nguồn này được giữ nguyên, không áp dụng chính sách lọc mây của dữ liệu tự
thu. Nhãn TARGET không được đọc trong luồng inference.

Mùa hiển thị 2018–2019 là tên bộ dữ liệu; lịch PASTIS thực có thể kéo dài từ
tháng 9/2018 tới tháng 10/2019, ngày chính xác hiện trên UI và exports. Giữ
thứ tự DOY đã đối chiếu với pickle 10000_0 cho các patch cùng lịch. Những lịch
khác dùng sort DOY ổn định, giữ thứ tự acquisition khi trùng DOY; chưa xác
nhận khớp từng pickle PASTIS24 không có trên máy. Không gọi đây là benchmark
tái lập đầy đủ PASTIS24.

Thêm hoặc chọn patch khác:

```bash
.venv/bin/python prepare_data.py --patches 10003 10010 20000
```

Catalog được ghi sau khi tải thành công. Giữ các patch đã cài; UI chỉ quảng
bá patch test có file trên máy. Patch 10000/train cũ vẫn giữ cho kiểm tra
parity local, không đưa vào danh sách demo hoặc gói EC2.

## Mô hình và đầu ra

- Kiến trúc giữ nguyên TSViT, 1.657.476 tham số, checkpoint `weights/best.pth`.
- Đúng thứ tự 10 band: B2/B3/B4/B5/B6/B7/B8/B8A/B11/B12.
- Normalize fold 1 → DOY/365.0001 → cut/pad 60 → THWC `[60,24,24,11]`.
- Chuỗi >60 ngày bị cắt, chuỗi ngắn hơn được pad zero theo code train.
- 19 lớp đầu ra 0–18; void 19 là nhãn đánh giá, không phải lớp mô hình.
- Xuất GeoTIFF UTM, CSV, PNG, GeoJSON WGS84 và ZIP. Pixel ngoài lựa chọn
  là nodata 255; diện tích tính từ tâm pixel 10 m, 0,01 ha/pixel.
- Nền Esri chỉ để định vị, có thể khác ngày ảnh phân tích. Lớp **Acquired
  Sentinel‑2** hiển thị ảnh PASTIS thực với ngày chụp.
- Confidence là xác suất mô hình; chưa có đánh giá độ chính xác mới cho các
  vùng demo. Thời gian thực tế phụ thuộc CPU, số cửa sổ và hàng chờ.

## Docker và EC2

```bash
docker compose up -d --build
docker compose ps
```

Truy cập http://127.0.0.1:8000. Checkpoint và ảnh mount read-only; kết quả nằm
trong named volume riêng, tồn tại sau khi thay container. Docker chạy CPU,
một worker, giới hạn bốn job đang chờ/chạy. Không đóng dữ liệu, API key hoặc
checkpoint DINOv3 vào image.

Đóng gói code + checkpoint + tám vùng test bằng:

```bash
.venv/bin/python package_deploy.py
```

Xem **[README_DEPLOY.md](README_DEPLOY.md)** cho cách chuyển gói lên Ubuntu
EC2, cài Docker, mở cổng, chạy, cập nhật, sao lưu và dừng.

## Kiểm tra

```bash
.venv/bin/python -m pytest -q test_app.py test_pastis_demo.py
```

Kiểm tra gồm tọa độ, chọn vùng, chuẩn hóa/padding, nodata/background, inference
checkpoint thật, preview, exports và xác nhận chế độ PASTIS không gọi dịch
vụ lấy ảnh. Kiểm tra GEODES trước đó vẫn giữ bằng `CROP_SOURCE=geodes`.
Kiểm tra vùng liên tục/resume/mask/giới hạn/cache bằng `test_cog_data.py`.

## Các task và nguồn khác

- Task 1 DINOv3 nằm riêng tại `../DeepSatModels-DINOv3/`; web tiếp tục dùng TSViT.
- Task 2: [hướng dẫn](data_collection/README.md),
  [notebook Kaggle](data_collection/collect_sample_kaggle.ipynb). Bộ tự thu
  25.000 mẫu không nằm trong gói deploy.
- Tài liệu chi tiết GEODES cũ lưu tại [README_GEODES.md](README_GEODES.md).
  Chạy live ngoài Compose bằng `CROP_SOURCE=geodes ./run.sh`; cần key và quyền
  tải riêng, có thể mất nhiều thời gian do nguồn tải toàn cảnh.

## Nguồn

- [Figma](https://www.figma.com/design/xSpZ4Xx9FfvhpIMIX2MUeL?node-id=2-305).
- [PASTIS chính thức](https://github.com/VSainteuf/pastis-benchmark),
  [dữ liệu và giấy phép CC BY 4.0](https://zenodo.org/records/5012942).
- [Code/checkpoint TSViT của nhóm](https://github.com/loanhviet/tsvit-crop-segmentation),
  commit `d47d88c948b8fd3d1cdc8ab15390ba526784dfcb`, Apache-2.0;
  [nguồn tác giả](https://github.com/michaeltrs/DeepSatModels).
- SHA256 checkpoint: `92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733`.
- Giấy phép model trong `weights/LICENSE.txt`; Leaflet/font/icon giữ trong
  `web/assets/`. Gói deploy kèm danh mục SHA256 và nguồn dữ liệu.
