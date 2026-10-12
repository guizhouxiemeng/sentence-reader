#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_snapui.py — 计算"吸附式点击界面"的可行密度

用户思路：视线移到大致范围 → 吸附到最近的可点击元素 → 模拟点击。
这本质上是把精度问题从【传感器】转移到【界面设计】：
只要元素够大够少，现有精度就能用。

本脚本回答一个具体问题：以我们实测的精度，界面最多能放多少个按钮？

做法：
  1. 用真实数据得到袋外预测误差
  2. 模拟各种网格布局（1x2、2x2、3x3、4x3、4x4、5x4 等）
  3. 对每个布局计算"吸附命中率"：预测点吸附到最近按钮后，是否正确
  4. 同时统计"邻格误选率"（吸附到了错误但相邻的按钮）

判据：
  · 吸附命中率 ≥ 90% 且邻格误选 ≤ 5% 的布局，才算真正可用
  · 这直接给出"精度 → 界面密度"的换算表，是可落地的设计指南

用法： python tools/test_snapui.py
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
    tr = np.array([int(r[c['trial']]) for r in d])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    iod = col('iod') + 1e-9
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    F = np.column_stack([iry, irx, gx, gx * gx, iry * iry,
                         col('L_h'), col('L_h2'), col('R_h'), col('R_h2')])
    return F, tx, ty, tr


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else abs(v)


def ridge(A, y, lam=1000.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def oof(F, tx, ty, tr, dims=6, lam=1000.0):
    order = list(np.argsort(-np.array([max(corr(F[:, i], tx), corr(F[:, i], ty))
                                       for i in range(F.shape[1])]))[:dims])
    X = F[:, order]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    pred = np.full((len(tx), 2), np.nan)
    for k in np.unique(tr):
        te = tr == k
        trn = ~te
        if trn.sum() < 40:
            continue
        A = np.column_stack([Z[trn], np.ones(trn.sum())])
        bx = ridge(A, tx[trn], lam); by = ridge(A, ty[trn], lam)
        if bx is None or by is None:
            continue
        Ae = np.column_stack([Z[te], np.ones(te.sum())])
        pred[te, 0] = Ae @ bx
        pred[te, 1] = Ae @ by
    return pred


def layout_centers(W, H, cols, rows, inset=0.10):
    ix, iy = W * inset, H * inset
    sx, sy = W - 2 * ix, H - 2 * iy
    pts = []
    for r in range(rows):
        for c in range(cols):
            pts.append(((ix + sx * c / max(cols - 1, 1)) if cols > 1 else W / 2,
                        (iy + sy * r / max(rows - 1, 1)) if rows > 1 else H / 2))
    return np.array(pts)


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    for F, tx, ty, tr in data[:1]:
        W = (tx.max() - tx.min()) / (1 - 2 * INSET)
        H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    print('载入 %d 会话   视口 %.0f x %.0f   对角线 %.0f px\n'
          % (len(data), W, H, np.hypot(W, H)))

    # 收集所有会话的袋外预测与真实目标
    print('=' * 84)
    print('【第一步】袋外预测的误差分布（吸附界面的输入）')
    print('=' * 84)
    allerr = []
    for i, (F, tx, ty, tr) in enumerate(data):
        pred = oof(F, tx, ty, tr)
        e = np.linalg.norm(pred - np.column_stack([tx, ty]), axis=1)
        e = e[np.isfinite(e)]
        allerr.append(e)
        print('  会话%d: 平均 %.0f px   中位 %.0f px   p10 %.0f   p90 %.0f'
              % (i + 1, e.mean(), np.median(e), np.percentile(e, 10), np.percentile(e, 90)))
    E = np.concatenate(allerr)
    diag = float(np.hypot(W, H))
    print('  合计: 平均 %.0f px (%.4f 对角线)   中位 %.0f px (%.4f)'
          % (E.mean(), E.mean() / diag, np.median(E), np.median(E) / diag))

    print('\n' + '=' * 84)
    print('【第二步】不同界面密度的吸附命中率')
    print('  假设：目标均匀铺满屏幕；预测点吸附到最近的按钮；')
    print('        吸附半径 = 按钮对角线的一半（超出即视为未命中，不点击）')
    print('=' * 84)
    print('%-14s %-10s %-12s %-12s %-12s %s'
          % ('布局', '按钮数', '按钮间距px', '吸附命中率', '邻格误选率', '可用性'))
    print('-' * 84)

    # 真实目标点只覆盖 4x3 网格，所以"布局"指把预测吸附到该布局的最近按钮，
    # 而"正确答案"是离真实目标最近的那个按钮。
    for cols, rows, name in [(1, 2, '1x2'), (2, 1, '2x1'), (2, 2, '2x2'),
                             (3, 2, '3x2'), (3, 3, '3x3'), (4, 3, '4x3'),
                             (4, 4, '4x4'), (5, 3, '5x3'), (5, 4, '5x4'), (6, 4, '6x4')]:
        centers = layout_centers(W, H, cols, rows)
        # 按钮间距（取横纵间距的较小者）
        dx = (W * 0.8) / max(cols - 1, 1) if cols > 1 else W
        dy = (H * 0.8) / max(rows - 1, 1) if rows > 1 else H
        spacing = min(dx, dy)
        hit_r = np.hypot(dx, dy) / 2          # 吸附半径
        hit, neighbor, miss = 0, 0, 0
        total = 0
        for F, tx, ty, tr in data:
            pred = oof(F, tx, ty, tr)
            for j in range(len(tx)):
                if not np.isfinite(pred[j, 0]):
                    continue
                total += 1
                # 预测点最近的按钮
                d = np.linalg.norm(centers - pred[j], axis=1)
                pi = int(np.argmin(d))
                if d[pi] > hit_r:
                    miss += 1
                    continue
                # 正确答案：离真实目标最近的按钮
                dt = np.linalg.norm(centers - np.array([tx[j], ty[j]]), axis=1)
                ti = int(np.argmin(dt))
                if pi == ti:
                    hit += 1
                else:
                    # 判定是否相邻格
                    pr, pc = pi // cols, pi % cols
                    tr_, tc = ti // cols, ti % cols
                    if abs(pr - tr_) <= 1 and abs(pc - tc) <= 1:
                        neighbor += 1
                    else:
                        miss += 1
        acc = hit / max(total, 1)
        nb = neighbor / max(total, 1)
        ms = miss / max(total, 1)
        usable = ('✓ 可用' if acc >= 0.90 and nb <= 0.05 else
                  ('△ 勉强' if acc >= 0.75 else '✗ 不可用'))
        print('%-14s %-10d %-12.0f %-12.1f%% %-12.1f%% %s'
              % (name, cols * rows, spacing, 100 * acc, 100 * nb, usable))

    print('\n' + '=' * 84)
    print('【第三步】结论：精度 → 界面密度的换算表')
    print('=' * 84)
    print('  我们的精度：平均误差 %.0f px = %.3f 屏幕对角线，中位 %.0f px'
          % (E.mean(), E.mean() / diag, np.median(E)))
    print('  因此按钮尺寸必须达到误差量级才可靠：')
    for frac in (0.20, 0.25, 0.30, 0.40, 0.50):
        size = frac * diag
        maxcols = max(1, int(W * 0.8 / size))
        maxrows = max(1, int(H * 0.8 / size))
        print('    按钮直径 %.2f 对角线 (%.0f px) → 最多约 %d x %d = %d 个'
              % (frac, size, maxcols, maxrows, maxcols * maxrows))
    print('\n  这与 README 里那张"命中半径→误触发率"表是同一个结论的不同表述：')
    print('  精度决定了界面密度的上限，而不是交互策略或滤波方法。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
