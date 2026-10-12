#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_star.py — 对比"米字"与其它校准布局

用户提议：画米字（中心 + 上、下、左、右、四个斜向，共 9 点）。

这是一次干净的布局对比。之前测过：
    4x3 网格(12点)  垂直跨度比 0.70  留一误差 450px
    十字(5点)       垂直跨度比 0.70  留一误差 541px
    五点(中心+四角)  垂直跨度比 0.70  留一误差 510px
点数多的占优。米字 9 点介于两者之间，需要实测。

同时比较"米字 9 点"与"米字去掉斜向 = 十字 5 点"，
以判断斜向点是否真带来额外信息（对角线方向能约束两个轴同时变化）。

用法： python tools/test_star.py
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
    # 与 demo 的 9 维特征一致，且不含 iod
    X = np.column_stack([iry, irx, gx, gx * gx, iry * iry,
                         col('L_h'), col('L_h2'), col('R_h'), col('R_h2')])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    return X, tx, ty


def make_layouts(W, H):
    ix, iy = W * INSET, H * INSET
    sx, sy = W - 2 * ix, H - 2 * iy
    cx, cy = W / 2, H / 2
    L = {}
    # 米字 9 点：中心 + 四正 + 四斜
    L['米字(9点)'] = [(cx, cy),
                     (cx, iy), (cx, H - iy), (ix, cy), (W - ix, cy),
                     (ix, iy), (W - ix, iy), (ix, H - iy), (W - ix, H - iy)]
    # 只有四正，无斜向（= 十字 5 点）
    L['十字(5点)'] = [(cx, cy), (cx, iy), (cx, H - iy), (ix, cy), (W - ix, cy)]
    # 3x3 网格 9 点（与米字点数相同，但只覆盖 3 列 3 行）
    L['3x3网格(9点)'] = [(ix + sx * a / 2, iy + sy * b / 2)
                        for b in range(3) for a in range(3)]
    # 3x4 网格 12 点（竖排多点，强化垂直）
    L['3列x4行(12点)'] = [(ix + sx * a / 2, iy + sy * b / 3)
                        for b in range(4) for a in range(3)]
    # 4x3 网格 12 点（当前 demo 用的）
    L['4列x3行(12点)'] = [(ix + sx * a / 3, iy + sy * b / 2)
                        for b in range(3) for a in range(4)]
    return L


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


def run(X, tx, ty, pts, dims=6, lam=1000.0):
    assign = np.array([int(np.argmin([(tx[i]-p[0])**2 + (ty[i]-p[1])**2 for p in pts]))
                       for i in range(len(tx))])
    order = list(np.argsort(-np.array([max(corr(X[:, i], tx), corr(X[:, i], ty))
                                       for i in range(X.shape[1])]))[:dims])
    Xs = X[:, order]
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
    bx = ridge(Z, tx, lam); by = ridge(Z, ty, lam)
    A = np.column_stack([Z, np.ones(len(Z))])
    p = np.column_stack([A @ bx, A @ by])
    return dict(err=np.mean(errs), n=len(np.unique(assign)),
                sx=(p[:, 0].max() - p[:, 0].min()) / (tx.max() - tx.min()),
                sy=(p[:, 1].max() - p[:, 1].min()) / (ty.max() - ty.min()))


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    X0, tx0, ty0 = data[0]
    W = (tx0.max() - tx0.min()) / (1 - 2 * INSET)
    H = (ty0.max() - ty0.min()) / (1 - 2 * INSET)
    L = make_layouts(W, H)
    print('载入 %d 会话   视口 %.0fx%.0f\n' % (len(data), W, H))
    print('%-18s %-7s %-11s %-11s %-11s %s' % ('布局', '实际点数', '留一误差px', '水平跨度比', '垂直跨度比', '校准耗时(按2.5s/点)'))
    print('-' * 88)
    res = []
    for name, pts in L.items():
        rows = [run(X, tx, ty, pts) for X, tx, ty in data]
        rows = [r for r in rows if r]
        if not rows:
            continue
        e = np.mean([r['err'] for r in rows])
        sx = np.mean([r['sx'] for r in rows])
        sy = np.mean([r['sy'] for r in rows])
        n = rows[0]['n']
        cost = len(pts) * 2.5
        res.append((e, name, n, sx, sy, cost))
        print('%-18s %-7d %-11.0f %-11.2f %-11.2f %.0f 秒' % (name, n, e, sx, sy, cost))
    res.sort()
    print('\n按留一误差排序：')
    for e, name, n, sx, sy, cost in res:
        print('   %-18s %.0f px  垂直跨度 %.2f  耗时 %.0f 秒' % (name, e, sy, cost))
    print('\n判据：')
    print('  · 留一误差越小越好；垂直跨度比越接近 1，"到不了下半部分"越轻微。')
    print('  · 同时要考虑校准耗时 —— 点数越多越准，但使用者越容易在中途头动。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
