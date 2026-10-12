#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
compare_featuresets.py — 特征集对比：抖动到底能不能降下来

问题
----
连续光标版唯一的毛病是抖动。已确认：
  · 1€ filter 用官方实现、已逐行验证正确
  · 但"抖动-延迟"交换比不划算（降 45% 抖动要付 200ms 延迟，预算只有 10~20ms）
  · 所以滤波这条路到顶了

那就只剩"从源头提高信噪比"。而早期数据显示一个关键差异：
    绝对坐标  f_irisL_y  信噪比 6.26    f_irisL_x  5.67
    纯相对量  f_L_h      信噪比 1.52    f_R_h      1.38
差 4 倍。原因是我们的相对量为了消掉头位，把信号也一起消掉了。

EyeTrax 的做法是"绝对坐标 + 显式头姿补偿"：不试图消掉头位，
而是把头姿作为显式特征让拟合去补偿。

本脚本用【已有的 4147 帧数据】比较三套特征，同一评估方式：
  A. 纯相对量（7 维，当前 reader 用的）
  B. 绝对坐标 + 头姿（EyeTrax 思路）
  C. 全部（相对 + 绝对 + 头姿）

指标（关键：区分"准"和"稳"）
  · 系统偏差 = |预测均值 − 目标|  → 可靠校准消除
  · 抖动     = 同一目标内预测的标准差 → 只能靠时间平均，这才是限制
  · 信噪比   = 组间标准差 / 组内标准差

用法： python tools/compare_featuresets.py
"""
import csv
import math
import sys
from collections import defaultdict

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 相对路径 —— 从仓库根目录运行即可。
#  原来写死成本机绝对路径，只在作者本机能跑。
CSV = 'gaze_p411900_frames.csv'

RELATIVE = ['f_L_h', 'f_R_h', 'f_L_v', 'f_R_v', 'f_iod']
ABSOLUTE = ['f_irisL_x', 'f_irisL_y', 'f_irisR_x', 'f_irisR_y',
            'f_eyecenter_x', 'f_eyecenter_y', 'f_iod']
HEADPOSE = ['f_yaw', 'f_pitch', 'f_fore_z', 'f_z_nose', 'f_fore_x', 'f_fore_y']


def ridge_fit(Z, y, lam=1000.0):
    d = Z.shape[1]
    G = Z.T @ Z + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, Z.T @ y)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(G, Z.T @ y, rcond=None)[0]


def build_Z(X, tr):
    mu = X[tr].mean(0)
    sd = X[tr].std(0) + 1e-12
    return mu, sd


def evaluate(cols, rows, T, Y, tgt, name):
    """逐 trial 留一：测系统偏差、抖动、信噪比。"""
    miss = [c for c in cols if c not in rows[0]]
    if miss:
        return None, '缺少列: %s' % miss
    X = np.array([[float(r[c]) for c in cols] for r in rows])

    pred = np.zeros_like(Y)
    for t in np.unique(T):
        te = (T == t)
        tr = ~te
        mu = X[tr].mean(0)
        sd = X[tr].std(0) + 1e-12
        Ztr = np.column_stack([(X[tr] - mu) / sd, np.ones(tr.sum())])
        Zte = np.column_stack([(X[te] - mu) / sd, np.ones(te.sum())])
        bx = ridge_fit(Ztr, Y[tr, 0])
        by = ridge_fit(Ztr, Y[tr, 1])
        pred[te, 0] = Zte @ bx
        pred[te, 1] = Zte @ by

    dev = np.hypot(pred[:, 0] - Y[:, 0], pred[:, 1] - Y[:, 1])
    # 抖动：同一 trial 内预测相对自身均值的散布（与坐标无关的"稳不稳"）
    jit = []
    # 系统偏差：同一 trial 内预测均值与目标的距离
    bias = []
    for t in np.unique(T):
        m = (T == t)
        a = pred[m]
        jit.append(math.hypot(a[:, 0].std(), a[:, 1].std()))
        cx, cy = a[:, 0].mean(), a[:, 1].mean()
        bias.append(math.hypot(cx - tgt[t][0], cy - tgt[t][1]))
    jit = float(np.median(jit))
    bias = float(np.median(bias))

    # 信噪比：沿屏幕 y 方向（本数据目标只在 4x3 网格上）
    gy = defaultdict(list)
    for i in range(len(rows)):
        gy[(tgt[T[i]][0], tgt[T[i]][1])].append(pred[i, 1])
    means = np.array([np.mean(v) for v in gy.values()])
    withins = np.array([np.std(v) for v in gy.values()])
    snr_y = float(means.std() / (withins.mean() + 1e-12))

    return dict(name=name, nfeat=len(cols), jitter=jit, bias=bias,
                dev=float(dev.mean()), snr=snr_y), None


def main():
    with open(CSV, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    T = np.array([int(r['trial']) for r in rows])
    Y = np.array([[float(r['tx']), float(r['ty'])] for r in rows])
    tgt = {}
    for r in rows:
        tgt[int(r['trial'])] = (float(r['tx']), float(r['ty']))

    print('=' * 88)
    print('特征集对比：能不能把抖动降下来')
    print('=' * 88)
    print('  数据: %d 帧 / %d 个目标位置' % (len(rows), len(tgt)))
    print()

    sets = [
        ('A 纯相对量（当前 reader）', RELATIVE),
        ('B 绝对坐标 + 头姿（EyeTrax 思路）', ABSOLUTE + HEADPOSE),
        ('C 全部（相对 + 绝对 + 头姿）', RELATIVE + ABSOLUTE + HEADPOSE),
    ]

    print('  %-34s %-6s %-12s %-12s %-12s %s'
          % ('特征集', '维度', '系统偏差px', '抖动px', '平均误差px', '信噪比'))
    print('  ' + '-' * 84)
    results = []
    for name, cols in sets:
        r, err = evaluate(cols, rows, T, Y, tgt, name)
        if r is None:
            print('  %-34s %s' % (name, err))
            continue
        results.append(r)
        print('  %-34s %-6d %-12.0f %-12.1f %-12.0f %.2f'
              % (name, r['nfeat'], r['bias'], r['jitter'], r['dev'], r['snr']))

    print()
    print('=' * 88)
    print('判读')
    print('=' * 88)
    if len(results) < 2:
        print('  样本不足，无法比较')
        return 0

    a = results[0]
    print('  基准（A 纯相对量）: 抖动 %.1f px　信噪比 %.2f' % (a['jitter'], a['snr']))
    print()
    for r in results[1:]:
        ratio_j = r['jitter'] / a['jitter']
        ratio_s = r['snr'] / a['snr'] if a['snr'] else float('nan')
        verdict = ('明显更好' if ratio_j < 0.7 else
                   ('略好' if ratio_j < 0.9 else
                    ('相当' if ratio_j < 1.1 else '更差')))
        print('  %s' % r['name'])
        print('     抖动 %.1f px（A 的 %.2f 倍）　信噪比 %.2f（A 的 %.2f 倍）　%s'
              % (r['jitter'], ratio_j, r['snr'], ratio_s, verdict))

    print()
    print('  说明：')
    print('    · 系统偏差可靠校准消除，所以判断"能不能做连续光标"要看【抖动】')
    print('    · 抖动是同一目标下预测的散布，滤波只能降它的绝对值、降不了相对比例')
    print('    · 若 B 的抖动降到 A 的 0.7 倍以下，换特征就是有效的改进；')
    print('      否则说明"视线连续坐标"在这套硬件上确实不可用。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
