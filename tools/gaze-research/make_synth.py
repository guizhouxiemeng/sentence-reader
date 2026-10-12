#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""make_synth.py — 生成一份合成 CSV 来验证 analyze.py 本身没写错。
两列虹膜特征按真实目标位置线性生成 + 噪声，所以分析脚本应当报告"存在相关信号"。
"""
import csv
import math
import random
import sys

FNAMES = ['L_h', 'L_v', 'L_h2', 'L_v2', 'R_h', 'R_v', 'R_h2', 'R_v2',
          'iod', 'earL', 'earR', 'yaw', 'pitch',
          'irisL_x', 'irisL_y', 'irisL_z', 'irisR_x', 'irisR_y', 'irisR_z',
          'eyeOL_x', 'eyeOL_y', 'eyeOR_x', 'eyeOR_y', 'eyeIL_x', 'eyeIL_y', 'eyeIR_x', 'eyeIR_y',
          'eyecenter_x', 'eyecenter_y', 'fore_z', 'nose_x', 'nose_y', 'chin_x', 'chin_y',
          'fore_x', 'fore_y', 'z_irisL', 'z_irisR', 'z_nose']

W, H = 1920.0, 1080.0
COLS, ROWS = 4, 3
INSET = 0.08
random.seed(7)

rows = []
t = 0.0
trial = 0
for round_i in range(3):
    pts = [(INSET * W + (W - 2 * INSET * W) * (c / (COLS - 1)),
            INSET * H + (H - 2 * INSET * H) * (r / (ROWS - 1)))
           for r in range(ROWS) for c in range(COLS)]
    random.shuffle(pts)
    for (tx, ty) in pts:
        # 期望特征值：与目标线性相关
        ex = (tx / W - 0.5) / 1.55
        ey = (ty / H - 0.5) / 1.35
        for phase, dur in (('pre', 700), ('dot', 800)):
            steps = max(1, int(dur / 33))
            for k in range(steps):
                if phase == 'dot' and (k * 33) < 280:
                    continue          # 与采集器一致：丢弃视线飞行期
                jitter = 0.004 if phase == 'dot' else 0.02
                lh = ex + random.gauss(0, jitter)
                lv = ey + random.gauss(0, jitter)
                rh = ex + random.gauss(0, jitter)
                rv = ey + random.gauss(0, jitter)
                vals = [lh, lv, lh * 0.98, lv * 1.01, rh, rv, rh * 0.99, rv * 0.99,
                        0.22, 0.30, 0.30, 0.5 + 0.02 * ex, 1.1,
                        0.5 + 0.02 * ex, 0.5 + 0.02 * ey, -0.02,
                        0.5 + 0.02 * ex, 0.5 + 0.02 * ey, -0.02,
                        0.30, 0.42, 0.62, 0.42, 0.42, 0.42, 0.54, 0.42,
                        0.46, 0.42, -0.01, 0.5, 0.55, 0.48, 0.72, 0.47, 0.2, -0.03, -0.03, -0.05]
                rows.append([round(t, 2), trial, phase, round(tx, 2), round(ty, 2)] +
                            [round(v, 6) for v in vals])
                t += 33.3
        trial += 1

header = ['t', 'trial', 'phase', 'tx', 'ty'] + ['f_' + n for n in FNAMES]
out = sys.argv[1] if len(sys.argv) > 1 else 'synth_frames.csv'
with open(out, 'w', encoding='utf-8', newline='') as f:
    w = csv.writer(f)
    w.writerow(header)
    w.writerows(rows)
print('wrote', out, len(rows), 'rows,', trial, 'trials')
