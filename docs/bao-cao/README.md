# Architecture diagrams

Retained material: editable Mermaid/PlantUML sources and configuration in `nguon/`, figure metadata in `danh-muc-hinh.json`, and twelve SVG diagrams in `hinh/svg/`. These describe the prepared CPU application; they do not establish any current cloud deployment status.

Representative diagrams:

- [System architecture](hinh/svg/02-kien-truc-he-thong.svg)
- [Inference pipeline](hinh/svg/07-pipeline-suy-luan.svg)
- [TSViT architecture](hinh/svg/08-kien-truc-tsvit.svg)
- [Docker deployment](hinh/svg/10-trien-khai-docker.svg)

PDF, DOCX, PNG, ZIP, generated HTML and execution evidence are intentionally omitted. Original exports remain in the original project. Publish future verified exports as release assets rather than duplicating every generated format in Git.

Optional local rendering uses `xuat-hinh.mjs` (Mermaid/PlantUML/Chrome) and `dong-goi.py` (python-docx/pypdf/Pillow). These dependencies are separate from application requirements. Configure REPORT_TOOLS_DIR, REPORT_CHROME and the Puppeteer configuration as appropriate. Tool installation/rendering were not performed during migration.

Generators overwrite local documentation/output files, including README; review resulting diffs before committing. Generated export links are only valid after rendering locally. Source references in the diagram metadata correspond to the original application line numbers.
