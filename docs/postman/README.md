# Postman API checks

Start the prepared application after [provisioning assets](../ASSETS.md). Import `Crop-Map.postman_collection.json`, set `base_url` and run folder **01 - Luồng phân tích thành công**, followed by **02 - Kiểm tra lỗi đầu vào**. Delay requests by 400 ms. Folder 03 is a manual cooperative-cancellation check.

The collection has no authentication because the application has no login. It selects PASTIS patch 10003 (or another small test patch), stores request geometry/job id and polls until done or its limit. It does not work unchanged against a live-only COG bundle with no small PASTIS test patch; that needs an explicit external-region smoke profile.

Request body example: [request-mau.json](request-mau.json). Coordinates are [longitude, latitude], the polygon must be closed and inside coverage, and the prepared season must match the catalog exactly (`2018–2019`). POST analyses returns 202 before completion. Poll the returned id; HTTP 200 for status does not itself mean inference succeeded.

After done, verify pixel lookup, overlay and exports. Formats: tif/csv/png/geojson/zip. 422/404 negative cases in folder 02 are expected assertions. DELETE requests cancellation and does not delete outputs. Prepared classification tile/pixel routes intentionally return 404.

OpenAPI is available at /openapi.json and Swagger at /docs. The collection generator is retained for reproducibility; regeneration overwrites the collection/request example. No Newman or live API run was performed during migration.
