#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scale.py — 检查采集时的"人脸尺度"是否漂移，以及它如何污染几何特征

背景：几何特征的量是 (虹膜 - 眼中心)/瞳距。若瞳距在两次会话间变化很大，
      同一注视方向会得到完全不同的特征值，固定系数的几何基线必然失效。
      ear（眼睛张开度）的绝对值也是尺度代理量。

用法： python tools/scale.py a.csv b.csv
"""
import argparse
import csv
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def load_dot(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    return h, c, d


def stats(path):
    h, c, d = load_dot(path)
    g = lambda r, n: np.array([float(x[c['f_' + n]]) for x in r]) if False else None
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    out = {}
    for n in ['iod', 'earL', 'earR', 'eyecenter_x', 'eyecenter_y', 'nose_x', 'nose_y',
              'eyeOL_x', 'eyeOR_x', 'irisL_x', 'irisR_x', 'irisL_y', 'irisR_y']:
        if 'f_' + n in c:
            out[n] = col(n)
    return h, c, d, out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()

    data = []
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); return 1
        h, c, d, s = stats(f)
        data.append((os.path.basename(f), h, c, d, s))

    print('=' * 78)
    print('【人脸尺度 / 位置】—— 决定几何特征是否可比')
    print('   %-26s %10s %10s %10s %10s' % ('文件', 'iod中位', 'ear中位', '眼中心x', '眼中心y'))
    for name, h, c, d, s in data:
        print('   %-26s %10.5f %10.5f %10.5f %10.5f'
              % (name, np.median(s['iod']), np.median((s['earL'] + s['earR']) / 2),
                 np.median(s['eyecenter_x']), np.median(s['eyecenter_y'])))

    print('\n【虹膜相对眼中心的原始像素位移】—— 几何基线的真正输入')
    print('   %-26s %12s %12s %12s %12s' % ('文件', 'x范围', 'y范围', 'x_std', 'y_std'))
    for name, h, c, d, s in data:
        ix = (s['irisL_x'] + s['irisR_x']) / 2 - s['eyecenter_x']
        iy = (s['irisL_y'] + s['irisR_y']) / 2 - s['eyecenter_y']
        print('   %-26s %12.5f %12.5f %12.6f %12.6f'
              % (name, ix.max() - ix.min(), iy.max() - iy.min(), ix.std(), iy.std()))

    # 垂直方向：目标 y 与 gaze_y 的关系是否饱和
    print('\n【垂直方向是否饱和】按目标 y 分 3 档看 gaze_y 的分布')
    for name, h, c, d, s in data:
        gx = ((s['irisL_x'] + s['irisR_x']) / 2 - s['eyecenter_x']) / s['iod']
        gy = ((s['irisL_y'] + s['irisR_y']) / 2 - s['eyecenter_y']) / s['iod']
        ty = np.array([float(r[c['ty']]) for r in d])
        H = (ty.max() - ty.min()) / 0.84
        print('   -- %s  (屏高约 %.0f)' % (name, H))
        for lo, hi, tag in [(0, 0.4, '上'), (0.4, 0.6, '中'), (0.6, 1.01, '下')]:
            m = (ty / H >= lo) & (ty / H < hi)
            if m.sum() == 0:
                continue
            print('      %s: gaze_y 均值=%+.5f  std=%.5f  p5=%+.5f p95=%+.5f  (n=%d)'
                  % (tag, gy[m].mean(), gy[m].std(),
                     np.percentile(gy[m], 5), np.percentile(gy[m], 95), m.sum()))

    # 屏幕下方目标：gaze 与目标的相关是否更弱
    print('\n【分区相关性】gaze_x↔target_x 与 gaze_y↔target_y')
    for name, h, c, d, s in data:
        gx = ((s['irisL_x'] + s['irisR_x']) / 2 - s['eyecenter_x']) / s['iod']
        gy = ((s['irisL_y'] + s['irisR_y']) / 2 - s['eyecenter_y']) / s['iod']
        tx = np.array([float(r[c['tx']]) for r in d])
        ty = np.array([float(r[c['ty']]) for r in d])
        print('   %-26s r(gx,tx)=%+.3f   r(gy,ty)=%+.3f' % (name, np.corrcoef(gx, tx)[0, 1], np.corrcoef(gy, ty)[0, 1]))

    # 眨眼/低质量帧占比
    print('\n【帧质量】ear 过低(疑似闭眼/眯眼)的帧占比')
    for name, h, c, d, s in data:
        ear = (s['earL'] + s['earR']) / 2
        for th in (0.10, 0.15, 0.20):
            print('   %-26s ear<%0.2f : %5.1f%%' % (name, th, 100 * (ear < th).mean()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
