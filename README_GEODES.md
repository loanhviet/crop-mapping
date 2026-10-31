# Crop Map

Ứng dụng theo giao diện Figma/slide 3, dùng checkpoint TSViT và luồng chọn vùng → lấy ảnh THEIA/GEODES → tiền xử lý → dự đoán.

Task 2 thu thập dữ liệu có [hướng dẫn riêng](data_collection/README.md) và
[notebook Kaggle độc lập](data_collection/collect_sample_kaggle.ipynb): lấy Sentinel-2
COG + polygon RPG, xuất cửa sổ ảnh–nhãn 24×24, hỗ trợ chạy tiếp đến mục tiêu
60.825 mẫu. Mỗi khối lấy ngẫu nhiên 8–12 ngày thật, có seed; mọi mẫu đi qua
Normalize/DOY/cut-pad/THWC và ghép target theo slide 2. Notebook mặc định chạy
thử 100 mẫu; báo cáo ghi số thực tế đã thu.

## Chạy

```bash
cd /home/viet/projects/TLU/TSViT/crop-map
./run.sh
```

Mở **http://127.0.0.1:8000**. Frontend HTML/CSS/JavaScript + Leaflet; backend FastAPI/PyTorch. Không cần Node.js hoặc build frontend.

Nhấn **Select area**, chọn hai góc đối diện trên bản đồ và chọn mùa vụ. Ứng dụng kiểm tra catalog trước, hiển thị số cảnh, số cảnh đã chuẩn bị và dung lượng cần tải. Nhấn **Analyze selected area** để tải/tiền xử lý/chạy TSViT. UI hiển thị tiến độ từng cảnh, số GB, tốc độ tải, thời gian chờ và cho hủy. Kết quả gồm bản đồ phân loại, thống kê, tra pixel và GeoTIFF/CSV/PNG/GeoJSON/ZIP.

## Kết nối GEODES

Key hiện đã được cấu hình trong `.env` trên máy này. Khi cài máy khác:

```bash
cp .env.example .env
chmod 600 .env
```

Điền `GEODES_API_KEY` từ **https://geodes-portal.cnes.fr → My information → Generate**. Backend đọc `.env` khi nhận yêu cầu; không đưa key vào frontend, kết quả xuất hoặc Git. Tạo tài khoản THEIA miễn phí; GEODES áp dụng quota tài khoản. Quota xử lý trên GEODES không phải quota chạy TSViT trên máy riêng.

**Giới hạn quan trọng:** [FAQ chính thức](https://geodes.cnes.fr/support/faq/) xác nhận GEODES hiện tải cả cảnh, chưa hỗ trợ subsetting theo AOI. Một vùng nhỏ vẫn có thể cần hàng chục GB cho cả mùa. Không thể cam kết phản hồi trong vài giây khi lấy dữ liệu mới hoàn toàn. Cần chuẩn bị ảnh trước/cache cho các vùng và mùa sẽ phục vụ, hoặc tích hợp nguồn THEIA có định dạng cho phép đọc cửa sổ khi mở rộng.

Mỗi cảnh được tải bằng một GET, cắt/căn chỉnh cục bộ rồi bỏ ZIP tạm. Ảnh cắt và mặt nạ chất lượng lưu trong `data/imagery/`; chạy lại cùng lưới/nguồn/phiên bản dùng cache, kể cả sau khi hủy hoặc khởi động lại. Lưới cố định theo ô 240 m giúp các lựa chọn gần nhau dùng chung phần ảnh. Cache hiện chưa tự dọn; có thể xóa khi không cần. Không còn đọc ZIP nén từ xa bằng hàng loạt byte-range request tiêu tốn quota.

HTTP 429 hoặc thông báo quota được hiển thị thành trạng thái chờ và có thể hủy. Lỗi tạm thời 500/502/503/504 thử lại tối đa hai lần. Key sai hoặc không đủ ảnh được báo riêng. Sản phẩm chỉ lưu trên băng chưa được tự phục hồi; phiên bản đầu dùng sản phẩm online.

Để chuẩn bị vùng/mùa trước khi người dùng phân tích, dùng cùng pipeline từ terminal:

```bash
# Chỉ xem số cảnh/dung lượng, không tải ảnh
.venv/bin/python prepare_data.py --geodes area.geojson --season 2018–2019 --plan
# Tải và chuẩn bị cache; UI sẽ tái sử dụng
.venv/bin/python prepare_data.py --geodes area.geojson --season 2018–2019
```

`area.geojson` chứa Polygon WGS84 hoặc Feature có geometry Polygon. Chạy script không có `--geodes` vẫn chỉ chuẩn bị hai vùng PASTIS đối chiếu. Chưa tự chạy lịch tải định kỳ; khi deploy có thể gọi cùng công cụ này từ worker/lịch nền.

## Cấu trúc

```text
crop-map/
├── app.py              # API, hàng chờ một worker, trạng thái và phục vụ UI
├── imagery.py          # Catalog GEODES, tải, cache, căn chỉnh, kiểm tra chất lượng
├── inference.py        # Tiền xử lý khớp train, nạp model, dự đoán, xuất kết quả
├── model.py            # Kiến trúc TSViT khớp checkpoint
├── prepare_data.py     # Chuẩn bị cache GEODES trước; PASTIS để đối chiếu
├── test_app.py         # Kiểm tra acquisition, inference, địa lý, quota và cache
├── .env.example        # Cấu hình mẫu; .env thật nằm ngoài Git
├── requirements.txt
├── run.sh
├── web/                # HTML, CSS, JS, bản đồ, icon, font
├── weights/            # best.pth, config.yaml, giấy phép mô hình
└── data/
    ├── imagery/        # Cache ảnh đã cắt/căn chỉnh, không chứa key
    └── results/        # Kết quả và trạng thái theo UUID
```

API, nguồn ảnh và mô hình tách nhau để sau này thêm nguồn, worker/GPU và CI/CD/deploy. Hiện checkpoint nạp một lần, một worker xử lý lần lượt, tối đa bốn yêu cầu chờ/chạy. Chưa thêm Docker/CI/CD theo phạm vi hiện tại. Backend phục vụ local mặc định; triển khai công khai cần bổ sung xác thực, quản lý quota/cache và worker trước.

## Theo slide 2

Nhánh ảnh: **AOI/mùa → catalog THEIA Sentinel‑2 L2A → cảnh ảnh online → đọc 10 kênh và chất lượng → căn chỉnh UTM/lưới 10 m → chuỗi thời gian → ô 24×24 → Normalize → ghép DOY/365.0001 → cut/pad 60 → THWC → TSViT → phân loại và diện tích**.

- Kênh theo thứ tự B2, B3, B4, B5, B6, B7, B8, B8A, B11, B12. Reflectance mặc định FRE (hiệu chỉnh địa hình); hệ số lượng tử hóa và nodata đọc từ XML MUSCATE, đưa DN về thang 10000. Nội suy bilinear khi căn chỉnh/resample ảnh; nearest cho mask. Cần đối chiếu FRE/SRE với ảnh train trước khi kết luận tương đương radiometry.
- Chuẩn hóa đúng mean/std fold 1 của checkpoint. Input `[60,24,24,11]`, 19 lớp gồm background. Nhãn void 19 không phải đầu ra. Pad thời gian toàn zero như code train.
- Mùa được định nghĩa 01/10 đến 30/09, chỉ chọn mùa hoàn tất từ 2016–2017. Dùng `start_datetime` (ngày chụp), không dùng `datetime` (ngày nhập catalog). Chọn phiên bản mới nhất theo acquisition/tile; lưu phiên bản xử lý và ngày trong provenance.
- Mặc định lọc cloud-cover cả tile ≤30% trước khi tải để giảm dung lượng. Nếu >60 cảnh thì lấy đều theo thời gian; sau đó sắp theo DOY và ngày chụp. Năm nhuận quy về lịch 365 ngày (29/02 dùng DOY 28/02); checkpoint chỉ có 365 vị trí ngày.
- Dùng CLM (strict cloud/shadow), EDG, SAT và tuyết MG2 để kiểm tra. Bỏ cảnh nếu dưới 50% pixel AOI rõ/không lỗi. Giữ reflectance của cảnh được chọn, không tự tạo ảnh sạch mây. Chỉ xuất pixel có dữ liệu native ở mọi cảnh giữ lại và ít nhất ba quan sát rõ. Không đủ dữ liệu thì báo thiếu; phần bị loại là nodata 255, thống kê riêng khỏi background 0.
- Đây là chính sách vận hành cho nguồn mới, khác lịch 43 cảnh PASTIS có sẵn. Sản phẩm THEIA mới có thể đã reprocess. Chưa có đánh giá độ chính xác trên các vùng/năm mới; cùng loại nguồn và tensor đúng không bảo đảm cùng chất lượng dự đoán.
- IGN/RPG là nhánh nhãn để train/evaluate; dự đoán với checkpoint không yêu cầu nhãn thật và không dùng nhãn thật để mask kết quả.
- Bản đầu xử lý AOI trong một tile, giữa 80°S và 84°N; lưới bao tối đa 160000 pixel (1600 ha), chia hết 24. AOI qua ranh tile được báo cần chọn lại. Không phụ thuộc hai vùng PASTIS cũ; API `patch_id` còn giữ cho kiểm tra/khôi phục cũ.
- Diện tích = số tâm pixel 10 m hợp lệ ×100 m². GeoTIFF giữ UTM; ảnh overlay reproject sang Web Mercator; GeoJSON WGS84. Confidence là xác suất model, không phải độ chính xác đã kiểm định.
- Esri là nền tham khảo, có thể khác mùa phân tích. **Map layers → Acquired Sentinel‑2** hiển thị preview từ ảnh vừa phân tích, với ngày chụp thật.

## Cấu hình

`.env` hỗ trợ `GEODES_API_KEY`, `GEODES_REFLECTANCE` (`FRE`), `GEODES_MAX_DOWNLOAD_GB` (64), `GEODES_MAX_CLOUD_PERCENT` (30), `CROP_MAX_GRID_PIXELS` (160000). Kiểm tra dung lượng dự kiến trước khi tải; giới hạn GB theo 1024³ byte. Tăng giới hạn có thể kéo dài đáng kể thời gian tải. Thu nhỏ AOI không làm gói ZIP gốc nhỏ hơn.

Biến môi trường chạy model: `HOST` (127.0.0.1), `PORT` (8000), `CROP_DATA_DIR`, `CROP_WEIGHTS_DIR`, `CROP_THREADS` (4), `CROP_DEVICE` (`cpu`). Ví dụ `PORT=8001 ./run.sh`.

Kết quả hoàn tất tồn tại sau restart; UI khôi phục phân tích gần nhất. Yêu cầu bị gián đoạn được báo để chạy lại; cache cảnh đã chuẩn bị vẫn dùng được. Kết quả/cache chưa tự xóa. `data/results/` và `data/imagery/` có thể dọn thủ công. Checkpoint và dữ liệu PASTIS đối chiếu không cần tải lại.

## Kiểm tra

```bash
.venv/bin/python -m pytest -q test_app.py
```

13 kiểm tra: chuẩn hóa/padding, tọa độ, nodata/background, real-checkpoint inference và export, định dạng MUSCATE với bands 10/20 m, scale XML, mask chất lượng, một GET/cảnh, không truyền key sang host redirect, quota/hủy, thiếu key, tái sử dụng cache và scale/offset/nodata của COG. Phần acquisition end-to-end trong test dùng HTTP fixture và raster giả lập để kiểm tra logic; không phải xác nhận đã tải cả mùa GEODES thật. Catalog và quyền tải đã kiểm tra trực tiếp bằng key trên máy này. `data/verification.json` giữ kiểm tra parity với code train và mẫu PASTIS24 Drive (tensor sai số 0).

## Thử chuỗi COG cả mùa

`benchmark_cog.py` là công cụ thử nghiệm riêng; chưa đổi nguồn mặc định của app. Công cụ kiểm tra mặt nạ SCL ở mọi ngày của mùa, đọc đủ 10 kênh cho chuỗi 60 ngày chụp thật trải đều và chuỗi đã lọc mây, rồi chạy checkpoint thật. Catalog gốc và Collection-1 được kết hợp để tránh khoảng trống lịch sử; provenance ghi nguồn/phiên bản và scale/offset của từng kênh.

```bash
.venv/bin/python benchmark_cog.py --geometry area.geojson --season 2018–2019 --workers 4 --output data/benchmarks/my-season
```

Thư mục output phải mới. Kết quả gồm `report.html`, `report.json`, ảnh RGB theo 60 ngày, mặt nạ chất lượng, dữ liệu 10 kênh, tensor `[60,24,24,11]` của một ô và các file phân loại. Báo cáo đo tải lạnh, đọc cache, số frame phải pad, phân bố theo tháng và khoảng thiếu quan sát lớn nhất. Chuỗi 60 ngày còn ảnh mây chỉ dùng đo latency. Chuỗi sau lọc cũng cần kiểm định độ chính xác khi dùng nguồn khác THEIA. HTTP payload được tính từ response Content-Range, không gồm overhead mạng. Mỗi phép đo chỉ đại diện vùng/mùa, mạng và máy đang chạy.

## Nguồn

- Thiết kế: https://www.figma.com/design/xSpZ4Xx9FfvhpIMIX2MUeL?node-id=2-305
- GEODES API: https://geodes.cnes.fr/support/api/; hạn chế subsetting: https://geodes.cnes.fr/support/faq/
- Định dạng MAJA: https://www.cesbio.cnrs.fr/maja/sentinel-2-output-format/
- Mã model: https://github.com/loanhviet/tsvit-crop-segmentation, commit `d47d88c948b8fd3d1cdc8ab15390ba526784dfcb`. Apache-2.0, giấy phép trong `weights/LICENSE.txt`.
- Checkpoint SHA256: `92a83d0d94e529e762233c571efdcf36513cf503b678fc9dba09b8171a40b733`.
- PASTIS đối chiếu: https://github.com/VSainteuf/pastis-benchmark; https://zenodo.org/records/5012942
- Leaflet 1.9.4, Carlito; giấy phép giữ trong `web/assets/`.
