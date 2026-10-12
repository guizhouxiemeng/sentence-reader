#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cross_session.py — 跨会话可迁移性实验（这是第 3 周的核心问题，提前验证）

三种工况：
  A. 什么都不做：用会话1拟合的系数直接套到会话2（离线迁移）
  B. 快速校准：用会话2的前 K 个目标位置重新拟合，在其余点上评估
  C. 会话内上限：同一会话内按点交叉验证（理想情况）

问题：花 K 个校准点，能把跨会话误差救回到什么程度？
用法： python tools/cross_session.py train.csv test.csv
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


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / col('iod')
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / col('iod')
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    return gx, gy, tx, ty


def key_of(tx, ty, q=20):
    return np.round(tx / q).astype(int) * 100000 + np.round(ty / q).astype(int)


def fit(gx, gy, tx, ty, ridge=0.0):
    """带可选岭正则的最小二乘。
    为什么需要：只用 K 个目标位置拟合 3 个参数（每轴）时，K 小时是欠定问题，
    普通 lstsq 会给出数值爆炸的解（实测 K=1,2 时误差反而比不校准更差）。
    ridge 让解偏向"小而稳"，这才是快速校准的正确做法。"""
    A = np.column_stack([gx, gy, np.ones(len(gx))])
    if ridge <= 0:
        coef, *_ = np.linalg.lstsq(A, np.column_stack([tx, ty]), rcond=None)
        return coef
    # 不惩罚截距项
    R = np.diag([ridge, ridge, 0.0])
    AtA = A.T @ A + R
    coef = np.linalg.solve(AtA, A.T @ np.column_stack([tx, ty]))
    return coef


def pred(coef, gx, gy):
    return np.column_stack([gx, gy, np.ones(len(gx))]) @ coef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('train_csv')
    ap.add_argument('test_csv')
    args = ap.parse_args()

    gx1, gy1, tx1, ty1 = load(args.train_csv)
    gx2, gy2, tx2, ty2 = load(args.test_csv)
    W = (tx1.max() - tx1.min()) / 0.84
    H = (ty1.max() - ty1.min()) / 0.84
    diag = float(np.hypot(W, H))
    print('训练会话: %s' % os.path.basename(args.train_csv))
    print('测试会话: %s' % os.path.basename(args.test_csv))
    print('对角线: %.0f px' % diag)

    # --- A: 离线迁移 ---
    coef1 = fit(gx1, gy1, tx1, ty1)
    eA = np.linalg.norm(pred(coef1, gx2, gy2) - np.column_stack([tx2, ty2]), axis=1)
    print('\n【A】直接迁移（0 个校准点）        : %6.1f px   %.4f 对角线' % (eA.mean(), eA.mean() / diag))

    # --- A2: 迁移 + 平移补偿（用测试会话全体均值，仅作诊断）---
    coef1b = coef1.copy()
    err_vec = pred(coef1, gx2, gy2) - np.column_stack([tx2, ty2])
    print('     迁移后的系统偏差: dx=%+.1f  dy=%+.1f px' % (err_vec[:, 0].mean(), err_vec[:, 1].mean()))

    # --- B: 快速校准 K 个点 ---
    kes = key_of(tx2, ty2)
    uniq2 = np.unique(kes)
    print('\n【B】用测试会话的前 K 个目标位置重新校准（带岭正则），在其余点上评估')
    print('   %6s %12s %12s %12s' % ('K', '无正则', '有正则', '/对角线'))
    rng = np.random.default_rng(0)
    for K in [1, 2, 3, 5, 8]:
        if K >= len(uniq2):
            continue
        for ridge in [0.0, 1e-4]:
            trials = []
            for rep in range(20):
                perm = rng.permutation(uniq2)
                cal = set(perm[:K].tolist())
                m_cal = np.isin(kes, list(cal))
                m_te = ~m_cal
                if m_cal.sum() < 5 or m_te.sum() < 10:
                    continue
                cf = fit(gx2[m_cal], gy2[m_cal], tx2[m_cal], ty2[m_cal], ridge=ridge)
                e = np.linalg.norm(pred(cf, gx2[m_te], gy2[m_te]) - np.column_stack([tx2, ty2])[m_te], axis=1)
                trials.append(e.mean())
            if ridge == 0.0:
                plain = np.mean(trials) if trials else float('nan')
            else:
                reg = np.mean(trials) if trials else float('nan')
                print('   %6d %12.1f %12.1f %12.4f' % (K, plain, reg, reg / diag))

    # --- C: 会话内上限（留一点交叉验证）---
    errs = []
    for i, k in enumerate(uniq2):
        te = kes == k
        tr = ~te
        if te.sum() < 10 or tr.sum() < 50:
            continue
        cf = fit(gx2[tr], gy2[tr], tx2[tr], ty2[tr])
        errs.append(np.linalg.norm(pred(cf, gx2[te], gy2[te]) - np.column_stack([tx2, ty2])[te], axis=1).mean())
    print('\n【C】会话内留一点交叉验证（理想上限）  : %6.1f px   %.4f 对角线'
          % (np.mean(errs), np.mean(errs) / diag))

    print('\n解读：若 B 在 K=5 时接近 C，说明"每次坐下花 5 个点校准"就能解决跨会话退化，')
    print('      这是可以写进简历的实用性结论；若 B 远差于 C，说明特征本身不稳定。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
