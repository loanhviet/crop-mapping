"""TC05 — Model Prediction Quality: real checkpoint vs official PASTIS ground truth."""
import scripts.common as c
import scripts.ai_common as ai
import numpy as np
import matplotlib.pyplot as plt

from inference import CLASS_NAMES

ev = c.Evidence('TC05', 'Model Prediction Quality', 'AI Test', 'Local')
THRESHOLD_OA, THRESHOLD_MIOU = 0.70, 0.40  # fixed before running (see 02_TEST_PLAN.md)
results = {}
for pid, role in [(10003, 'test (Fold 5, held-out)'), (10000, 'training (Fold 1, NOT held-out)')]:
    gt = ai.ground_truth(pid)
    pred, conf = ai.predict_patch(pid)
    m = ai.metrics(pred, gt)
    m['mean_confidence'] = round(float(conf.mean()), 4)
    results[pid] = dict(role=role, **m)
    ev.log(f'patch {pid} [{role}]: OA={m["overall_accuracy"]} mIoU={m["miou"]} macroF1={m["macro_f1"]} '
           f'pixels={m["evaluated_pixels"]} void={m["void_pixels"]} meanConf={m["mean_confidence"]}')
    np.save(ev.dir / f'pred_{pid}.npy', pred)
    fig, axes = plt.subplots(1, 4, figsize=(15, 4))
    rgb, frame = ai.rgb(pid)
    axes[0].imshow(rgb); axes[0].set_title(f'Sentinel-2 RGB (patch {pid}, frame {frame})', fontsize=9); axes[0].axis('off')
    ai.label_image(axes[1], gt, 'Ground truth PASTIS (trắng = void)')
    ai.label_image(axes[2], pred, f'Dự đoán TSViT · OA={m["overall_accuracy"]:.3f}')
    err = np.where(gt == ai.VOID, 0.5, (pred != gt).astype(float))
    axes[3].imshow(err, cmap='RdYlGn_r', vmin=0, vmax=1); axes[3].set_title('Sai lệch (đỏ = sai, vàng = void)', fontsize=9); axes[3].axis('off')
    fig.suptitle(f'TC05 · patch {pid} · {role} · dữ liệu thực, checkpoint thực', fontsize=10)
    fig.tight_layout(); fig.savefig(ev.dir / f'gt_vs_pred_{pid}.png', dpi=110); plt.close(fig)

# Confusion matrix (held-out patch, classes present only)
cm = np.array(results[10003]['confusion_matrix'])
idx = [i for i in range(len(CLASS_NAMES)) if cm[i].sum() + cm[:, i].sum() > 0]
sub = cm[np.ix_(idx, idx)]
norm = sub / np.maximum(sub.sum(1, keepdims=True), 1)
fig, ax = plt.subplots(figsize=(8, 7))
ax.imshow(norm, cmap='Blues', vmin=0, vmax=1)
names = [CLASS_NAMES[i] for i in idx]
ax.set_xticks(range(len(idx)), names, rotation=60, ha='right', fontsize=8); ax.set_yticks(range(len(idx)), names, fontsize=8)
for (i, j), v in np.ndenumerate(sub):
    if v:
        ax.text(j, i, v, ha='center', va='center', fontsize=7, color='white' if norm[i, j] > .5 else 'black')
ax.set_xlabel('Dự đoán'); ax.set_ylabel('Ground truth')
ax.set_title('TC05 · Confusion matrix patch 10003 (số pixel, màu = tỉ lệ theo hàng)', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'confusion_matrix_10003.png', dpi=110); plt.close(fig)

# Per-class IoU chart
pc = results[10003]['per_class']
fig, ax = plt.subplots(figsize=(9, 4))
ax.barh(list(pc), [v['iou'] for v in pc.values()], color='#4a7fb5')
for i, v in enumerate(pc.values()):
    ax.text(v['iou'] + .01, i, f"{v['iou']:.2f} (GT {v['gt_pixels']} px)", va='center', fontsize=8)
ax.set_xlim(0, 1.15); ax.set_xlabel('IoU'); ax.set_title('TC05 · IoU theo lớp — patch 10003 (held-out)', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'per_class_iou_10003.png', dpi=110); plt.close(fig)

ev.save('input.json', dict(patches={10003: 'S2_10003.npy + TARGET_10003.npy (official PASTIS, Fold 5 = test)',
                                     10000: 'S2_10000.npy + TARGET_10000.npy (Fold 1 = training, reference only)'},
                           windows='25 windows 24x24 covering 120x120 px', ignore_label=ai.VOID,
                           checkpoint_sha256=ai.engine().sha256))
ev.save('output.json', results)
t = results[10003]
ev.check('OA trên patch held-out 10003 >= 0.70', t['overall_accuracy'] >= THRESHOLD_OA, f'>= {THRESHOLD_OA}', t['overall_accuracy'])
ev.check('mIoU trên patch held-out 10003 >= 0.40', t['miou'] >= THRESHOLD_MIOU, f'>= {THRESHOLD_MIOU}', t['miou'])
ev.check('Nhãn dự đoán trong khoảng 0..18', bool(np.load(ev.dir / 'pred_10003.npy').max() <= 18), '<= 18', int(np.load(ev.dir / 'pred_10003.npy').max()))
ev.finish(expected='Trên patch held-out 10003: OA >= 0.70 và mIoU >= 0.40; nhãn hợp lệ 0..18.',
          actual=f"10003: OA={t['overall_accuracy']}, mIoU={t['miou']}, macro-F1={t['macro_f1']}; "
                 f"10000 (training, tham khảo): OA={results[10000]['overall_accuracy']}, mIoU={results[10000]['miou']}",
          notes='Chỉ có 1 patch held-out có ground truth tại local (14.400 pixel) nên kết quả mang tính chỉ báo, không thay thế đánh giá trên toàn bộ fold test PASTIS. mIoU tính trên các lớp xuất hiện trong GT hoặc dự đoán, bỏ void (19).',
          metrics=dict(test_10003={k: v for k, v in t.items() if k != 'confusion_matrix'},
                       train_10000={k: v for k, v in results[10000].items() if k not in ('confusion_matrix', 'per_class')}))
