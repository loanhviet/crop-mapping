"""TC08 — Out-of-Distribution Behavior: PASTIS test tiles (in-distribution) vs Normandy THEIA COG region (domain shift)."""
import scripts.common as c
import scripts.ai_common as ai
import numpy as np
import matplotlib.pyplot as plt

from inference import CLASS_NAMES

ev = c.Evidence('TC08', 'Out-of-Distribution Behavior', 'AI Test', 'Local')
prov = ai.provider()
eng = ai.engine()


def run(pid, windows):
    conf_all, labels_all = [], []
    for r, col in windows:
        lab, conf = eng.predict(np.asarray(prov.window(pid, r, col), np.float32), prov.window_doy(pid, r, col))
        conf_all.append(conf.ravel()); labels_all.append(lab.ravel())
    return np.concatenate(conf_all), np.concatenate(labels_all)


groups = {}
id_patches = [p['id'] for p in prov.public_catalog(False)['patches']]
conf, lab = zip(*[run(pid, ai.WINDOWS) for pid in id_patches])
groups['PASTIS test (in-distribution)'] = dict(source=f'{len(id_patches)} patch PASTIS split test: {id_patches}', windows=25 * len(id_patches),
                                              conf=np.concatenate(conf), labels=np.concatenate(lab))

region = 900010
valid = prov.valid_mask(region)
h, w = prov.get(region)['shape']
candidates = [(r, col) for r in range(0, h, 24) for col in range(0, w, 24) if valid[r:r+24, col:col+24].all()]
rng = np.random.default_rng(0)
picked = [candidates[i] for i in sorted(rng.choice(len(candidates), 100, replace=False))]
cn, ln = run(region, picked)
groups['Normandy THEIA COG (domain shift)'] = dict(source=f'Region {region}: 100 cửa sổ 24x24 chọn ngẫu nhiên (seed 0) trong {len(candidates)} cửa sổ hợp lệ',
                                                    windows=100, conf=cn, labels=ln)

stats = {}
for name, g in groups.items():
    hist = np.bincount(g['labels'], minlength=19)
    stats[name] = dict(source=g['source'], windows=g['windows'], pixels=int(g['conf'].size),
                       mean_confidence=round(float(g['conf'].mean()), 4),
                       median_confidence=round(float(np.median(g['conf'])), 4),
                       share_conf_below_0_5=round(float((g['conf'] < .5).mean()), 4),
                       share_conf_below_0_7=round(float((g['conf'] < .7).mean()), 4),
                       class_distribution={CLASS_NAMES[i]: round(float(v / hist.sum()), 4) for i, v in enumerate(hist) if v})
    ev.log(f'{name}: pixels={g["conf"].size} meanConf={stats[name]["mean_confidence"]} <0.5={stats[name]["share_conf_below_0_5"]}')

fig, axes = plt.subplots(1, 2, figsize=(13, 4.3))
for name, g in groups.items():
    axes[0].hist(g['conf'], bins=40, range=(0, 1), density=True, alpha=.55, label=name)
axes[0].set_xlabel('Softmax confidence'); axes[0].set_ylabel('Mật độ'); axes[0].legend(fontsize=8)
axes[0].set_title('Phân bố confidence', fontsize=9)
names = list(groups)
classes = sorted({c for n in names for c in stats[n]['class_distribution']}, key=lambda c: CLASS_NAMES.index(c))
x = np.arange(len(classes))
for i, n in enumerate(names):
    axes[1].bar(x + (i - .5) * .4, [stats[n]['class_distribution'].get(c, 0) for c in classes], .4, label=n)
axes[1].set_xticks(x, classes, rotation=60, ha='right', fontsize=7); axes[1].set_ylabel('Tỉ lệ pixel'); axes[1].legend(fontsize=8)
axes[1].set_title('Phân bố lớp dự đoán', fontsize=9)
fig.suptitle('TC08 · In-distribution vs domain shift (dữ liệu thực, không có ground truth cho Normandy)', fontsize=10)
fig.tight_layout(); fig.savefig(ev.dir / 'ood_confidence_classes.png', dpi=110); plt.close(fig)

ev.save('input.json', {n: dict(source=g['source'], windows=g['windows']) for n, g in groups.items()})
ev.save('output.json', stats)
idn, ood = stats[names[0]], stats[names[1]]
ev.check('Suy luận trên dữ liệu domain shift không lỗi', True, 'không exception', f"{ood['pixels']} pixel")
ev.check('Mô hình thể hiện độ bất định cao hơn trên domain shift (mean confidence thấp hơn ít nhất 0.05)',
         idn['mean_confidence'] - ood['mean_confidence'] >= .05, '>= 0.05', round(idn['mean_confidence'] - ood['mean_confidence'], 4))
ev.finish(expected='Mô hình chạy ổn định trên dữ liệu ngoài phân phối huấn luyện và thể hiện độ bất định cao hơn (mean confidence thấp hơn ít nhất 0.05 so với in-distribution).',
          actual=f"Mean confidence ID={idn['mean_confidence']}, Normandy={ood['mean_confidence']}; tỉ lệ pixel confidence<0.5: ID={idn['share_conf_below_0_5']}, Normandy={ood['share_conf_below_0_5']}.",
          notes='Normandy là dữ liệu THEIA L2A do hệ thống tự chuẩn bị (pipeline khác PASTIS) nên được coi là domain shift; không có ground truth nên KHÔNG đánh giá độ chính xác, chỉ đánh giá hành vi (confidence, phân bố lớp). Đây là quan sát thực nghiệm, không phải kết luận về độ chính xác.',
          metrics=dict(in_distribution={k: v for k, v in idn.items() if k != 'class_distribution'},
                       domain_shift={k: v for k, v in ood.items() if k != 'class_distribution'}))
