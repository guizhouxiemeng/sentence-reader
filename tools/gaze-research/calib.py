#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
calib.py — 验证"用采集时那 12 个点自己拟合系数"能做到多好

这是第 3 周"个人校准"的核心实验，提前在第 1 周做掉，因为它决定了
固定系数方案是否还有存在价值。

协议：留一目标点交叉验证（leave-one-grid-point-out）
  · 4x3 网格共 12 个目标位置
  · 每次留出 1 个目标位置的全部帧做测试，用其余 11 个位置的帧拟合
  · 只用 gaze_x/gaze_y 两维，线性映射（4 参数/轴 = 平移+缩放）
  · 另外测二次多项式版本（看非线性是否值得）

用法： python tools/calib.py a.csv [b.csv ...]
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


def design_lin(gx, gy):
    return np.column_stack([gx, gy, np.ones(len(gx))])


def design_quad(gx, gy):
    return np.column_stack([gx, gy, gx * gx, gy * gy, gx * gy, np.ones(len(gx))])


def logo(gx, gy, tx, ty, design, min_test_pts=1):
    """留一目标位置交叉验证。返回每帧误差数组。"""
    # 把目标位置离散化（四舍五入到 20px），避免抖动造成同一格被拆开
    key = np.round(tx / 20).astype(int) * 10000 + np.round(ty / 20).astype(int)
    uniq = np.unique(key)
    err = np.full(len(tx), np.nan)
    for k in uniq:
        te = key == k
        tr = ~te
        if te.sum() < min_test_pts or tr.sum() < 12:
            continue
        A = design(gx[tr], gy[tr])
        coef, *_ = np.linalg.lstsq(A, np.column_stack([tx[tr], ty[tr]]), rcond=None)
        P = design(gx[te], gy[te]) @ coef
        err[te] = np.hypot(P[:, 0] - tx[te], P[:, 1] - ty[te])
    return err, len(uniq)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()

    print('=' * 78)
    print('留一目标位置交叉验证：每留出一个点，用其余 11 个点拟合' )
    print('%-26s %10s %12s %12s %12s' % ('文件', '目标位置数', '线性(px)', '二次(px)', '线性/对角线'))
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); continue
        gx, gy, tx, ty = load(f)
        W = (tx.max() - tx.min()) / 0.84
        H = (ty.max() - ty.min()) / 0.84
        diag = float(np.hypot(W, H))
        e1, n1 = logo(gx, gy, tx, ty, design_lin)
        e2, _ = logo(gx, gy, tx, ty, design_quad)
        m1 = np.nanmean(e1)
        m2 = np.nanmean(e2)
        print('%-26s %10d %12.1f %12.1f %12.4f'
              % (os.path.basename(f), n1, m1, m2, m1 / diag))
        # 与"不校准"对比
        print('%-26s %10s %12s %12s %12s'
              % ('', '', '(中位 %.0f)' % np.nanmedian(e1), '', ''))

    print('\n参照：')
    print('   · 上一轮固定系数几何基线 = 0.3105 对角线')
    print('   · 39 维线性模型（按试次4折CV，旧数据） = 0.1531 对角线')
    print('   · 随机猜 = 约 0.36 对角线')
    print('\n解读：')
    print('   若"线性"一列显著低于 0.15，说明只要每次采集重新拟合 12 个点，')
    print('   连最简单的模型都能打败全局固定系数 —— 校准本身就是最大的收益来源。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
