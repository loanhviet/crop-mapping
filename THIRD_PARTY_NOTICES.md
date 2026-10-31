# Third-party notices and publication gate

The application image contains TSViT architecture code adapted from
https://github.com/loanhviet/tsvit-crop-segmentation and the original DeepSatModels
implementation. The retained architecture is modified for inference; the source
header records this adaptation. Its Apache-2.0 license is included at
`/app/licenses/TSViT-APACHE-2.0.txt`.

Leaflet is distributed under BSD-2-Clause with copyright/license retained in
`/app/web/assets/LEAFLET-LICENSE.txt`. Carlito fonts retain their OFL-1.1 notice
in `/app/web/assets/CARLITO-LICENSE.txt`. These assets and notices are unchanged.

Python dependencies retain their distribution metadata/license files in
site-packages. The base image and Debian packages retain their own notices.
See `requirements/locks/` for the exact Python distributions. A dependency
license inventory is recorded with local validation evidence; it is not a
substitute for owner review of distribution rights.

No checkpoint, satellite imagery, ground truth, credentials or private .env is
included in the image. Public redistribution of the application code/UI still
requires confirmation by the repository owner: no project-wide license has been
selected. Existing third-party licenses do not grant rights to unrelated code.
Do not push publicly until ownership, notices, dependency terms and the first
public-push approval have been reviewed. No public push is authorized by this
notice.
