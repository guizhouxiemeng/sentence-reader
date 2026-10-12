#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_zones.py — 验证"粗分区判定"的可行性（用户思路）

用户提示：NavEye / Eye Auto Scroll / WebGazer 这类工具并不追求精确的视线坐标，
而是做粗粒度区域判定 —— "视线是否在屏幕底部区域"、"是否在左/右侧"。
这是二分类问题，对噪声的容忍度远高于回归。

这恰好绕开了本项目最大的困难：回归要求逐帧精度，而区域判定只需要
"一段时间内视线大致落在哪个区域"，天然可用时间积分提纯。

本脚本用真实数据评估各方向的分区可分性：
  1. 把目标按屏幕位置分成 上/中/下 或 左/中/右 三区
  2. 用特征做三分类（留一网格点交叉验证）
  3. 报告混淆矩阵与准确率

关键判据：
  · 准确率显著高于随机（33%）说明该方向可分
  · "上 vs 下"（二分类）的准确率尤其重要 —— 它决定"底部区域触发"是否可行

用法： python tools/test_zones.py
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
INSET = 0.08


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
    iry = (col('irisL_y') + col('irisR_y')) / 2
    irx = (col('irisL_x') + col('irisR_x')) / 2
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    gy = (iry - (col('eyeOL_y') + col('eyeOR_y')) / 2) / iod
    X = np.column_stack([iry, irx, gx, gy, gx * gx, iry * iry,
                         col('L_h'), col('L_h2'), col('R_h'), col('R_h2'),
                         col('eyecenter_y'), col('nose_y'), col('pitch')])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    return X, tx, ty, tr


def zone3(v, lo, hi):
    """三分类：低 / 中 / 高。"""
    z = np.ones(len(v), dtype=int)
    z[v < lo] = 0
    z[v > hi] = 2
    return z


def fit_predict(Xtr, ytr, Xte):
    """岭正则最小二乘分类：把三类的 one-hot 当回归目标，取最大响应。"""
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    A = np.column_stack([(Xtr - mu) / sd, np.ones(len(Xtr))])
    d = A.shape[1]
    G = A.T @ A + np.diag([10.0] * (d - 1) + [0.0])
    Y = np.zeros((len(ytr), 3))
    Y[np.arange(len(ytr)), ytr] = 1
    try:
        B = np.linalg.solve(G, A.T @ Y)
    except np.linalg.LinAlgError:
        return None
    Ae = np.column_stack([(Xte - mu) / sd, np.ones(len(Xte))])
    return np.argmax(Ae @ B, axis=1)


def evaluate(X, tx, ty, tr, axis):
    """按目标位置的三个分区做留一【网格点】交叉验证。"""
    v = ty if axis == 'y' else tx
    lo, hi = np.percentile(v, 33), np.percentile(v, 67)
    z = zone3(v, lo, hi)
    # 每个试次一个标签（同试次目标相同）
    ks = np.unique(tr)
    key_z = np.array([z[tr == k][0] for k in ks])
    pred = np.full(len(z), -1)
    for k, kz in zip(ks, key_z):
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        p = fit_predict(X[trn], np.array([key_z[list(ks).index(kk)] for kk in
                                          [np.where(ks == t)[0][0] for t in tr[trn]]]), X[te])
        if p is not None:
            pred[te] = p
    ok = pred >= 0
    if ok.sum() < 20:
        return None
    acc = (pred[ok] == z[ok]).mean()
    # 混淆矩阵
    cm = np.zeros((3, 3), dtype=int)
    for t, p in zip(z[ok], pred[ok]):
        cm[t, p] += 1
    return acc, cm, ok.sum()


def evaluate_binary(X, tx, ty, tr, axis, which):
    """二分类：关注"是否落在某一端"（对应"是否看向底部/左侧"）。"""
    v = ty if axis == 'y' else tx
    lo, hi = np.percentile(v, 40), np.percentile(v, 60)
    if which == 'high':
        y = (v > hi).astype(int)      # 例如"看向底部"
    else:
        y = (v < lo).astype(int)
    ks = np.unique(tr)
    key_y = np.array([int(y[tr == k][0]) for k in ks])
    idx_of = {int(k): i for i, k in enumerate(ks)}
    pred = np.full(len(y), -1)
    for k in ks:
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        ytr = np.array([key_y[idx_of[int(t)]] for t in tr[trn]])
        mu, sd = X[trn].mean(0), X[trn].std(0) + 1e-9
        A = np.column_stack([(X[trn] - mu) / sd, np.ones(trn.sum())])
        d = A.shape[1]
        G = A.T @ A + np.diag([10.0] * (d - 1) + [0.0])
        try:
            B = np.linalg.solve(G, A.T @ ytr)
        except np.linalg.LinAlgError:
            continue
        Ae = np.column_stack([(X[te] - mu) / sd, np.ones(te.sum())])
        pred[te] = (Ae @ B > 0.5).astype(int)
    ok = pred >= 0
    if ok.sum() < 20:
        return None
    acc = (pred[ok] == y[ok]).mean()
    base = max(y[ok].mean(), 1 - y[ok].mean())   # 多数类基线
    return acc, base, ok.sum()


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 78)
    print('【三分类：视线落在哪个区域】随机基线 = 33%')
    print('=' * 78)
    for axis, label in [('x', '水平（左/中/右）'), ('y', '垂直（上/中/下）')]:
        accs, cms = [], []
        for X, tx, ty, tr in data:
            r = evaluate(X, tx, ty, tr, axis)
            if r:
                accs.append(r[0]); cms.append(r[1])
        if not accs:
            continue
        print('\n%s：平均准确率 %.1f%%' % (label, 100 * np.mean(accs)))
        cm = np.sum(cms, axis=0)
        print('  混淆矩阵（行=真实，列=预测）:')
        for i, nm in enumerate(['低', '中', '高']):
            row = cm[i]
            tot = row.sum() or 1
            print('    %s: %s   (召回 %.0f%%)' % (nm, ' '.join('%5d' % x for x in row),
                                                  100 * row[i] / tot))

    print('\n' + '=' * 78)
    print('【二分类：是否看向某一端】—— 对应"看向底部触发翻页"这类需求')
    print('=' * 78)
    print('%-26s %10s %10s %10s' % ('任务', '准确率', '多数类基线', '提升'))
    print('-' * 78)
    for axis, which, label in [('y', 'high', '看向底部（触发翻页）'),
                               ('y', 'low', '看向顶部（触发回翻）'),
                               ('x', 'high', '看向右侧'),
                               ('x', 'low', '看向左侧')]:
        accs, bases = [], []
        for X, tx, ty, tr in data:
            r = evaluate_binary(X, tx, ty, tr, axis, which)
            if r:
                accs.append(r[0]); bases.append(r[1])
        if not accs:
            continue
        a, b = np.mean(accs), np.mean(bases)
        print('%-26s %9.1f%% %9.1f%% %+9.1f pp' % (label, 100 * a, 100 * b, 100 * (a - b)))

    print('\n判据：')
    print('  · 准确率明显高于基线 → 该方向的分区判定可行，可以做"注视区域触发"的交互')
    print('  · 尤其是"看向底部"这一项 —— 它决定翻页/滚动功能是否成立')
    return 0


if __name__ == '__main__':
    sys.exit(main())
