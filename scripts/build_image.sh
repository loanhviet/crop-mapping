#!/bin/sh
# Build a local, commit-tagged single-platform image. Never publishes.
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_ROOT"
ARCH=${1:-amd64}
case "$ARCH" in
  amd64) ;;
  *) echo 'Usage: scripts/build_image.sh [amd64]' >&2; exit 2 ;;
esac
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  echo 'Refusing a commit-derived tag for a dirty working tree. Review and commit changes first.' >&2
  exit 1
fi
REVISION=$(git rev-parse HEAD)
VERSION=sha-$(git rev-parse --short=12 HEAD)
REPOSITORY=${IMAGE_REPOSITORY:-loanhviet070105/crop-mapping}
BUILDER=${BUILDX_BUILDER:-default}
mkdir -p .validation/phase2
exec docker buildx build --builder "$BUILDER" --platform "linux/$ARCH" \
  --build-arg "VCS_REF=$REVISION" --build-arg "IMAGE_VERSION=$VERSION" \
  --tag "$REPOSITORY:$VERSION-$ARCH" \
  --metadata-file ".validation/phase2/build-$VERSION-$ARCH.json" \
  --load --progress plain .
