# Vùng Sentinel-2 liên tục cho web

Đây là bản một khối ban đầu; vùng mở rộng hiện tại ở [README_REGIONS.md](README_REGIONS.md).

Vùng Normandy một khối rộng **7,68 × 7,68 km = 5.898,24 ha**, phủ cả phần
trùng patch PASTIS 10003. Chuẩn bị ảnh một lần, sau đó web chỉ đọc cửa sổ
local để dự đoán; không tải ảnh khi người xem bấm Analyze.

## Chuẩn bị local

```bash
.venv/bin/python prepare_cog.py --plan
.venv/bin/python prepare_cog.py
```

Cấu hình tại `preparation/cog_config.json`: tối đa 40 ngày thật, tối thiểu 30,
mùa 01/10/2018–30/09/2019, chọn phủ thời gian trong số ngày đạt chất lượng.
STAC gộp Collection-1 và catalog cũ, giữ một bản/ngày và một tile phủ cả vùng.
Đọc SCL trước; chỉ tải đủ 10 kênh cho các ngày được chọn. Không cần key/GPU.

- Ngày được giữ khi ít nhất 50% vùng là SCL 4/5/6 và ít nhất 99% có dữ liệu
  native hợp lệ; SCL 1 bị loại. Đây là ngưỡng cấu hình, không phải ảnh sạch
  mây hoàn toàn. Reflectance còn mây không được nội suy hoặc thay bằng ảnh giả.
- Pixel được xuất prediction khi hợp lệ native trong mọi ngày được chọn và
  có ít nhất ba quan sát SCL 4/5/6. Pixel không đủ điều kiện là nodata 255.
- Band dùng bilinear, SCL dùng nearest. Scale/offset đọc từ metadata rồi đưa
  về reflectance ×10000 trước tiền xử lý TSViT gốc.
- Thứ tự band giữ B2/B3/B4/B5/B6/B7/B8/B8A/B11/B12; DOY sort ổn định rồi
  padding zero tới 60. Không dùng kênh RGB đơn lẻ cho TSViT.

Code lưu từng ngày hoàn tất bằng file nguyên tử. Nếu mạng lỗi, chạy lại đúng
lệnh để dùng cache; không đổi slug/cấu hình dữ liệu giữa chừng. Có thể đổi
`workers` (1–8) vì chỉ là cấu hình tải. Catalog web chỉ ghi khi cube hoàn tất.
Sau khi dữ liệu sẵn, chạy lại công cụ sẽ kiểm tra checksum và dùng bản đã có.
Đọc TIFF lỗi được mở lại; cache HTTP theo URL dùng tiền tố `/vsicurl/`
theo [hướng dẫn GDAL](https://gdal.org/en/stable/user/virtual_file_systems.html).

Mảng 40 ngày/10 kênh float32/768×768 là **900 MiB**, chưa tính mask/cache.
HTTP traffic có thể lớn hơn do cấu trúc tile COG, nhiều mức phân giải và retry.
Cache ngày phục vụ resume có thể chiếm thêm gần một bản dữ liệu; không đóng
cache vào gói deploy. Ảnh lưu `.npy` có thể mmap, không nạp toàn cube vào RAM.

Bản local ngày 17/10/2026 đã tải đủ 40 ngày từ 146 ngày catalog, khoảng trống
lớn nhất giữa hai quan sát là 28 ngày; 94,33% pixel đạt chính sách native/clear.
Thời gian chuẩn bị ghi nhận 372,93 giây trên mạng/máy hiện tại, không phải
cam kết cho máy hoặc dịch vụ khác. Chưa đo riêng tổng HTTP payload của lượt này.

## Dùng trên web

```bash
docker compose up -d --build
```

`CROP_SOURCE=prepared` nạp cả catalog COG đã hoàn tất và PASTIS đối chiếu.
Vùng COG hiện trước trong Available region; bản đồ zoom theo toàn vùng và
hiển thị preview từ một ngày thật có độ phủ rõ cao.

Lựa chọn ban đầu là **1,92 × 1,92 km**, 64 cửa sổ. Có thể vẽ vùng khác trong
coverage; giới hạn mỗi lượt là **256 cửa sổ 24×24**, xấp xỉ vùng 3,84×3,84 km
nếu thẳng theo lưới. Hình chữ nhật WGS84 có thể cắt thêm cửa sổ ở mép nên
số cửa sổ thực tế quyết định giới hạn, không chỉ diện tích.

API kiểm tra giới hạn trước khi tạo job. Dự đoán từng cửa sổ với đúng tọa độ
gốc rồi ghép lên raster của vùng; chỉ pixel trong lựa chọn và có dữ liệu hợp
lệ được thống kê. Không mask theo nhãn thật.

Yêu cầu giống nhau được tái sử dụng kết quả đã hoàn thành theo geometry,
region ID, mùa, phiên bản dữ liệu/mask, checkpoint và phiên bản pipeline.
UI thông báo khi dùng kết quả cũ. Kết quả cache tồn tại trong volume sau
restart; dữ liệu mới/checkpoint khác không được dùng lại prediction cũ.

## Chạy Kaggle/Colab

Notebook độc lập: `preparation/prepare_continuous_kaggle.ipynb`. Bật Internet,
CPU là đủ. Notebook chứa đúng source `cog_data.py`, không cần clone repo.

Sau khi hoàn tất, cell export tạo `continuous-cog.tar.gz` và checksum. Lưu
Output hoặc tải gói về trước khi kết thúc phiên. Nếu cần dừng sớm, export
với `INCLUDE_CACHE=True` để mang theo các ngày đã tải. Phiên sau thêm vào
Input, đặt `RESTORE_PATH` tới archive hoặc thư mục chứa `cog/` đã giải nén.

Đưa về máy chạy web:

```bash
tar -xzf /path/to/continuous-cog.tar.gz -C data
docker compose up -d --force-recreate
```

Chỉ giải nén gói của bạn; nếu web đã có một vùng cùng ID/slug thì kiểm tra
phiên bản trước khi thay. Cấu hình khác dùng slug và ID khác để tách dữ liệu.

Để cập nhật notebook khi sửa acquisition code:

```bash
.venv/bin/python preparation/build_cog_notebook.py
```

## Kiểm tra tương thích

Đã đọc thử cùng lưới/ngày với PASTIS 10003: hai ngày ít mây cho tương quan
pixel khoảng 0,96–0,999 tùy band; mức phản xạ vẫn khác. Ngày 17/01/2019
bị mây ở ô thử nên không dùng để suy luận tương đương radiometry.

Sau khi cube sẵn, đánh giá phần trùng bằng checkpoint thật:

```bash
.venv/bin/python validate_cog.py
```

Kết quả tại `data/cog/normandy-2018-2019/overlap-validation.json`, so sánh
PASTIS và COG trên cùng pixel nhãn hợp lệ. Nhãn chỉ được đọc trong công cụ
đánh giá này; không nằm trong luồng web hay gói EC2. Hai chuỗi có lịch khác
nhau, nên đây không phải thí nghiệm chỉ thay nguồn hay benchmark toàn bộ.
Không suy rộng độ chính xác của một patch cho toàn vùng mới.

Bản local đã đánh giá 12.941 pixel có nhãn trên phần trùng PASTIS 10003:
PASTIS 43 ngày đạt OA 87,34%, COG 40 ngày đạt OA 88,09%. mIoU trên **cùng
tập 11 lớp thuộc hợp union của hai prediction/ground truth** lần lượt là
0,5800 và 0,5658, gồm background. Nếu mỗi lần tự chọn tập lớp có union riêng
thì mIoU thay đổi mẫu số, không dùng hai số đó để so trực tiếp.

## Đóng gói EC2

```bash
.venv/bin/python package_deploy.py
```

Gói lấy code/checkpoint, PASTIS test và cube đã công bố, mask, config/report;
không lấy cache tải, dữ liệu task 2 hoặc token. File lớn được hash theo từng
khối để hạn chế RAM. Xem `README_DEPLOY.md` cho bước EC2.

Nguồn: [Earth Search](https://earth-search.aws.element84.com/v1),
[Sentinel-2 COG](https://registry.opendata.aws/sentinel-2-l2a-cogs/),
[PASTIS](https://zenodo.org/records/5012942).
