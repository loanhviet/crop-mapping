"""Render a short, readable excerpt of a REAL evidence log (black on white) for the report.

Lines are copied verbatim from evidence/<ID>/execution.log (only the timestamp prefix is dropped);
nothing is edited. Output: evidence/<ID>/report_log_excerpt.png
"""
import re
import unicodedata
from pathlib import Path

import scripts.common as c  # noqa: F401  (adds .pydeps to sys.path)
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt


def excerpt(test_id, keep=None, max_lines=12, width=88):
    src = c.EVIDENCE / test_id / 'execution.log'
    lines = [unicodedata.normalize('NFC', re.sub(r'^\[[\d:.]+\] ', '', l)) for l in src.read_text(encoding='utf-8').splitlines()]
    body = [l for l in lines if (keep(l) if keep else (' · ' in l and (l.startswith('PASS') or l.startswith('FAIL'))))]
    if len(body) > max_lines:  # keep every FAIL line first, then fill with PASS lines in log order
        fails = [l for l in body if l.startswith('FAIL')][:max_lines]
        rest = [l for l in body if not l.startswith('FAIL')][:max_lines - len(fails)]
        chosen = set(fails + rest)
        total = len(body)
        body = [l for l in body if l in chosen][:max_lines]
        body.append(f'... ({total - len(body)} assertion khác, xem đầy đủ trong execution.log)')
    verdict = [l for l in lines if l.startswith('VERDICT')]
    text = [f'$ {test_id}: trích evidence/{test_id}/execution.log', *body, *verdict]
    text = [t if len(t) <= width else t[:width - 3] + '...' for t in text]
    fig = plt.figure(figsize=(6.3, 0.3 + 0.19 * len(text)), dpi=220)
    for i, t in enumerate(text):
        fig.text(0.015, 1 - (0.15 + 0.19 * (i + 0.8)) / (0.3 + 0.19 * len(text)), t,
                 family='DejaVu Sans Mono', fontsize=8.2, color='black', va='baseline')
    fig.patches.append(matplotlib.patches.Rectangle((0.002, 0.004), 0.996, 0.992, transform=fig.transFigure,
                                                    fill=False, edgecolor='black', linewidth=0.6))
    out = c.EVIDENCE / test_id / 'report_log_excerpt.png'
    fig.savefig(out, facecolor='white'); plt.close(fig)
    return out


if __name__ == '__main__':
    for t in ['TC02', 'TC04', 'TC09', 'TC10', 'AT01', 'AT02', 'AT07', 'AT08', 'AT10']:
        print(excerpt(t))
