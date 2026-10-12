#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
find_stable_calib.py — 为 demo 校准找一组"数值稳定"的参数

背景：现场诊断显示 |bx| 达到 1.42e6，而特征是 1e-3 量级。
只要现场特征稍偏离校准范围，Σβ·x 就溢出成 Infinity，
1€ filter 存下 Infinity 后做 Infinity-Infinity → NaN，光标永久不动。
同时 cvErr 高达 4236px，说明这次校准本身也没拟合好。

稳定性与精度是两件事。这个脚本同时报告：
  · 留一校准误差（精度）
  · 系数最大绝对值 |β|max（稳定性：越小越安全）
  · 设计矩阵条件数

用法： python tools/find_stable_calib.py
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
COLS, ROWS, INSET = 4, 3, 0.08

FNAMES = ['gaze_x','gaze_y','gaze_x2','gaze_y2','gaze_xy',
          'L_h','L_v','L_h2','L_v2','R_h','R_v','R_h2','R_v2','iod']


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
    gx = (irx - col('eyecenter_x')) / iod
    gy = (iry - col('eyecenter_y')) / iod
    X = np.column_stack([gx, gy, gx*gx, gy*gy, gx*gy,
                         col('L_h'), col('L_v'), col('L_h2'), col('L_v2'),
                         col('R_h'), col('R_v'), col('R_h2'), col('R_v2'), col('iod')])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    return X, tx, ty


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else abs(v)


def ridge(Xs, y, lam):
    mu, sd = Xs.mean(0), Xs.std(0) + 1e-9
    A = np.column_stack([(Xs - mu) / sd, np.ones(len(Xs))])
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    bn = np.linalg.solve(G, A.T @ y)
    beta = np.zeros(d)
    inter = bn[-1]
    for j in range(d - 1):
        w = bn[j] / sd[j]
        beta[j] = w
        inter -= w * mu[j]
    beta[-1] = inter
    return beta


def evaluate(X, tx, ty, dims, lam, seed=0):
    """按 demo 的流程：4x3 网格校准 + 留一网格点评估。"""
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    diag = float(np.hypot(W, H))
    grid = [(W*INSET + (W-2*W*INSET)*cc/(COLS-1), H*INSET + (H-2*H*INSET)*r/(ROWS-1))
            for r in range(ROWS) for cc in range(COLS)]
    assign = np.array([int(np.argmin([(tx[i]-g[0])**2 + (ty[i]-g[1])**2 for g in grid]))
                       for i in range(len(tx))])
    rng = np.random.default_rng(seed)
    order = list(np.argsort(-np.array([max(corr(X[:, i], tx), corr(X[:, i], ty))
                                       for i in range(X.shape[1])]))[:dims])
    errs, betas = [], []
    for k in np.unique(assign):
        te = assign == k
        tr = ~te
        if te.sum() < 5 or tr.sum() < 50:
            continue
        bx = ridge(X[tr][:, order], tx[tr], lam)
        by = ridge(X[tr][:, order], ty[tr], lam)
        betas.extend(np.abs(bx).tolist()); betas.extend(np.abs(by).tolist())
        A = np.column_stack([X[te][:, order], np.ones(te.sum())])
        p = np.column_stack([A @ bx, A @ by])
        errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
    if not errs:
        return None
    # 全量拟合的系数（真正部署时用的是这套）
    bxf = ridge(X[:, order], tx, lam)
    byf = ridge(X[:, order], ty, lam)
    full_max = max(np.abs(bxf).max(), np.abs(byf).max())
    return dict(err=np.mean(errs), err_norm=np.mean(errs)/diag, diag=diag,
                beta_max=float(full_max), dims=dims, lam=lam,
                order=[FNAMES[i] for i in order])


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 个会话\n' % len(data))
    print('%-6s %-9s %-11s %-11s %s' % ('维度', 'lambda', '留一误差px', '误差/对角线', '|β|max'))
    print('-' * 62)
    results = []
    for dims in (3, 4, 5, 6, 8):
        for lam in (1e-2, 1e-1, 1.0, 10.0, 100.0):
            rows = []
            for X, tx, ty in data:
                r = evaluate(X, tx, ty, dims, lam)
                if r:
                    rows.append(r)
            if not rows:
                continue
            e = np.mean([r['err'] for r in rows])
            en = np.mean([r['err_norm'] for r in rows])
            bm = np.mean([r['beta_max'] for r in rows])
            results.append((dims, lam, e, en, bm))
            flag = ''
            if bm > 1e6:
                flag = '  ← 系数过大，有溢出风险'
            elif bm > 1e5:
                flag = '  ← 偏大'
            print('%-6d %-9g %-11.0f %-11.4f %.2e%s' % (dims, lam, e, en, bm, flag))

    ok = [r for r in results if r[4] < 1e5]
    if ok:
        ok.sort(key=lambda r: r[3])
        d, l, e, en, bm = ok[0]
        print('\n推荐（|β|max < 1e5 中误差最小）: 维度=%d  lambda=%g  →  %.0f px (%.4f 对角线), |β|max=%.2e'
              % (d, l, e, en, bm))
    else:
        print('\n没有 |β|max < 1e5 的组合 —— 说明该特征集本身不适合做线性映射')
    return 0


if __name__ == '__main__':
    sys.exit(main())
