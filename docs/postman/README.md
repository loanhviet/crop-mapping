# Kiểm tra API Crop Map bằng Postman

API của dự án là HTTP REST, được định nghĩa bởi các decorator trong `app.py`. FastAPI phục vụ cả web và API trong cùng ứng dụng. Request phân tích chứa JSON và GeoJSON Polygon; model chạy dưới dạng tác vụ nền, nên POST trả mã tác vụ trước khi có kết quả cuối.

Tài liệu và collection này áp dụng cho **CROP_SOURCE=prepared** hoặc `pastis`, có dữ liệu local tương ứng. Collection ưu tiên patch test `10003` và một vùng nhỏ bên trong để test nhanh. Bản hiện tại không yêu cầu đăng nhập hoặc Bearer token cho API.

## 1. Khởi động backend

Tại thư mục `crop-map`, dùng một trong hai cách:

```bash
./run.sh
```

Hoặc:

```bash
docker compose up -d --build
```

Địa chỉ mặc định: `http://127.0.0.1:8000`.

- Giao diện: `http://127.0.0.1:8000/`.
- Swagger UI: `http://127.0.0.1:8000/docs`.
- Đặc tả OpenAPI: `http://127.0.0.1:8000/openapi.json`.

Nếu chạy server trên máy khác, thay địa chỉ bằng host và cổng thực tế mà Postman truy cập được. Docker Compose mặc định chỉ bind localhost. `base_url` không có `/api` ở cuối vì mỗi request đã chứa phần đó.

## 2. Import bộ request có sẵn

Trong Postman, chọn **Import** rồi chọn `Crop-Map.postman_collection.json` trong thư mục này. Collection đã có biến `base_url=http://127.0.0.1:8000` và Authorization là No Auth.

Chạy lần lượt các request trong folder **01 - Luồng phân tích thành công**. Request catalog tự lưu thông tin mẫu vào Collection Variables. Request tạo phân tích tự lưu mã tác vụ vào `job_id`.

Nếu chạy tự động bằng **Collection Runner**, chọn folder 01, Iterations = 1 và Delay = 400 ms. Request theo dõi trạng thái sẽ tự lặp khi `queued` hoặc `running`, tối đa `max_polls` lần. `pm.execution.setNextRequest()` chỉ điều hướng khi chạy collection; nếu bấm Send từng request thì bạn tự Send lại request GET trạng thái.

Folder **02 - Kiểm tra lỗi đầu vào** chạy sau khi folder 01 hoàn thành. Các HTTP 422/404 trong folder này là kết quả mong đợi và có assertion tương ứng. Folder **03 - Hủy tác vụ** dùng thủ công ngay sau khi tạo job nếu muốn thử hủy. Nếu job đã done, DELETE có thể trả `cancellation_requested=false`; đó là hành vi hợp lệ.

Không tạo Environment Variables trùng tên `job_id`, `geometry`, `patch_id`, `season`, `lat`, `lng` nếu muốn dùng script của collection: environment có thể ghi đè giá trị Collection Variables. Chỉ cần đổi `base_url` nếu địa chỉ server khác.

## 3. Làm thủ công để hiểu luồng

### Bước A — Kiểm tra server và xem dữ liệu

```http
GET http://127.0.0.1:8000/api/health
GET http://127.0.0.1:8000/api/catalog
```

Trong catalog, xem `patches`, `seasons` và `classes`. `patch_id` phải thuộc dữ liệu đã cài; geometry phải nằm trong vùng tương ứng. Việc nhìn thấy một vị trí trên nền Esri không có nghĩa backend có ảnh tại vị trí đó.

### Bước B — Kiểm tra vùng chọn

Tạo request:

```http
POST http://127.0.0.1:8000/api/imagery-plan
Content-Type: application/json
```

Trong Postman: **Body → raw → JSON**, dán nội dung `request-mau.json`:

```json
{
  "patch_id": 10003,
  "season": "2018–2019",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-0.362, 49.304],
      [-0.360, 49.304],
      [-0.360, 49.302],
      [-0.362, 49.302],
      [-0.362, 49.304]
    ]]
  }
}
```

Đầu và cuối vòng tọa độ phải trùng nhau. GeoJSON dùng **[kinh độ, vĩ độ]**. `geometry` là đối tượng JSON, không phải chuỗi chứa JSON. Tên mùa copy từ catalog; dấu trong `2018–2019` là en dash `–`, không phải dấu trừ `-`. Trong prepared hiện tại, backend so sánh mùa theo đúng chuỗi.

Response 200 trả thông tin ảnh, diện tích và số cửa sổ; chưa thực hiện suy luận. Bạn không upload ảnh bằng form-data: ảnh Sentinel-2 đã nằm trên server.

### Bước C — Yêu cầu phân tích

Giữ nguyên JSON trên và đổi URL thành:

```http
POST http://127.0.0.1:8000/api/analyses
```

Response có dạng sau, với `id` là UUID thật do backend tạo:

```json
{
  "id": "UUID_CUA_TAC_VU",
  "cached": false
}
```

HTTP **202 Accepted** nghĩa backend đã tiếp nhận; chưa có bản đồ ngay. Không gửi POST nhiều lần để xem tiến độ vì mỗi lần tạo một job mới và chạy model mới.

Để lưu id tự động khi tự tạo request trong Postman, đặt script tại **Scripts → Post-response**:

```javascript
pm.test("API đã tiếp nhận", () => pm.response.to.have.status(202));
if (pm.response.code === 202) {
  pm.collectionVariables.set("job_id", pm.response.json().id);
}
```

### Bước D — Theo dõi tiến độ

```http
GET {{base_url}}/api/analyses/{{job_id}}
```

Body của GET để trống. Gửi lại request khi trạng thái còn `queued` hoặc `running`. Response có các trường như `status`, `progress`, `message`, `request`; khi `done` có thêm `result`.

| status | Ý nghĩa |
| --- | --- |
| queued | Tác vụ đang chờ worker |
| running | Đang chuẩn bị/chạy suy luận/xuất dữ liệu |
| done | Đã có kết quả để tra cứu hoặc tải |
| cancelled | Worker đã nhận yêu cầu hủy |
| error | Phân tích gặp lỗi; xem message |

HTTP 200 của GET trạng thái chỉ có nghĩa đã đọc được tác vụ; cần xem `status` để biết phân tích thành công hay lỗi.

### Bước E — Tra cứu và tải kết quả

Sau khi `status=done`:

```http
GET {{base_url}}/api/analyses/{{job_id}}/pixel?lat=49.303&lng=-0.361
GET {{base_url}}/api/analyses/{{job_id}}/overlay.png
GET {{base_url}}/api/analyses/{{job_id}}/download/csv
GET {{base_url}}/api/analyses/{{job_id}}/download/tif
GET {{base_url}}/api/analyses/{{job_id}}/download/geojson
GET {{base_url}}/api/analyses/{{job_id}}/download/zip?include=tif,csv,png,geojson
```

`pixel` trả JSON. PNG, TIFF, CSV và ZIP trả ảnh/file, không có cấu trúc JSON. Dùng chức năng lưu/download response của Postman để lưu các định dạng này.

### Bước F — Thử hủy

```http
DELETE {{base_url}}/api/analyses/{{job_id}}
```

Gửi trong lúc job còn chờ/chạy. DELETE chỉ bật cờ hủy, không xóa thư mục kết quả. Tiếp tục GET trạng thái để xác nhận. Nếu worker đã xuất kết quả hoặc hoàn tất, job có thể vẫn `done`.

## 4. Mã HTTP thường gặp

| Mã | Trường hợp trong dự án |
| --- | --- |
| 200 | Lấy được dữ liệu hoặc file; với GET trạng thái vẫn cần đọc status |
| 202 | Tạo tác vụ thành công và đã xếp hàng |
| 422 | JSON/Polygon sai, vùng ngoài phạm vi, mùa không có ảnh, tham số không hợp lệ |
| 404 | Không có job/pixel/file/định dạng tương ứng |
| 409 | Yêu cầu ảnh, pixel hoặc file khi job chưa done |
| 429 | Tổng tác vụ chờ/chạy trong pending đã đạt 4 |

`/api/patches/{patch_id}/tiles/...` và `/api/patches/{patch_id}/pixel` hiện chủ ý trả 404; hãy dùng `/api/analyses/{job_id}/...` sau khi Analyze hoàn tất.

## 5. Dùng OpenAPI thay vì tự nhập route

Bạn có thể import URL `http://127.0.0.1:8000/openapi.json` vào Postman để lấy cấu trúc route tự sinh. Tuy nhiên, trường `geometry` trong Pydantic hiện khai báo là `dict`, nên schema chỉ mô tả object tổng quát. Quy tắc Polygon nằm trong validator; dùng body mẫu ở trên để điền dữ liệu địa lý đúng.

Collection đi kèm bổ sung dữ liệu thật, script lưu job_id, polling và assertion cho luồng nghiệp vụ mà bản OpenAPI tự sinh chưa tự nối thành chuỗi thao tác.

## Kết quả kiểm tra bộ request

Đã chạy bằng Newman trên server Uvicorn tạm với checkpoint TSViT thật và dữ liệu local ngày 2026-10-30: **22 lượt HTTP, 46 assertion, không có lỗi kiểm tra**. Số lượt HTTP lớn hơn 17 request định nghĩa vì bước GET trạng thái được lặp. Vùng mẫu có 321 pixel, tương đương 3,21 ha, đi qua hai cửa sổ suy luận. Thử DELETE trong lượt chạy này áp dụng cho job đã done và kiểm tra phản hồi yêu cầu hủy; chưa phải một phép đo bảo đảm hủy được trong lúc model đang chạy. Chi tiết tổng hợp nằm trong `kiem-tra.json`.

Server tạm đã được dừng và thư mục kết quả test đã được xóa sau khi kiểm tra. Khi import collection để dùng, hãy tự khởi động backend ở địa chỉ `base_url` đã chọn.

## Tham chiếu

- Mã dự án: `app.py`, `inference.py`, `web/app.js`.
- [Postman: viết script trước/sau request](https://learning.postman.com/docs/tests-and-scripts/write-scripts/intro-to-scripts/).
- [Postman: Collection Variables](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-variables).
- [Postman: setNextRequest và phạm vi áp dụng](https://learning.postman.com/docs/tests-and-scripts/write-scripts/postman-sandbox-reference/pm-execution).
