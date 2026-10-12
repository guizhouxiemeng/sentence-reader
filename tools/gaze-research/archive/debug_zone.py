#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
debug_zone.py — 诊断区域分类器在理想信号下为何只有 56%

无头验证发现：合成一个"gx 与屏幕 x 单调、iry 与屏幕 y 单调"的理想视线信号，
4x4=16 区域的 one-vs-rest 线性分类器自检准确率只有 56.3%。
理想情况下这种单调信号应该接近 100%。

需要查明是：
  A. 分类器实现有 bug（数值问题）
  B. 16 区域对线性分类器而言本身就难（区域太多）
  C. 我的合成信号设计有问题

做法：在 Python 里用同样的合成信号，分别测
  · 理想 (gx, iry) 直接分类
  · 加二次项后的分类
  · 不同区域数（2x2 / 3x3 / 4x4）的准确率
并按单个轴分析（x 分 4 段、y 分 4 段）。

用法： python tools/debug_zone.py
"""
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

W, H = 1920.0, 1080.0
rng = np.random.default_rng(7)


def synth(ncols, nrows, n_per=20, nz=0.01):
    """构造理想视线特征：gx 随屏幕 x 单调，iry 随屏幕 y 单调。"""
    F, lab = [], []
    for u in range(ncols):
        for v in range(nrows):
            px = (u + 0.5) / ncols * W
            py = (v + 0.5) / nrows * H
            for _ in range(n_per):
                gx = -0.05 + 0.10 * (px / W) + rng.normal(0, nz)
                iry = 0.74 + 0.03 * (py / H) + rng.normal(0, nz)
                irx = 0.5 + rng.normal(0, nz)
                F.append([iry, irx, gx, gx * gx, iry * iry, gx * 0.5, gx * 0.5])
                lab.append(v * ncols + u)
    return np.array(F), np.array(lab), ncols, nrows


def ridge(A, y, lam=10.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def fit_eval(F, lab, nz):
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
    B = []
    for lv in range(nz):
        b = ridge(Z, (lab == lv).astype(float))
        if b is None:
            return None
        B.append(b)
    B = np.array(B)
    scores = Z @ B.T
    pred = np.argmax(scores, axis=1)
    return (pred == lab).mean(), pred


def main():
    print('=' * 78)
    print('区域分类器诊断：理想信号下的准确率')
    print('=' * 78)
    print('%-10s %-16s %-16s %s' % ('区域网格', '特征集', '自检准确率', '说明'))
    print('-' * 78)

    for (nc, nr) in [(2, 2), (3, 3), (4, 4), (2, 4), (4, 2)]:
        F, lab, ncols, nrows = synth(nc, nr)
        nz = nc * nr
        # 完整特征集（与 demo 一致）
        acc_full, _ = fit_eval(F, lab, nz)
        # 只用 (gx, iry) 两个最有信息的量
        acc_min, _ = fit_eval(F[:, [0, 2]], lab, nz)
        print('%-10s %-16s %-16.1f%% %s'
              % ('%dx%d' % (nc, nr), '完整 7 维', acc_full * 100, ''))
        print('%-10s %-16s %-16.1f%% %s'
              % ('', '仅 (iry,gx)', acc_min * 100, ''))
        if acc_full < 0.95:
            # 单轴准确率，判断是哪个轴拖累
            ux = (lab % nc)
            uy = (lab // nc)
            # 用 gx 单轴预测 x 段
            gx = F[:, 2]
            pred_ux = np.clip(((gx + 0.05) / 0.10 * nc).astype(int), 0, nc - 1)
            acc_ux = (pred_ux == ux).mean()
            iry = F[:, 0]
            pred_uy = np.clip(((iry - 0.74) / 0.03 * nr).astype(int), 0, nr - 1)
            acc_uy = (pred_uy == uy).mean()
            print('%-10s %-16s %-16s gx 定 x 段 %.1f%% / iry 定 y 段 %.1f%%'
                  % ('', '', '', acc_ux * 100, acc_uy * 100))

    print('\n' + '=' * 78)
    print('结论')
    print('=' * 78)
    print('  若"仅 (iry,gx)"的准确率显著高于"完整 7 维"，说明多余特征在稀释信号')
    print('  （岭正则 λ=10 把噪声维度的系数压小，但也可能压掉有效维度的贡献）。')
    print('  若单轴准确率都接近 100% 而联合准确率低，说明 one-vs-rest 的'
          '线性决策边界在二维网格上确实不够（区域数越多越明显）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
