> Interactive inference update: use `package_deploy.py --live`. The server requires real
> time-series cubes, starts without classification overlays, and runs TSViT for each
> Analyze request (including repeated selections). Saved predictions are not used.
> The previous 48 MiB predictions-only bundle cannot serve this workflow.
> Whole region selects the full prepared footprint; it still requires Analyze and
> can take longer on CPU. Pixel popups display only the class color and name.

# Chạy Crop Map trên Docker và EC2

Bản này giữ giao diện Figma, dùng Sentinel-2 COG/PASTIS chuẩn bị trước và checkpoint
TSViT thật. Trình duyệt cần Internet để tải nền Esri; phân tích không cần gọi
Drive, Kaggle hoặc GEODES. Chưa tạo instance hoặc đưa ứng dụng lên AWS.

## 1. Kiểm tra trên máy trước

```bash
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/api/health
```

Mở http://127.0.0.1:8000. Chọn vùng ở góc dưới bên trái bản đồ, Analyze, thử
tra pixel và xuất ZIP. `healthy` xác nhận model và catalog nạp thành công;
không thay thế kiểm tra chất lượng mô hình.

Compose mặc định chỉ mở localhost. `data/` và `weights/` là bind mounts
read-only; `results` là named volume writable. Một worker nạp model một lần,
giới hạn 2 CPU, 2 GiB RAM và bốn job chờ/chạy; container chạy user không có
quyền root. Không có tài khoản đăng nhập trong bản demo này.

## 2. Tạo gói deploy

```bash
.venv/bin/python package_deploy.py --live
```

Gói gồm chuỗi ảnh Sentinel-2 thật (khoảng 8,3 GB chưa nén) cho vùng
23,04 × 23,04 km, checkpoint, code và mask. Không chứa kết quả phân loại
đã tính sẵn, token, .env, nhãn ground truth, dữ liệu task 2 hoặc DINOv3.
Mỗi lần Analyze chạy TSViT trên từng cửa sổ 24×24 thuộc vùng chọn;
Whole region chỉ chọn cả vùng, chưa chạy cho đến khi bấm Analyze.
Có progress và Cancel. Ảnh vệ tinh đã chuẩn bị sẵn nên không gọi Drive/GEODES.
Gói prediction-only cũ không tương thích với chế độ tương tác này.

## 3. Chuẩn bị EC2

Dùng Ubuntu 24.04 LTS **x86_64/amd64**, bắt đầu với 2 vCPU, 4 GiB RAM,
ổ gp3 khoảng 30 GiB. Không cần GPU. Đây là cấu hình khởi điểm cho demo ít
người, chưa phải cam kết hiệu năng dưới tải lớn.
Gói live cần khoảng 8 GiB cho ảnh giải nén, thêm archive và Docker image.
Kiểm tra dung lượng trống trước khi giải nén; nên còn ít nhất 15 GiB.

Trong Security Group:

- TCP 22: chỉ IP của bạn để SSH.
- TCP 80: IP người xem demo; nếu cần link công khai thì mở nguồn tương ứng.

Không ghi AWS key hoặc SSH private key vào repo/gói deploy.

## 4. Chuyển gói lên máy chủ

Trên máy local, thay tên gói, đường dẫn key và địa chỉ thật:

```bash
scp -i /path/to/key.pem deployment/bundles/crop-map-demo-YYYYMMDD-HHMMSS.tar.gz ubuntu@EC2_IP:~/
scp -i /path/to/key.pem deployment/bundles/crop-map-demo-YYYYMMDD-HHMMSS.tar.gz.sha256 ubuntu@EC2_IP:~/
ssh -i /path/to/key.pem ubuntu@EC2_IP
```

Trên EC2:

```bash
sha256sum -c crop-map-demo-YYYYMMDD-HHMMSS.tar.gz.sha256
tar -xzf crop-map-demo-YYYYMMDD-HHMMSS.tar.gz
cd crop-map
```

## 5. Cài Docker trên Ubuntu mới

Nếu máy đã có Docker và plugin Compose, bỏ qua bước này. Theo
[hướng dẫn Docker chính thức](https://docs.docker.com/engine/install/ubuntu/):

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

```bash
sudo tee /etc/apt/sources.list.d/docker.sources > /dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

## 6. Chạy web

Tạo `.env` mới trên EC2 (gói không chứa `.env` của máy cá nhân):

```bash
cp .env.example .env
```

Sửa ba dòng:

```dotenv
CROP_BIND=0.0.0.0
CROP_PORT=80
CROP_THREADS=2
```

```bash
sudo docker compose up -d --build
sudo docker compose ps
curl --fail http://127.0.0.1/api/health
sudo docker compose logs --tail=80 crop-map
```

Mở **http://EC2_IP** từ trình duyệt, kiểm tra dự đoán và download. Khi cần
domain/HTTPS, đặt reverse proxy trước app; hướng dẫn hiện tại là bản demo
HTTP theo IP, chưa cấu hình TLS hay xác thực.

Nếu không truy cập được: kiểm tra public IPv4, Security Group TCP 80,
`CROP_BIND`, `CROP_PORT`, `docker compose ps` và log. Không mở thêm cổng 8000
ra Internet khi đã publish cổng 80 theo cấu hình trên.

## 7. Vận hành và cập nhật

```bash
sudo docker compose logs -f --tail=80 crop-map
sudo docker stats --no-stream
sudo docker compose up -d --build
sudo docker compose stop
sudo docker compose start
```

Khi cập nhật code, giữ nguyên thư mục dự án và named volume. Kết quả đã hoàn
thành có thể khôi phục sau restart; job đang chạy sẽ được đánh dấu gián đoạn.
Không dùng `down -v` nếu còn cần kết quả, vì tùy chọn đó xóa named volume.

Sao lưu kết quả của container đang chạy ra thư mục mới:

```bash
sudo docker compose cp crop-map:/app/results ./results-backup
```

Dừng EC2 khi không dùng. Chỉ terminate khi đã giữ đủ dữ liệu cần thiết.

## Nguồn triển khai

- [Bind mounts và read-only](https://docs.docker.com/engine/storage/bind-mounts/).
- [Biến cấu hình Compose](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/).
- [Quy tắc Security Group EC2](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/security-group-rules-reference.html).
- [Dữ liệu PASTIS, CC BY 4.0](https://zenodo.org/records/5012942).
