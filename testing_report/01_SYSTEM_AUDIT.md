# 01 — System Audit: Satellite Crop Mapping

Audit dựa trên mã nguồn tại commit `8ede7cf` (branch `loanhviet/ai-system-testing-report`) và các phép gọi chỉ đọc tới production ngày 2026-11-14.

## 1. Kiến trúc thực tế
- Một tiến trình FastAPI (`app.py`) phục vụ cả API lẫn frontend tĩnh (`web/`, Leaflet; không có bước build frontend).
- Hàng đợi job nằm trong bộ nhớ: `ThreadPoolExecutor(max_workers=1)`, tối đa 4 job chờ (vượt thì trả 429). Bắt buộc chạy 1 worker Uvicorn.
- Không có database. Mỗi job ghi vào `RESULTS/<uuid>/`: `request.json`, `status.json`, `classification.tif/png/geojson`, `overlay.png`, `summary.csv`, `result.json`, `confidence.npy`.
- Khi khởi động, các job đang `queued/running` được đánh dấu `error` ("interrupted by a server restart"). Hệ quả: hai tiến trình dùng chung một thư mục RESULTS sẽ làm hỏng job của nhau (gặp trong quá trình kiểm thử song song; đã cô lập RESULTS theo từng tiến trình test).
- Nguồn ảnh: `CROP_SOURCE` ∈ {prepared, pastis, geodes}. Production chạy `prepared` (offline).

## 2. API endpoints
| Method | Path | Ghi chú |
|---|---|---|
| GET | /api/health | status, model, device, checkpoint_sha256, available_patches, source_mode, imagery |
| GET | /api/catalog | 19 lớp, mùa (2018–2019), vùng có ảnh (8 patch test + vùng Normandy 900010) |
| POST | /api/imagery-plan | Kiểm tra AOI và lập kế hoạch; **không tạo job**; 422 / 502 |
| POST | /api/analyses | 202 + id; 422 khi input sai; 429 khi hàng đợi đầy; 503 khi chế độ geodes thiếu khóa |
| GET / DELETE | /api/analyses/{id} | Theo dõi / hủy; id phải là UUID chuẩn (nếu không trả 404) |
| GET | /api/analyses/{id}/overlay.png, preview.png, pixel, download/{tif,csv,png,geojson,zip} | Job chưa xong trả 409 |
| GET | /api/patches/{id}/preview, preview-bounds, tiles, pixel | tiles/pixel luôn trả 404 (legacy) |

## 3. Mô hình, dữ liệu, pipeline
- TSViT (`model.py`): dim 128, 4 head, temporal/spatial depth 4, patch 2, đầu vào [60, 24, 24, 11], 19 lớp.
- `Engine`: kiểm tra `assets/model-manifest.json` (SHA-256 + config), `torch.load(weights_only=True)`, `strict=True`; nếu cấu hình sai thì từ chối khởi động.
- `preprocess`: kiểm tra shape [T,10,24,24], giá trị hữu hạn, DOY trong 1..365; chuẩn hóa MEAN/STD; cắt hoặc pad về 60 mốc. **Không** kiểm tra T = 0 hay dải giá trị phản xạ.
- Dữ liệu local: `S2_<id>.npy` (T×10×128×128 int16; dùng 120×120 góc trên-trái), `TARGET_10003/10000.npy` (ground truth PASTIS), `data/cog/` (Normandy 2304×2304, 9 khối).
- Hậu xử lý: `export_result` sinh GeoTIFF uint8 (nodata 255, colormap, tag checkpoint), PNG, overlay EPSG:3857, GeoJSON vector hóa (streaming), CSV diện tích.

## 4. Input validation và error handling
- `validate_polygon`: Polygon, 1 ring, 4–100 điểm, hữu hạn, |lon| ≤ 180, |lat| ≤ 90, ring khép kín. **Không** kiểm tra topology (tự cắt).
- `selection_mask`: polygon phải nằm trong vùng có ảnh và chứa ít nhất 1 tâm pixel.
- Model Pydantic ở chế độ mặc định (lax): ép kiểu chuỗi hoặc float sang int, bỏ qua trường thừa.
- Không có giới hạn kích thước body ở ứng dụng. File Caddy mẫu đặt `max_size 1MB`, nhưng cấu hình thật trên production chưa được xác minh.
- `run_analysis`: `ImageryError` trả về thông báo cụ thể; exception khác trả thông báo chung và ghi log stack; dọn `imagery.npy`.

## 5. Bảo mật
- Không có xác thực hay phân quyền; job được định danh bằng UUIDv4 (không đoán được).
- Chống path traversal ở job_id (UUID chuẩn) và `PreparedProvider.data_path` (phải nằm trong thư mục data).
- Checkpoint được xác minh toàn vẹn trước khi deserialize.
- Production: Caddy → uvicorn; không thấy header HSTS hay X-Content-Type-Options trong 1 lần HEAD.

## 6. Test suite có sẵn, CI/CD, deployment
- 53 test pytest (`tests/`), có gate asset ngoài trong `conftest.py`. Chạy với asset thật: **53 passed**.
- CI: pytest `-m 'not external_assets'`, kiểm tra Compose và Dockerfile. CD: build ARM64 → GHCR → SSH deploy tới Oracle A1, có health check và rollback.
- Compose: mặc định 2 CPU, giới hạn 2 GiB RAM; weights mount chỉ đọc.

## 7. Thành phần có thể mock
`app.state.engine.predict`, `app.state.provider.window`, `app.state.imagery.{plan,prepare,status}`, `httpx.Client` bên trong `imagery.py` (qua `MockTransport`), `inference.WEIGHTS` (checkpoint giả mạo).

## 8. Giới hạn ảnh hưởng tới kiểm thử
- Ground truth chỉ có cho patch 10003 (test) và 10000 (training).
- Vùng Normandy không có nhãn.
- Production chỉ cho phép kiểm thử nhẹ, không phá hoại (xem `02_TEST_PLAN.md`).

## 9. Production (đo ngày 2026-11-14)
- `/api/health` trả 200, `source_mode=prepared`, `device=cpu`, checkpoint `92a83d0d…a40b733`, giống local.
- Catalog production giống hệt local (cùng 9 vùng, cùng dataset_version).
