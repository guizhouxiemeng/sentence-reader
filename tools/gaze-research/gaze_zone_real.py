#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gaze_zone_real.py — 用【真实视线数据】验证 2x2 区域判定的实际准确率

为什么必须先做这一步
--------------------
融合的前提是"眼动能把目标缩小到 2x2 里的一个区域"。
已知实测（README 里的量化结果）：
    二分类 看向底部 81.0% / 看向顶部 86.8% / 看向左侧 80.9% / 看向右侧 76.7%
    三分类 水平 66.3% / 垂直 56.4%

四分类（2x2 象限）会落在哪个区间？如果它明显低于 80%，
那"纯眼动选目标"（条件 B）就不可靠，融合的价值主要只剩"减少手部移动"，
而不是"提升准确率"—— 这个区别决定了 README 该怎么写。

做法
----
用真实采集的会话（含 39 维特征与目标坐标）：
  ① 重建 demo 用的 7 维视线特征（已剔除被眼皮污染的量）
  ② 把目标映射到 2x2 象限标签
  ③ 按【目标位置】留一交叉验证（不是按帧！按帧会得到虚高的数字）
  ④ 报准确率、混淆矩阵，并与二分类基线对比

用法： python tools/gaze_zone_real.py
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
    iod = col('iod') + 1e-9
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    # 与 demo 的 buildGazeFeatures 完全一致的 7 维
    F = np.column_stack([
        iry, irx, gx, gx * gx, iry * iry,
        (col('irisL_x') - col('eyeOL_x')) / iod,
        (col('irisR_x') - col('eyeOR_x')) / iod,
    ])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    return F, tx, ty, tr


def label2x2(tx, ty, W, H):
    """把目标坐标映射到 2x2 象限标签（0=左上,1=右上,2=左下,3=右下）。

    分界点必须用【实际目标坐标的中点】，不能用 W/2、H/2。
    这里踩过一个坑：按 (ty/H > 0.5) 划分，但目标坐标的范围是 0.08~0.92
    倍的视口（INSET=0.08），所以 0.5 倍的 H 并不是目标的上下分界，
    导致下半象限被错误标注，混淆矩阵出现"下半召回 5%"的假象。
    正确做法是取目标坐标自身的中位数作为分界。
    """
    cx = (tx > np.median(tx)).astype(int)
    cy = (ty > np.median(ty)).astype(int)
    return cy * 2 + cx


def ridge(A, y, lam=10.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def loo_zone_acc(F, lab, tr, nz):
    """按目标位置留一：留出一个 trial，用其余训练，预测留出 trial 的区域。"""
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
    ks = np.unique(tr)
    lab_tr = {k: lab[tr == k][0] for k in ks}
    pred = np.full(len(lab), -1)
    for k in ks:
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        B = []
        ok = True
        for lv in range(nz):
            ytr = np.array([1.0 if lab_tr[int(t)] == lv else 0.0 for t in tr[trn]])
            b = ridge(Z[trn], ytr)
            if b is None:
                ok = False
                break
            B.append(b)
        if not ok:
            continue
        sc = Z[te] @ np.array(B).T
        pred[te] = np.argmax(sc, axis=1)
    m = pred >= 0
    if m.sum() < 20:
        return None, None, None
    acc = (pred[m] == lab[m]).mean()
    cm = np.zeros((nz, nz), dtype=int)
    for t, p in zip(lab[m], pred[m]):
        cm[t, p] += 1
    return acc, cm, m.sum()


def loo_binary_acc(F, tx, ty, tr, axis, thr=0.5):
    """二分类基线：是否在某一侧（对应 README 里的 80% 左右数字）。"""
    v = tx if axis == 'x' else ty
    W = v.max() - v.min()
    base = v.min()
    y = ((v - base) / W > thr).astype(int)
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
    ks = np.unique(tr)
    yt = {k: int(y[tr == k][0]) for k in ks}
    pred = np.full(len(y), -1)
    for k in ks:
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        ytr = np.array([yt[int(t)] for t in tr[trn]])
        b = ridge(Z[trn], ytr.astype(float))
        if b is None:
            continue
        pred[te] = (Z[te] @ b > 0.5).astype(int)
    m = pred >= 0
    return (pred[m] == y[m]).mean() if m.sum() > 20 else None


def main():
    data = []
    for fn in FILES:
        p = os.path.join(ROOT, fn)
        if os.path.exists(p):
            data.append((fn, load(p)))
    print('载入 %d 个会话\n' % len(data))

    print('=' * 78)
    print('【2x2 象限判定：真实数据，按目标位置留一交叉验证】')
    print('=' * 78)
    print('  %-26s %-14s %-14s %s' % ('会话', '2x2 准确率', '帧数', '说明'))
    print('  ' + '-' * 74)
    accs, cms = [], []
    for fn, (F, tx, ty, tr) in data:
        W = (tx.max() - tx.min()) / (1 - 0.16)
        H = (ty.max() - ty.min()) / (1 - 0.16)
        lab = label2x2(tx, ty, W, H)
        nz = len(np.unique(lab))
        acc, cm, n = loo_zone_acc(F, lab, tr, nz)
        if acc is None:
            continue
        accs.append(acc)
        cms.append(cm)
        note = '可用' if acc > 0.75 else ('勉强' if acc > 0.6 else '不可用')
        print('  %-26s %-14s %-14d %s' % (fn, '%.1f%%' % (acc * 100), n, note))
    print('\n  平均 2x2 准确率: %.1f%%   （随机基线 25%%）'
          % (100 * np.mean(accs)) if accs else '  无有效结果')

    if cms:
        cm = np.sum(cms, axis=0)
        print('\n  混淆矩阵（行=真实象限，列=预测；0左上 1右上 2左下 3右下）:')
        for i in range(cm.shape[0]):
            tot = cm[i].sum() or 1
            print('    %d: %s   召回 %.0f%%'
                  % (i, ' '.join('%6d' % x for x in cm[i]), 100 * cm[i][i] / tot))

    print('\n' + '=' * 78)
    print('【与二分类基线对比】确认"区域数越多越难"在真实数据上成立')
    print('=' * 78)
    print('  %-26s %-16s %-16s %s' % ('会话', '左右二分类', '上下二分类', '2x2 四分类'))
    print('  ' + '-' * 74)
    for fn, (F, tx, ty, tr) in data:
        aL = loo_binary_acc(F, tx, ty, tr, 'x')
        aV = loo_binary_acc(F, tx, ty, tr, 'y')
        W = (tx.max() - tx.min()) / (1 - 0.16)
        H = (ty.max() - ty.min()) / (1 - 0.16)
        lab = label2x2(tx, ty, W, H)
        a4, _, _ = loo_zone_acc(F, lab, tr, len(np.unique(lab)))
        fmt = lambda v: ('%.1f%%' % (v * 100)) if v is not None else '—'
        print('  %-26s %-16s %-16s %s' % (fn, fmt(aL), fmt(aV), fmt(a4)))

    print('\n' + '=' * 78)
    print('【对融合实验的直接含义】')
    print('=' * 78)
    if accs:
        a = np.mean(accs)
        print('  眼动 2x2 判定实测准确率约 %.0f%%。' % (a * 100))
        if a > 0.75:
            print('  → 条件 B（纯眼动选目标）可行，融合的前途取决于能否减少手部移动。')
        elif a > 0.6:
            print('  → 条件 B 勉强可用但错误率会偏高；融合的主要价值是"缩小手指搜索范围"。')
        else:
            print('  → 条件 B 不可行。融合的价值将只剩"减少手部移动/出画"，')
            print('     而不是"提升准确率"——这个区别必须如实写进结论。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
