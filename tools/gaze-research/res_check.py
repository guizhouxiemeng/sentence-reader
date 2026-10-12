#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
res_check.py — 核实"屏幕分辨率/窗口尺寸"是否影响了数据可比性

采集器的行为：设置页的屏幕宽高默认填 window.innerWidth/Height。
  · 若点了"进入全屏"，填的是全屏后的尺寸
  · 若没进全屏，填的是窗口尺寸 —— 而目标点坐标是按这个值生成的

所以三种情况要分清：
  A. 字段正确、也确实全屏 → 归一化可信
  B. 没全屏但字段=窗口 → 目标点只覆盖窗口区域，归一化仍自洽，
     但"对角线"比全屏小，误差占比会被略微高估
  C. 字段与目标点生成尺寸不一致（异常）→ 数据不可信

判据：目标坐标的跨度应当恰好等于 0.84 × 屏幕尺寸（INSET=0.08）。
用法： python tools/res_check.py a.csv b.csv c.csv
"""
import argparse
import csv
import os
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

INSET = 0.08
ASPECT_CANDIDATES = [
    (1920, 1080, '1080p'), (2560, 1440, '1440p'), (3840, 2160, '4K'),
    (1600, 900, '900p'), (1366, 768, '768p'), (1280, 720, '720p'),
    (2560, 1600, '16:10 2.5K'), (2880, 1800, '16:10 2.8K'), (3456, 2234, 'MacBook 16'),
    (3024, 1964, 'MacBook 14'), (1680, 1050, '16:10 WSXGA'),
]


def check(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    tx = [float(r[c['tx']]) for r in rows]
    ty = [float(r[c['ty']]) for r in rows]
    spanx = max(tx) - min(tx)
    spany = max(ty) - min(ty)
    W = spanx / (1 - 2 * INSET)
    H = spany / (1 - 2 * INSET)
    print('=' * 76)
    print(os.path.basename(path))
    print('  帧数 %d   目标 x 范围 %.0f..%.0f (跨度 %.0f)   y 范围 %.0f..%.0f (跨度 %.0f)'
          % (len(rows), min(tx), max(tx), spanx, min(ty), max(ty), spany))
    print('  按 INSET=%.2f 反推的采集时尺寸: %.0f x %.0f   (宽高比 %.3f)'
          % (INSET, W, H, W / max(H, 1e-9)))
    print('  对角线 %.0f px' % (W * W + H * H) ** 0.5 if False else '  对角线 %.0f px' % ((W * W + H * H) ** 0.5))

    # 与常见分辨率比对（归一化到相同宽高比，避免 DPI 缩放干扰）
    best = None
    for cw, ch, name in ASPECT_CANDIDATES:
        # 只看宽高比是否吻合
        d = abs((cw / ch) - (W / H))
        if best is None or d < best[0]:
            best = (d, cw, ch, name)
    d, cw, ch, name = best
    print('  宽高比最接近: %s (%dx%d), 比例差 %.4f' % (name, cw, ch, d))

    # 若是全屏，尺寸应等于某个常见分辨率（或等比例缩小）；若不是，通常是窗口尺寸
    ratio = W / cw
    print('  推断的缩放因子 W/候选宽 = %.3f' % ratio)
    if 0.97 <= ratio <= 1.03:
        print('  → 很可能就是 %s 全屏采集，归一化可信' % name)
    else:
        print('  → 尺寸明显小于 %s，说明**当时不是全屏**，或显示器不是该分辨率' % name)
        print('     这本身不算错误：目标点坐标就是按这个尺寸生成的，二者自洽。')
        print('     但"误差/对角线"会因此被略微高估 —— 因为实际可用屏幕更大。')

    # 更重要的一致性检查：所有点的分布是否均匀覆盖 4x3 网格
    import numpy as np
    q = np.round(np.array(tx) / 60).astype(int) * 100000 + np.round(np.array(ty) / 60).astype(int)
    u = np.unique(q)
    print('  去重后的目标位置数: %d  (抖动会让真实网格点多于 12)' % len(u))
    return W, H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()
    dims = []
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); continue
        dims.append((os.path.basename(f), check(f)))
    if len(dims) > 1:
        print('\n' + '=' * 76)
        print('跨会话尺寸一致性：')
        for n, (W, H) in dims:
            print('   %-28s %.0f x %.0f' % (n, W, H))
        ws = [d[0] for _, d in dims]
        hs = [d[1] for _, d in dims]
        print('   宽度极差 %.0f px   高度极差 %.0f px' % (max(ws) - min(ws), max(hs) - min(hs)))
        if max(ws) - min(ws) < 15 and max(hs) - min(hs) < 15:
            print('   → 三次采集的屏幕尺寸一致，误差指标可以直接横向比较 ✓')
        else:
            print('   → 尺寸不一致，比较误差时应各自用自己的对角线归一化')
    return 0


if __name__ == '__main__':
    sys.exit(main())
