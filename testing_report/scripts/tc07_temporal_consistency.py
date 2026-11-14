"""TC07 — Temporal Data Consistency: missing acquisitions (random and seasonal gaps) + determinism."""
import scripts.common as c
import scripts.ai_common as ai
import numpy as np
import matplotlib.pyplot as plt

ev = c.Evidence('TC07', 'Temporal Data Consistency', 'AI Test', 'Local')
gt = ai.ground_truth(10003)
clean, _ = ai.predict_patch(10003)
again, _ = ai.predict_patch(10003)
base = ai.metrics(clean, gt)
T = len(ai.provider().window_doy(10003, 0, 0))
ev.log(f'patch 10003: {T} acquisitions; clean OA={base["overall_accuracy"]} mIoU={base["miou"]}')
ev.check('Tính tất định: 2 lần suy luận cùng input cho kết quả giống hệt', bool((clean == again).all()), 'identical', f'{int((clean != again).sum())} pixel khác')

rows = []
for fraction in [0.1, 0.25, 0.5, 0.75]:
    for seed in [0, 1, 2]:
        rng = np.random.default_rng(seed)
        keep = np.sort(rng.choice(T, T - int(round(T * fraction)), replace=False))
        pred, conf = ai.predict_patch(10003, lambda im, d, k=keep: (im[k], d[k]))
        m = ai.metrics(pred, gt)
        rows.append(dict(scenario=f'random drop {int(fraction*100)}%', fraction=fraction, seed=seed, frames=len(keep),
                         overall_accuracy=m['overall_accuracy'], miou=m['miou'], mean_confidence=round(float(conf.mean()), 4),
                         agreement_with_clean=round(float((pred == clean).mean()), 4)))
        ev.log(f'{rows[-1]["scenario"]} seed={seed}: frames={len(keep)} OA={m["overall_accuracy"]} mIoU={m["miou"]}')

doy0 = np.asarray(ai.provider().window_doy(10003, 0, 0))
seasonal = {'mất mùa hè (DOY 152–243)': (doy0 >= 152) & (doy0 <= 243),
            'mất mùa xuân (DOY 60–151)': (doy0 >= 60) & (doy0 <= 151),
            'mất mùa đông (DOY 1–59 & 335–365)': (doy0 <= 59) | (doy0 >= 335),
            'chỉ giữ nửa đầu năm (DOY <= 182)': doy0 > 182}
for name, drop in seasonal.items():
    keep = np.where(~drop)[0]
    pred, conf = ai.predict_patch(10003, lambda im, d, k=keep: (im[k], d[k]))
    m = ai.metrics(pred, gt)
    rows.append(dict(scenario=name, fraction=round(float(drop.mean()), 3), seed=None, frames=len(keep),
                     overall_accuracy=m['overall_accuracy'], miou=m['miou'], mean_confidence=round(float(conf.mean()), 4),
                     agreement_with_clean=round(float((pred == clean).mean()), 4)))
    ev.log(f'{name}: frames={len(keep)} OA={m["overall_accuracy"]} mIoU={m["miou"]}')

def mean_oa(fraction):
    return round(float(np.mean([r['overall_accuracy'] for r in rows if r['fraction'] == fraction and r['seed'] is not None])), 4)

fig, axes = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw=dict(width_ratios=[1, 1.4]))
fr = [0, .1, .25, .5, .75]
axes[0].plot([f * 100 for f in fr], [base['overall_accuracy']] + [mean_oa(f) for f in fr[1:]], marker='o', label='OA')
axes[0].plot([f * 100 for f in fr], [base['miou']] + [round(float(np.mean([r['miou'] for r in rows if r['fraction'] == f and r['seed'] is not None])), 4) for f in fr[1:]], marker='s', label='mIoU')
axes[0].set_xlabel('% mốc thời gian bị loại ngẫu nhiên'); axes[0].set_ylim(0, 1); axes[0].grid(alpha=.3); axes[0].legend()
axes[0].set_title('Mất ngẫu nhiên (trung bình 3 seed)', fontsize=9)
sr = [r for r in rows if r['seed'] is None]
axes[1].barh([r['scenario'] + f" ({r['frames']} ảnh)" for r in sr] + [f'đầy đủ ({T} ảnh)'], [r['overall_accuracy'] for r in sr] + [base['overall_accuracy']], color=['#d9822b'] * len(sr) + ['#4a7fb5'])
axes[1].set_xlim(0, 1); axes[1].set_xlabel('Overall accuracy'); axes[1].set_title('Mất theo mùa', fontsize=9)
fig.suptitle('TC07 · Ảnh hưởng của dữ liệu thời gian bị thiếu — patch 10003', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'temporal_gaps.png', dpi=110); plt.close(fig)

fig, ax = plt.subplots(figsize=(10, 1.6))
ax.scatter(doy0, np.zeros_like(doy0), marker='|', s=400)
ax.set_yticks([]); ax.set_xlim(0, 366); ax.set_xlabel('Day of year của các ảnh Sentinel-2 (patch 10003)')
fig.tight_layout(); fig.savefig(ev.dir / 'acquisition_calendar.png', dpi=110); plt.close(fig)

ev.save('input.json', dict(patch=10003, acquisitions=T, doy=doy0.tolist(), scenarios=['random drop 10/25/50/75% x 3 seeds', *seasonal]))
ev.save('output.json', dict(clean=dict(overall_accuracy=base['overall_accuracy'], miou=base['miou']), runs=rows))
d25, d50 = round(base['overall_accuracy'] - mean_oa(.25), 4), round(base['overall_accuracy'] - mean_oa(.5), 4)
ev.check('Mất ngẫu nhiên 25% mốc: OA giảm <= 0.05', d25 <= .05, '<= 0.05', d25)
ev.check('Mất ngẫu nhiên 50% mốc: OA giảm <= 0.15', d50 <= .15, '<= 0.15', d50)
ev.finish(expected='Kết quả tất định; mất 25% mốc thời gian làm OA giảm <= 5 điểm %, mất 50% giảm <= 15 điểm %.',
          actual=f'Tất định: {bool((clean == again).all())}; OA đầy đủ={base["overall_accuracy"]}, mất 25% → {mean_oa(.25)}, 50% → {mean_oa(.5)}, 75% → {mean_oa(.75)}. ' +
                 '; '.join(f"{r['scenario']}: {r['overall_accuracy']}" for r in sr),
          notes='Thiếu mốc thời gian mô phỏng mây che/mất ảnh. Các mốc bị loại được bỏ cùng DOY tương ứng (pipeline tự pad về 60). Kết quả theo mùa cho thấy giai đoạn nào quan trọng với mô hình.',
          metrics=dict(acquisitions=T, clean_oa=base['overall_accuracy'], mean_oa_random_drop={str(f): mean_oa(f) for f in fr[1:]},
                       seasonal={r['scenario']: r['overall_accuracy'] for r in sr}))
