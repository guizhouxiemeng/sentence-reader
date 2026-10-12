#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_cross.py — 测试用户提出的"十字校准"方案

用户的两个现场观察：
  1. 光标只能在上半部分动，到不了下半部分  → 垂直映射范围不足
  2. 离摄像头距离变化时小球向上飞出        → iod（瞳距）被带进了映射

用户的建议：改成"随视线在屏幕中间划十字"的校准布局。

本脚本对比三种校准布局在真实数据上的表现：
  A. 4x3 网格（12 点，当前 demo 用的）
  B. 十字（中心 + 上下左右臂，覆盖垂直与水平的完整范围）
  C. 五点（中心 + 四角）

并同时对比特征组合：
  · 含 iod
  · 不含 iod（iod 会随人脸距离变化，若它进入映射，人一靠近光标就会漂）

判据：
  · 留一误差（越小越好）
  · 垂直预测跨度 / 垂直目标跨度（接近 1 说明垂直幅度正确，< 1 就是"到不了下半部分"）
  · 人脸距离敏感度：把 iod 整体偏移 10% 后预测点移动多少像素

用法： python tools/test_cross.py
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
    X = np.column_stack([iry, irx, gx, gx * gx, iry * iry,
                         col('L_h'), col('L_h2'), col('R_h'), col('R_h2'), iod])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    return X, tx, ty


def layouts(W, H):
    ix, iy = W * INSET, H * INSET
    sx, sy = W - 2 * ix, H - 2 * iy
    grid = [(ix + sx * cc / 3, iy + sy * rr / 2) for rr in range(3) for cc in range(4)]
    cx, cy = W / 2, H / 2
    cross = [(cx, cy), (cx, iy), (cx, H - iy), (ix, cy), (W - ix, cy)]
    five = [(cx, cy), (ix, iy), (W - ix, iy), (ix, H - iy), (W - ix, H - iy)]
    return {'4x3网格(12点)': grid, '十字(5点)': cross, '五点(中心+四角)': five}


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else abs(v)


def ridge(Z, y, lam):
    A = np.column_stack([Z, np.ones(len(Z))])
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def run(X, tx, ty, pts, dims, lam, use_iod=True):
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    # 把每帧归到最近的校准点
    assign = np.array([int(np.argmin([(tx[i]-p[0])**2 + (ty[i]-p[1])**2 for p in pts]))
                       for i in range(len(tx))])
    # 选特征（可按需剔除 iod，它是第 10 维即索引 9）
    cols = list(range(X.shape[1]))
    if not use_iod and 9 in cols:
        cols.remove(9)
    Xs = X[:, cols]
    order = list(np.argsort(-np.array([max(corr(Xs[:, i], tx), corr(Xs[:, i], ty))
                                       for i in range(Xs.shape[1])]))[:dims])
    Xs = Xs[:, order]
    mu, sd = Xs.mean(0), Xs.std(0) + 1e-9
    Z = (Xs - mu) / sd

    errs = []
    for k in np.unique(assign):
        te = assign == k
        tr = ~te
        if te.sum() < 5 or tr.sum() < 50:
            continue
        bx = ridge(Z[tr], tx[tr], lam); by = ridge(Z[tr], ty[tr], lam)
        if bx is None or by is None:
            continue
        A = np.column_stack([Z[te], np.ones(te.sum())])
        p = np.column_stack([A @ bx, A @ by])
        errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
    if not errs:
        return None
    # 全量拟合：看预测跨度与"人脸距离敏感度"
    bx = ridge(Z, tx, lam); by = ridge(Z, ty, lam)
    A = np.column_stack([Z, np.ones(len(Z))])
    p = np.column_stack([A @ bx, A @ by])
    span_ratio_y = (p[:, 1].max() - p[:, 1].min()) / (ty.max() - ty.min())
    span_ratio_x = (p[:, 0].max() - p[:, 0].min()) / (tx.max() - tx.min())
    # 人脸距离敏感度：iod 对应维整体 +10%
    iod_idx = None
    for j, i in enumerate(order):
        if cols[i] == 9:
            iod_idx = j
    dist_sens = 0.0
    if iod_idx is not None:
        # 设计向量长度 = dims + 1（含截距）
        z0 = np.zeros(len(order) + 1)
        z1 = np.zeros(len(order) + 1)
        z1[iod_idx] = 0.6          # 约 10% 的标准化偏移
        p0 = np.array([float(z0 @ bx), float(z0 @ by)])
        p1 = np.array([float(z1 @ bx), float(z1 @ by)])
        dist_sens = float(np.linalg.norm(p1 - p0))
    return dict(err=np.mean(errs), span_x=span_ratio_x, span_y=span_ratio_y,
                dist_sens=dist_sens, n_pts=len(np.unique(assign)))


def main():
    data = []
    for fn in FILES:
        if os.path.exists(os.path.join(ROOT, fn)):
            data.append(load(fn))
    print('载入 %d 会话\n' % len(data))
    # 用第一个会话的尺⼨定义布局
    X0, tx0, ty0 = data[0]
    W = (tx0.max() - tx0.min()) / (1 - 2 * INSET)
    H = (ty0.max() - ty0.min()) / (1 - 2 * INSET)
    L = layouts(W, H)

    print('%-18s %-6s %-8s %-10s %-10s %-10s %s'
          % ('布局', '维度', '用iod', '留一误差px', '水平跨度比', '垂直跨度比', '距离敏感度px'))
    print('-' * 92)
    for name, pts in L.items():
        for dims in (3, 4, 6):
            for use_iod in (True, False):
                rows = []
                for X, tx, ty in data:
                    r = run(X, tx, ty, pts, dims, 1000.0, use_iod)
                    if r:
                        rows.append(r)
                if not rows:
                    continue
                e = np.mean([r['err'] for r in rows])
                sx = np.mean([r['span_x'] for r in rows])
                sy = np.mean([r['span_y'] for r in rows])
                ds = np.mean([r['dist_sens'] for r in rows])
                flag = ''
                if sy < 0.75:
                    flag += '  ← 垂直幅度不足'
                if ds > 200:
                    flag += '  ← 对人脸距离敏感'
                print('%-18s %-6d %-8s %-10.0f %-10.2f %-10.2f %.0f%s'
                      % (name, dims, '是' if use_iod else '否', e, sx, sy, ds, flag))
    print('\n判据：')
    print('  · 垂直跨度比 = 预测点垂直跨度 / 目标点垂直跨度。接近 1 才对；')
    print('    < 0.75 就是用户说的"到不了下半部分"。')
    print('  · 距离敏感度 = 瞳距整体偏 10% 时预测点移动的像素数。')
    print('    它大说明"人一靠近/远离光标就漂" —— 这正是用户观察到的现象。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
