"""Generate an importable Postman v2.1 collection for the prepared-image workflow."""
from pathlib import Path
import json
import uuid

HERE = Path(__file__).resolve().parent
SAMPLE = {
    'patch_id': 10003,
    'season': '2018–2019',
    'geometry': {'type': 'Polygon', 'coordinates': [[
        [-0.362, 49.304], [-0.360, 49.304], [-0.360, 49.302],
        [-0.362, 49.302], [-0.362, 49.304],
    ]]},
}
BODY = '{\n  "patch_id": {{patch_id}},\n  "season": "{{season}}",\n  "geometry": {{geometry}}\n}'


def request(name, method, endpoint, description, script, body=None):
    req = {'method': method, 'header': [], 'url': '{{base_url}}' + endpoint, 'description': description}
    if body is not None:
        req['header'] = [{'key': 'Content-Type', 'value': 'application/json'}]
        req['body'] = {'mode': 'raw', 'raw': body, 'options': {'raw': {'language': 'json'}}}
    return {
        'id': str(uuid.uuid5(uuid.NAMESPACE_URL, 'crop-map-postman:' + name)),
        'name': name, 'request': req,
        'event': [{'listen': 'test', 'script': {'type': 'text/javascript', 'exec': script.strip().splitlines()}}],
    }


def expect(code):
    return f'pm.test("HTTP {code}", () => pm.response.to.have.status({code}));'


happy = [
    request('01 - Kiểm tra server', 'GET', '/api/health',
            'Chạy sau khi khởi động ./run.sh hoặc docker compose up. Luồng mẫu yêu cầu source_mode=prepared/pastis.',
            expect(200) + '''
if (pm.response.code !== 200) { pm.execution.setNextRequest(null); }
else {
  const body = pm.response.json();
  pm.test("Model TSViT sẵn sàng", () => pm.expect(body.model).to.eql("TSViT"));
  pm.test("Nguồn ảnh local", () => pm.expect(body.source_mode).to.be.oneOf(["prepared", "pastis"]));
  if (!["prepared", "pastis"].includes(body.source_mode)) pm.execution.setNextRequest(null);
}
'''),
    request('02 - Lấy catalog và chọn vùng mẫu', 'GET', '/api/catalog',
            'Tự lưu patch_id, season, geometry và tọa độ pixel vào Collection Variables. Ưu tiên patch 10003; fallback chỉ chọn một patch test nhỏ.',
            expect(200) + '''
const catalog = pm.response.json();
pm.test("Có 19 lớp", () => pm.expect(catalog.classes).to.have.lengthOf(19));
const patches = catalog.patches || [];
const patch = patches.find(p => p.id === 10003) || patches.find(p => p.split === "test" && p.shape && p.shape[0] <= 120 && p.shape[1] <= 120);
if (!patch) {
  pm.execution.setNextRequest(null);
  throw new Error("Không có patch test nhỏ. Chọn một vùng có ảnh và cập nhật Collection Variables trước khi chạy mẫu.");
}
let geometry;
if (patch.id === 10003) {
  geometry = {type:"Polygon",coordinates:[[[-0.362,49.304],[-0.360,49.304],[-0.360,49.302],[-0.362,49.302],[-0.362,49.304]]]};
} else {
  const points = patch.geometry.coordinates[0].slice(0, -1);
  const center = points.reduce((sum,p) => [sum[0]+p[0]/points.length,sum[1]+p[1]/points.length], [0,0]);
  const ring = points.map(p => [center[0]+(p[0]-center[0])*0.1,center[1]+(p[1]-center[1])*0.1]);
  ring.push([...ring[0]]);
  geometry = {type:"Polygon",coordinates:[ring]};
}
const points = geometry.coordinates[0].slice(0,-1);
const center = points.reduce((sum,p) => [sum[0]+p[0]/points.length,sum[1]+p[1]/points.length], [0,0]);
pm.collectionVariables.set("patch_id", patch.id);
pm.collectionVariables.set("season", patch.season || catalog.seasons[0]);
pm.collectionVariables.set("geometry", JSON.stringify(geometry));
pm.collectionVariables.set("lng", center[0]);
pm.collectionVariables.set("lat", center[1]);
console.log("Vùng test:", patch.name, geometry);
'''),
    request('03 - Kiểm tra kế hoạch ảnh', 'POST', '/api/imagery-plan',
            'Body raw JSON. Bước này kiểm tra ảnh và diện tích; chưa chạy model.',
            expect(200) + '''
if (pm.response.code !== 200) { pm.execution.setNextRequest(null); }
else {
  const plan = pm.response.json();
  pm.test("Có diện tích ảnh hợp lệ", () => pm.expect(plan.valid_area_ha).to.be.above(0));
  pm.test("Ảnh đã có trên server", () => pm.expect(plan.estimated_download_gb).to.eql(0));
  pm.test("Không dùng prediction lưu sẵn", () => pm.expect(plan.prediction_ready).to.eql(false));
  console.log("Kế hoạch:", plan);
}
''', BODY),
    request('04 - Tạo tác vụ phân tích', 'POST', '/api/analyses',
            'Mỗi lần Send tạo một job mới và chạy model mới. Response 202 là đã tiếp nhận, chưa có kết quả cuối. Script lưu body.id thành biến job_id.',
            expect(202) + '''
if (pm.response.code !== 202) { pm.execution.setNextRequest(null); }
else {
  const body = pm.response.json();
  pm.test("Có UUID tác vụ", () => pm.expect(body.id).to.match(/^[0-9a-f-]{36}$/));
  pm.test("Suy luận mới", () => pm.expect(body.cached).to.eql(false));
  pm.collectionVariables.set("job_id", body.id);
  pm.collectionVariables.set("poll_count", 0);
  console.log("job_id:", body.id);
}
''', BODY),
    request('05 - Theo dõi đến khi hoàn thành', 'GET', '/api/analyses/{{job_id}}',
            'Bấm Send nhiều lần khi test thủ công. Collection Runner tự lặp request này; đặt Delay 400 ms khi chạy. Hết max_polls thì dừng và báo lỗi, không tự hủy job.',
            expect(200) + '''
if (pm.response.code !== 200) { pm.execution.setNextRequest(null); }
else {
  const body = pm.response.json();
  const count = Number(pm.collectionVariables.get("poll_count") || 0) + 1;
  const limit = Number(pm.variables.get("max_polls") || 120);
  pm.collectionVariables.set("poll_count", count);
  pm.collectionVariables.set("job_status", body.status);
  pm.test("Trạng thái hợp lệ", () => pm.expect(body.status).to.be.oneOf(["queued","running","done","cancelled","error"]));
  console.log(body.status, body.progress, body.message);
  if (["queued","running"].includes(body.status)) {
    if (count >= limit) {
      pm.test("Hoàn thành trong số lần poll cho phép", () => pm.expect.fail("Tăng max_polls hoặc tiếp tục GET thủ công. Job chưa bị hủy."));
      pm.execution.setNextRequest(null);
    } else pm.execution.setNextRequest(pm.info.requestId);
  } else if (body.status === "done") {
    pm.test("Hoàn thành 100%", () => pm.expect(body.progress).to.eql(100));
    pm.test("Có thống kê pixel", () => pm.expect(body.result.pixels).to.be.above(0));
    pm.test("Tổng số pixel các lớp khớp", () => pm.expect(body.result.classes.reduce((n,c) => n+c.pixels,0)).to.eql(body.result.pixels));
    pm.collectionVariables.set("result_json", JSON.stringify(body.result));
  } else {
    pm.test("Tác vụ hoàn thành thành công", () => pm.expect.fail(body.message || body.status));
    pm.execution.setNextRequest(null);
  }
}
'''),
    request('06 - Tra cứu pixel', 'GET', '/api/analyses/{{job_id}}/pixel?lat={{lat}}&lng={{lng}}',
            'Chỉ dùng khi status=done. lat/lng là query parameters; API trả JSON tên lớp, màu và confidence.',
            expect(200) + '''
if (pm.response.code === 200) {
  const pixel = pm.response.json();
  pm.test("Lớp trong 0–18", () => pm.expect(pixel.id).to.be.within(0,18));
  pm.test("Confidence trong 0–1", () => pm.expect(pixel.confidence).to.be.within(0,1));
}
'''),
    request('07 - Xem lớp phủ PNG', 'GET', '/api/analyses/{{job_id}}/overlay.png',
            'Response là ảnh PNG, không phải JSON.', expect(200) + '\npm.test("PNG", () => pm.expect(pm.response.headers.get("Content-Type")).to.include("image/png"));'),
    request('08 - Tải thống kê CSV', 'GET', '/api/analyses/{{job_id}}/download/csv',
            'Response là CSV. Để lưu file, dùng chức năng Download của Postman.',
            expect(200) + '\npm.test("Có cột diện tích", () => pm.expect(pm.response.text()).to.include("area_ha"));'),
    request('09 - Tải ZIP', 'GET', '/api/analyses/{{job_id}}/download/zip?include=tif,csv,png,geojson',
            'ZIP gồm các định dạng được chọn và result.json. Response là binary, không phải JSON.',
            expect(200) + '\npm.test("ZIP", () => pm.expect(pm.response.headers.get("Content-Type")).to.include("application/zip"));'),
    request('10 - Xem đặc tả OpenAPI', 'GET', '/openapi.json',
            'Đặc tả tự sinh bởi FastAPI; có thể import URL này vào Postman. Swagger UI nằm tại /docs.',
            expect(200) + '\npm.test("Có route phân tích", () => pm.expect(pm.response.json().paths).to.have.property("/api/analyses"));'),
]

negative = [
    request('E01 - Thiếu geometry', 'POST', '/api/analyses', 'Dự kiến 422; không tạo job.', expect(422), '{"patch_id": {{patch_id}}, "season": "{{season}}"}'),
    request('E02 - Mùa chưa có ảnh local', 'POST', '/api/analyses', 'Prepared hiện chỉ có mùa 2018–2019; dự kiến 422.', expect(422), BODY.replace('{{season}}','2098–2099')),
    request('E03 - Polygon không đóng', 'POST', '/api/imagery-plan', 'Điểm đầu khác điểm cuối; dự kiến 422.', expect(422), '{"patch_id": {{patch_id}}, "season": "{{season}}", "geometry": {"type":"Polygon", "coordinates":[[[-0.362,49.304],[-0.360,49.304],[-0.360,49.302],[-0.362,49.302]]]}}'),
    request('E04 - Job không tồn tại', 'GET', '/api/analyses/00000000-0000-4000-8000-000000000000', 'UUID đúng cấu trúc nhưng không có tác vụ; dự kiến 404.', expect(404)),
    request('E05 - Tọa độ ngoài vùng', 'GET', '/api/analyses/{{job_id}}/pixel?lat=0&lng=0', 'Chạy sau job done; dự kiến 404.', expect(404)),
    request('E06 - Định dạng ZIP không hợp lệ', 'GET', '/api/analyses/{{job_id}}/download/zip?include=unknown', 'Chạy sau job done; dự kiến 422.', expect(422)),
]
cancel = request('C01 - Yêu cầu hủy job hiện tại', 'DELETE', '/api/analyses/{{job_id}}',
                 'Gửi ngay sau request 04 nếu muốn thử hủy. DELETE chỉ bật Event, không xóa dữ liệu. Sau đó GET trạng thái để biết cancelled/done. Nếu chạy sau happy path đã done thì cancellation_requested=false là hợp lệ.',
                 expect(200) + '\npm.test("Có kết quả yêu cầu hủy", () => pm.expect(pm.response.json().cancellation_requested).to.be.a("boolean"));')

collection = {
    'info': {'_postman_id': str(uuid.uuid5(uuid.NAMESPACE_URL,'crop-map-postman-v1')),
             'name': 'Crop Map - API prepared',
             'description': 'Luồng thật theo app.py. Chạy folder 01 trước; Delay 400 ms trong Collection Runner. Không cần Authorization. Mỗi POST analyses thực hiện suy luận mới trên vùng nhỏ. Folder 02 kiểm tra lỗi và folder 03 thử hủy thủ công.',
             'schema': 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json'},
    'auth': {'type': 'noauth'},
    'variable': [{'key':k,'value':v,'type':'string'} for k,v in {
        'base_url':'http://127.0.0.1:8000', 'patch_id':'10003', 'season':SAMPLE['season'],
        'geometry':json.dumps(SAMPLE['geometry'],ensure_ascii=False), 'lat':'49.303', 'lng':'-0.361',
        'job_id':'', 'job_status':'', 'poll_count':'0', 'max_polls':'120',
    }.items()],
    'item': [
        {'name':'01 - Luồng phân tích thành công', 'item':happy},
        {'name':'02 - Kiểm tra lỗi đầu vào', 'item':negative},
        {'name':'03 - Hủy tác vụ (gửi thủ công)', 'item':[cancel]},
    ],
}
(HERE/'Crop-Map.postman_collection.json').write_text(json.dumps(collection,ensure_ascii=False,indent=2)+'\n')
(HERE/'request-mau.json').write_text(json.dumps(SAMPLE,ensure_ascii=False,indent=2)+'\n')
print('Generated collection: 17 requests, including 10 happy-path requests.')
