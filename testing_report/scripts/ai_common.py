"""Model-level helpers for AI tests: real checkpoint, real PASTIS windows, real ground truth."""
import scripts.common as c  # noqa: F401  (sets env before inference import)
import numpy as np

from inference import CLASS_NAMES, Engine, PastisProvider

VOID = 19  # PASTIS semantic label for void/unknown pixels; excluded from metrics.
WINDOWS = [(r, col) for r in range(0, 120, 24) for col in range(0, 120, 24)]
_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = Engine()
    return _engine


def provider():
    return PastisProvider()


def ground_truth(patch_id=10003):
    """Semantic channel of the official PASTIS TARGET, cropped exactly like prepare_data (top-left 120x120)."""
    target = np.load(c.ASSETS / 'data' / f'TARGET_{patch_id}.npy', allow_pickle=False)
    return target[0, :120, :120].astype(np.int64)


def predict_patch(patch_id=10003, transform=None, prov=None):
    """Run the real model on all 25 windows. transform(image[T,10,24,24], doy[T]) -> (image, doy)."""
    prov = prov or provider()
    labels = np.zeros((120, 120), np.uint8)
    conf = np.zeros((120, 120), np.float32)
    for r, col in WINDOWS:
        image = np.asarray(prov.window(patch_id, r, col), dtype=np.float32)
        doy = np.asarray(prov.window_doy(patch_id, r, col), dtype=np.float32)
        if transform is not None:
            image, doy = transform(image, doy)
        labels[r:r+24, col:col+24], conf[r:r+24, col:col+24] = engine().predict(image, doy)
    return labels, conf


def metrics(pred, gt):
    valid = gt != VOID
    p, g = pred[valid].astype(np.int64), gt[valid]
    k = len(CLASS_NAMES)
    cm = np.bincount(g * k + p, minlength=k * k).reshape(k, k)
    tp = np.diag(cm).astype(float)
    fp, fn = cm.sum(0) - tp, cm.sum(1) - tp
    present = (cm.sum(1) + cm.sum(0)) > 0
    iou = np.divide(tp, tp + fp + fn, out=np.zeros(k), where=(tp + fp + fn) > 0)
    f1 = np.divide(2 * tp, 2 * tp + fp + fn, out=np.zeros(k), where=(2 * tp + fp + fn) > 0)
    gt_classes = cm.sum(1) > 0
    return dict(overall_accuracy=round(float(tp.sum() / cm.sum()), 4),
                miou=round(float(iou[present].mean()), 4),
                macro_f1=round(float(f1[present].mean()), 4),
                miou_gt_classes=round(float(iou[gt_classes].mean()), 4),
                evaluated_pixels=int(cm.sum()), void_pixels=int((~valid).sum()),
                per_class={CLASS_NAMES[i]: dict(iou=round(float(iou[i]), 4), f1=round(float(f1[i]), 4),
                                                gt_pixels=int(cm.sum(1)[i]), pred_pixels=int(cm.sum(0)[i]))
                           for i in range(k) if present[i]},
                confusion_matrix=cm.tolist())


def rgb(patch_id=10003):
    """True-colour image of the least cloudy real frame (lowest mean blue band)."""
    image = provider().image(patch_id)
    frame = int(np.argmin([image[t, 0, :120, :120].mean() for t in range(len(image))]))
    data = np.asarray(image[frame, [2, 1, 0], :120, :120], float).transpose(1, 2, 0)
    return np.clip(data / 2500, 0, 1), frame


def palette():
    from inference import COLORS
    rgb = [tuple(int(h[i:i+2], 16) / 255 for i in (1, 3, 5)) for h in COLORS]
    return rgb + [(1, 1, 1)]  # index 19 = void shown white


def label_image(ax, labels, title):
    from matplotlib.colors import ListedColormap
    ax.imshow(labels, cmap=ListedColormap(palette()), vmin=0, vmax=19, interpolation='nearest')
    ax.set_title(title, fontsize=9)
    ax.axis('off')
