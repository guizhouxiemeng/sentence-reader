#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
measure_snr.py — 重新正确地测量信噪比

上一次的测量有方法论错误：我用"跨整场"的组间/组内比作为信噪比，
但整场里头部漂移、光照变化、坐姿变化全部被算进了组内噪声，把真实信号淹没了。

正确的分解（方差分析思路）：
    总方差 = 试次间方差（含视线变化 + 头位漂移）+ 试次内方差（含关键点抖动）
所以要看三层：
    L1 试次内抖动      —— 头不动、注视不动时的纯噪声（这是我们能压到多低的下限）
    L2 试次间差异      —— 含视线变化，也含头位漂移（信号 + 混淆）
    L3 剔除头位后的信号 —— 用头位特征做残差，看还剩多少视线信息

关键指标：
    · L1 若远小于 L2，说明"时间平均"能有效提纯，多帧平均就能救回信号
    · 若 L1 ≈ L2，说明连时间平均都救不了（真正的死路）

用法： python tools/measure_snr.py
"""
import csv
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = r"D:\projects\gaze-project"
FILES = ['gaze_p411900_frames.csv', 'gaze_p463357_frames.csv', 'gaze_p496980_frames.csv']


def load(fn):
    p = os.path.join(ROOT, fn)
    with open(p, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    iod = col('iod') + 1e-9
    iry = (col('irisL_y') + col('irisR_y')) / 2
    irx = (col('irisL_x') + col('irisR_x')) / 2
    return dict(tr=tr, tx=tx, ty=ty,
                iris_y=iry, iris_x=irx,
                eye_y=col('eyecenter_y'), eye_x=col('eyecenter_x'),
                head_y=col('nose_y'), head_x=col('nose_x'),
                pitch=col('pitch'), yaw=col('yaw'),
                ear=(col('earL') + col('earR')) / 2)


def variance_decomp(v, tr):
    """返回 (试次内平均 std, 试次间 std)。"""
    ks = np.unique(tr)
    within = [v[tr == k].std() for k in ks if (tr == k).sum() >= 5]
    means = np.array([v[tr == k].mean() for k in ks if (tr == k).sum() >= 5])
    return float(np.mean(within)), float(means.std())


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 84)
    print('【正确的信噪比分解】')
    print('  L1 = 试次内抖动（头不动、注视不动 → 纯噪声下限）')
    print('  L2 = 试次间差异（含视线变化，也含头位漂移）')
    print('  比值 L2/L1 越大，说明时间平均越能提纯信号')
    print('=' * 84)
    print('%-14s %-10s %-12s %-12s %-10s %s' % ('量', '会话', 'L1 试次内', 'L2 试次间', 'L2/L1', '解读'))
    print('-' * 84)
    summary = {}
    for tag, key in [('iris_y(垂直)', 'iris_y'), ('iris_x(水平)', 'iris_x'),
                     ('眼睛中心y', 'eye_y'), ('眼睛中心x', 'eye_x'),
                     ('鼻尖y(头位)', 'head_y'), ('鼻尖x(头位)', 'head_x'),
                     ('pitch(头姿)', 'pitch'), ('yaw(头姿)', 'yaw')]:
        vals = []
        for D in data:
            l1, l2 = variance_decomp(D[key], D['tr'])
            vals.append((l1, l2))
        l1 = np.mean([v[0] for v in vals])
        l2 = np.mean([v[1] for v in vals])
        ratio = l2 / (l1 + 1e-12)
        note = ''
        if ratio > 3:
            note = '时间平均很有效'
        elif ratio > 1.5:
            note = '时间平均有一定效果'
        else:
            note = '时间平均也救不了'
        summary[key] = (l1, l2, ratio)
        print('%-14s %-10s %-12.5f %-12.5f %-10.2f %s'
              % (tag, '平均', l1, l2, ratio, note))

    print('\n' + '=' * 84)
    print('【关键判断：多帧平均能把信号提纯到什么程度】')
    print('=' * 84)
    l1y, l2y, ry = summary['iris_y']
    l1x, l2x, rx = summary['iris_x']
    for name, l1, l2 in [('iris_y', l1y, l2y), ('iris_x', l1x, l2x)]:
        print('  %s: 单帧噪声 %.5f，若平均 N 帧则噪声降到 %.5f' % (name, l1, l1))
        for N in (5, 10, 20, 30):
            noiseN = l1 / np.sqrt(N)
            print('     平均 %2d 帧 → 噪声 %.5f   信噪比(信号%.5f/噪声) = %.2f'
                  % (N, noiseN, l2, l2 / noiseN))

    print('\n' + '=' * 84)
    print('【视线 vs 头位：到底谁在驱动特征】')
    print('=' * 84)
    print('  做法：对每个试次取均值，然后比较"与目标位置的相关"和"与头位特征的相关"')
    for D in data[:1]:
        ks = np.unique(D['tr'])
        m_iry = np.array([D['iris_y'][D['tr'] == k].mean() for k in ks])
        m_irx = np.array([D['iris_x'][D['tr'] == k].mean() for k in ks])
        m_ty = np.array([D['ty'][D['tr'] == k].mean() for k in ks])
        m_tx = np.array([D['tx'][D['tr'] == k].mean() for k in ks])
        m_heady = np.array([D['head_y'][D['tr'] == k].mean() for k in ks])
        m_headx = np.array([D['head_x'][D['tr'] == k].mean() for k in ks])
        corr = lambda a, b: np.corrcoef(a, b)[0, 1]
        print('  iris_y 与 目标y 相关: %+.3f     iris_y 与 头位y 相关: %+.3f'
              % (corr(m_iry, m_ty), corr(m_iry, m_heady)))
        print('  iris_x 与 目标x 相关: %+.3f     iris_x 与 头位x 相关: %+.3f'
              % (corr(m_irx, m_tx), corr(m_irx, m_headx)))
        print('  头位y 与 目标y 相关: %+.3f   ← 若这条也很高，说明头位与视线在数据里混淆'
              % corr(m_heady, m_ty))
        print('  头位x 与 目标x 相关: %+.3f' % corr(m_headx, m_tx))
    return 0


if __name__ == '__main__':
    sys.exit(main())
