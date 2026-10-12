#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tune_calib.py — 用真实数据搜索稳定且准确的校准配置

现场问题（用户实测）：
  · cvErr 1062px (0.548 对角线) —— 比随机猜(0.38)还差，校准崩了
  · 光标系统性偏左（要看右边才能到中间）
  · 光标乱动，但整体趋势正确
  · 标准化后 z 出现 1.70 / 1.34 / 1.23，说明现场特征超出校准覆盖范围

这个脚本搜索三个维度：
  · 特征维度数（3~8）
  · 岭系数（0.01~1000）
  · 是否对特征做"按校准点去重后的稳健拟合"

并对每个配置报告：留一误差、|β|max、以及"外推敏感度"——
即把输入特征整体偏移 1 个标准差时，预测点移动多少像素。
敏感度越小，现场抖动引起的乱飘越轻。

用法： python tools/tune_calib.py
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
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / iod
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / iod
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


def fit_std(Z, y, lam):
    """标准化空间已经由调用方做好，这里只做岭回归。"""
    A = np.column_stack([Z, np.ones(len(Z))])
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def run_config(data, dims, lam, evaluate_extrap=True):
    errs_all, beta_max_all, sens_all = [], [], []
    for X, tx, ty in data:
        W = (tx.max() - tx.min()) / (1 - 2 * INSET)
        H = (ty.max() - ty.min()) / (1 - 2 * INSET)
        grid = [(W*INSET + (W-2*W*INSET)*cc/(COLS-1), H*INSET + (H-2*H*INSET)*r/(ROWS-1))
                for r in range(ROWS) for cc in range(COLS)]
        assign = np.array([int(np.argmin([(tx[i]-g[0])**2 + (ty[i]-g[1])**2 for g in grid]))
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
            bx = fit_std(Z[tr], tx[tr], lam)
            by = fit_std(Z[tr], ty[tr], lam)
            if bx is None or by is None:
                continue
            A = np.column_stack([Z[te], np.ones(te.sum())])
            p = np.column_stack([A @ bx, A @ by])
            errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
        errs_all.append(np.mean(errs) if errs else 1e9)

        bxf = fit_std(Z, tx, lam)
        byf = fit_std(Z, ty, lam)
        if bxf is not None and byf is not None:
            beta_max_all.append(max(np.abs(bxf).max(), np.abs(byf).max()))
            if evaluate_extrap:
                # 外推敏感度：输入整体偏移 1 个标准差，预测点移动多少像素。
                # 用零向量与全 1 向量（标准化空间）的预测差衡量。
                z0 = np.concatenate([np.zeros(dims), [1.0]])
                z1 = np.concatenate([np.ones(dims), [1.0]])
                p0 = np.array([float(z0 @ bxf), float(z0 @ byf)])
                p1 = np.array([float(z1 @ bxf), float(z1 @ byf)])
                sens_all.append(float(np.linalg.norm(p1 - p0)))
    return (np.mean(errs_all), np.mean(beta_max_all) if beta_max_all else np.nan,
            np.mean(sens_all) if sens_all else np.nan)


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    diag = None
    for X, tx, ty in data:
        W = (tx.max() - tx.min()) / (1 - 2 * INSET)
        H = (ty.max() - ty.min()) / (1 - 2 * INSET)
        diag = float(np.hypot(W, H))
        break
    print('载入 %d 会话   参考对角线 %.0f px\n' % (len(data), diag))
    print('%-5s %-8s %-10s %-11s %-11s %s' % ('维度', 'lambda', '留一误差px', '误差/对角线', '|β|max', '外推敏感度px'))
    print('-' * 74)
    rows = []
    for dims in (3, 4, 5, 6, 8):
        for lam in (0.1, 1, 10, 100, 1000):
            e, bm, sens = run_config(data, dims, lam)
            rows.append((e, dims, lam, bm, sens))
            print('%-5d %-8g %-10.0f %-11.4f %-11.2e %.0f' % (dims, lam, e, e / diag, bm, sens))
    print('\n按留一误差排序（前 5）:')
    for e, dims, lam, bm, sens in sorted(rows)[:5]:
        print('   维度=%d lambda=%-6g 误差 %.0f px (%.4f)  |β|max=%.1e  外推敏感度 %.0f px'
              % (dims, lam, e, e / diag, bm, sens))
    print('\n判据：外推敏感度 = 输入特征整体偏移 1 个标准差时预测点移动的像素数。')
    print('      它应远小于目标半径（约 300px），否则现场抖动就会让光标乱飘。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
