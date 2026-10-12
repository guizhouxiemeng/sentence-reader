#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
audit_calib.py — 逐行复刻 demo 的 JS 校准算法，判断"算法错"还是"实现错"

背景：demo 的校准回归在现场选不中目标（连单个大目标都不行）。为区分
  · 算法本身不成立（最小二乘映射不足以表达眼动→屏幕）
  · JS 实现有 bug（矩阵求解、索引、特征顺序）
这个脚本用 Python 精确复刻同一套逻辑并报告中间量。

复刻的 JS 步骤（demo/index.html）：
  1. buildFeatures：14 维（gaze_x/y 及其二次项 + 5 个相对眼角量 + iod）
  2. pickTopFeats：按 |corr(feat, target_x)| 与 |corr(feat, target_y)| 的
     较大者排序，取前 CALIB_FEATS 个
  3. fitCalibration：岭回归（λ=0.01，截距不惩罚），逐轴求解
  4. 留一目标位置交叉验证 → cvErr
  5. 用 12 个 4x3 网格点做校准，预测留出点

用法： python tools/audit_calib.py gaze_p411900_frames.csv
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

CALIB_FEATS = 8
CALIB_LAMBDA = 0.01
COLS, ROWS, INSET = 4, 3, 0.08

FEAT_NAMES = ['gaze_x','gaze_y','gaze_x2','gaze_y2','gaze_xy',
              'L_h','L_v','L_h2','L_v2','R_h','R_v','R_h2','R_v2','iod']


def build_features(rows, c):
    """与 demo 的 buildFeatures 完全一致（14 维）。"""
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in rows])
    iod = col('iod') + 1e-9
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    ecx, ecy = col('eyecenter_x'), col('eyecenter_y')
    gx = (irx - ecx) / iod
    gy = (iry - ecy) / iod
    return np.column_stack([
        gx, gy, gx * gx, gy * gy, gx * gy,
        col('L_h'), col('L_v'), col('L_h2'), col('L_v2'),
        col('R_h'), col('R_v'), col('R_h2'), col('R_v2'), col('iod'),
    ])


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else abs(v)


def pick_top_feats(X, px, py, k=CALIB_FEATS):
    score = [max(corr(X[:, i], px), corr(X[:, i], py)) for i in range(X.shape[1])]
    return list(np.argsort(-np.array(score))[:k])


def ridge_fit(X, y, lam=CALIB_LAMBDA):
    """与 demo 的 ridgeFit 同一数学： (X'X + λI) β = X'y，截距不惩罚。"""
    A = np.column_stack([X, np.ones(len(X))])
    d = A.shape[1]
    G = A.T @ A
    R = np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G + R, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def predict(f, idx, bx, by):
    v = np.array([f[i] for i in idx] + [1.0])
    return float(v @ bx), float(v @ by)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    args = ap.parse_args()
    if not os.path.exists(args.csv):
        print('找不到:', args.csv)
        return 1

    with open(args.csv, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    X = build_features(d, c)
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    diag = float(np.hypot(W, H))
    print('数据: %d 帧  推断视口 %.0f x %.0f  对角线 %.0f' % (len(X), W, H, diag))

    # ---- 校准点：与 demo 相同的 4x3 网格（按视口尺寸生成，再匹配最近的实测目标）----
    grid = []
    for r in range(ROWS):
        for cc in range(COLS):
            grid.append((W * INSET + (W - 2 * W * INSET) * cc / (COLS - 1),
                         H * INSET + (H - 2 * H * INSET) * r / (ROWS - 1)))
    # 把每个实测帧归到最近的网格点
    assign = []
    for i in range(len(tx)):
        best, bd = 0, 1e18
        for j, (gx_, gy_) in enumerate(grid):
            dd = (tx[i] - gx_) ** 2 + (ty[i] - gy_) ** 2
            if dd < bd:
                bd, best = dd, j
        assign.append(best)
    assign = np.array(assign)
    present = np.unique(assign)
    print('校准网格点 %d 个，本数据覆盖 %d 个' % (len(grid), len(present)))

    # ---- 复刻 fitCalibration ----
    idx = pick_top_feats(X, tx, ty)
    print('选中特征: %s' % [FEAT_NAMES[i] for i in idx])
    bx = ridge_fit(X[:, idx], tx)
    by = ridge_fit(X[:, idx], ty)
    if bx is None or by is None:
        print('✗ 岭回归求解失败（矩阵奇异）—— 这就是 JS 端可能的故障点')
        return 1

    pred = np.column_stack([np.column_stack([X[:, idx], np.ones(len(X))]) @ bx,
                            np.column_stack([X[:, idx], np.ones(len(X))]) @ by])
    err = np.linalg.norm(pred - np.column_stack([tx, ty]), axis=1)
    print('\n全量拟合误差: %.0f px (%.4f 对角线)  ← 这是"自拟合"，必然乐观' % (err.mean(), err.mean() / diag))

    # ---- 预测是否随注视变化？（关键：查"光标不动"）----
    print('\n预测点动态范围（判断模型是否在响应注视）：')
    print('  目标 x 范围: %.0f .. %.0f  (跨度 %.0f)' % (tx.min(), tx.max(), tx.max() - tx.min()))
    print('  预测 x 范围: %.0f .. %.0f  (跨度 %.0f)' % (pred[:, 0].min(), pred[:, 0].max(), pred[:, 0].max() - pred[:, 0].min()))
    print('  目标 y 范围: %.0f .. %.0f  (跨度 %.0f)' % (ty.min(), ty.max(), ty.max() - ty.min()))
    print('  预测 y 范围: %.0f .. %.0f  (跨度 %.0f)' % (pred[:, 1].min(), pred[:, 1].max(), pred[:, 1].max() - pred[:, 1].min()))
    rx = np.corrcoef(pred[:, 0], tx)[0, 1]
    ry = np.corrcoef(pred[:, 1], ty)[0, 1]
    print('  r(预测x, 目标x) = %+.3f    r(预测y, 目标y) = %+.3f' % (rx, ry))

    # ---- 留一网格点交叉验证 ----
    errs = []
    for k in present:
        te = assign == k
        tr = ~te
        if te.sum() < 5 or tr.sum() < 50:
            continue
        idx2 = pick_top_feats(X[tr], tx[tr], ty[tr])
        cx = ridge_fit(X[tr][:, idx2], tx[tr])
        cy = ridge_fit(X[tr][:, idx2], ty[tr])
        if cx is None or cy is None:
            continue
        for i in np.where(te)[0]:
            px_, py_ = predict(X[i], idx2, cx, cy)
            errs.append(np.hypot(px_ - tx[i], py_ - ty[i]))
    errs = np.array(errs)
    print('\n留一网格点交叉验证: %.0f px (%.4f 对角线)  中位 %.0f px'
          % (errs.mean(), errs.mean() / diag, np.median(errs)))

    # ---- 单目标可用性判断 ----
    print('\n单目标可用性：若只有一个目标，命中半径需要多大？')
    for frac in (0.15, 0.20, 0.30, 0.40, 0.50):
        r = frac * diag
        print('  半径 %.2f 对角线 = %4.0f px → 落在半径内的帧占比 %5.1f%%'
              % (frac, r, 100 * (errs < r).mean()))
    print('\n结论判据：')
    print('  · 若"预测跨度"远小于"目标跨度" → 回归在收缩，预测被拉向均值（光标不动）')
    print('  · 若 r(预测,目标) 高但误差大 → 映射方向对，只是精度不足')
    return 0


if __name__ == '__main__':
    sys.exit(main())
