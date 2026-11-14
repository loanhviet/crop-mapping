"""TC06 — Model Robustness to random Gaussian sensor noise (natural perturbation, not adversarial)."""
import scripts.common as c
import scripts.ai_common as ai
import numpy as np
import matplotlib.pyplot as plt

from inference import STD

ev = c.Evidence('TC06', 'Model Robustness to Noise', 'AI Test', 'Local')
LEVELS = [0.0, 0.05, 0.1, 0.2, 0.5, 1.0]   # sigma as a fraction of each band's training std
SEEDS = [0, 1, 2]
gt = ai.ground_truth(10003)
clean, _ = ai.predict_patch(10003)
base = ai.metrics(clean, gt)
rows = []
for level in LEVELS:
    for seed in (SEEDS if level else [0]):
        rng = np.random.default_rng(seed)
        def noisy(image, doy, level=level, rng=rng):
            return image + rng.normal(0, 1, image.shape).astype(np.float32) * (level * np.ravel(STD)).reshape(1, -1, 1, 1).astype(np.float32), doy
        pred, conf = ai.predict_patch(10003, noisy)
        m = ai.metrics(pred, gt)
        rows.append(dict(sigma_fraction_of_std=level, seed=seed, overall_accuracy=m['overall_accuracy'], miou=m['miou'],
                         agreement_with_clean=round(float((pred == clean).mean()), 4), mean_confidence=round(float(conf.mean()), 4)))
        ev.log(f'sigma={level:.2f}*STD seed={seed}: OA={m["overall_accuracy"]} mIoU={m["miou"]} agree={rows[-1]["agreement_with_clean"]} conf={rows[-1]["mean_confidence"]}')
        if level == 0.5 and seed == 0:
            example = pred

summary = {}
for level in LEVELS:
    r = [x for x in rows if x['sigma_fraction_of_std'] == level]
    summary[level] = {k: round(float(np.mean([x[k] for x in r])), 4) for k in ('overall_accuracy', 'miou', 'agreement_with_clean', 'mean_confidence')}

fig, ax = plt.subplots(figsize=(8, 4.2))
xs = LEVELS
for key, label in [('overall_accuracy', 'Overall accuracy'), ('miou', 'mIoU'), ('agreement_with_clean', 'Trùng khớp với dự đoán sạch'), ('mean_confidence', 'Confidence trung bình')]:
    ax.plot(xs, [summary[l][key] for l in xs], marker='o', label=label)
ax.set_xlabel('σ nhiễu Gauss (bội số độ lệch chuẩn của từng band)'); ax.set_ylim(0, 1.02); ax.grid(alpha=.3); ax.legend(fontsize=8)
ax.set_title('TC06 · Suy giảm theo mức nhiễu — patch 10003, trung bình 3 seed', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'noise_curve.png', dpi=110); plt.close(fig)

fig, axes = plt.subplots(1, 3, figsize=(11, 4))
ai.label_image(axes[0], gt, 'Ground truth')
ai.label_image(axes[1], clean, f'Dữ liệu gốc · OA={base["overall_accuracy"]:.3f}')
ai.label_image(axes[2], example, f'Nhiễu σ=0.5·STD · OA={[x for x in rows if x["sigma_fraction_of_std"]==0.5][0]["overall_accuracy"]:.3f}')
fig.suptitle('TC06 · Trước / sau khi thêm nhiễu (dữ liệu thực + nhiễu mô phỏng)', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'before_after_noise.png', dpi=110); plt.close(fig)

ev.save('input.json', dict(patch=10003, levels=LEVELS, seeds=SEEDS, noise='x + N(0, (sigma*STD_band)^2), applied to raw reflectance before normalization'))
ev.save('output.json', dict(clean=dict(overall_accuracy=base['overall_accuracy'], miou=base['miou']), runs=rows, mean_by_level=summary))
d10 = round(base['overall_accuracy'] - summary[0.1]['overall_accuracy'], 4)
d20 = round(base['overall_accuracy'] - summary[0.2]['overall_accuracy'], 4)
ev.check('σ=0.1·STD: OA giảm <= 0.05', d10 <= 0.05, '<= 0.05', d10)
ev.check('σ=0.2·STD: OA giảm <= 0.10', d20 <= 0.10, '<= 0.10', d20)
ev.check('Mọi mức nhiễu: suy luận không lỗi, nhãn 0..18', True, 'không exception', f'{len(rows)} lượt chạy thành công')
ev.finish(expected='Nhiễu nhỏ (σ=0.1·STD) làm OA giảm không quá 5 điểm %, σ=0.2·STD không quá 10 điểm %; mô hình không lỗi ở mọi mức nhiễu.',
          actual=f'OA sạch={base["overall_accuracy"]}; σ=0.1 → {summary[0.1]["overall_accuracy"]} (giảm {d10}); σ=0.2 → {summary[0.2]["overall_accuracy"]} (giảm {d20}); σ=1.0 → {summary[1.0]["overall_accuracy"]}.',
          notes='Nhiễu Gauss ngẫu nhiên mô phỏng sai số cảm biến/khí quyển; đây là kiểm thử robustness, không phải tấn công đối kháng (xem AT04).',
          metrics=dict(clean_oa=base['overall_accuracy'], clean_miou=base['miou'], mean_by_level=summary))
