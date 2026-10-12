#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_coordsys.py — 验证"改用左下角为原点的直角坐标系"对精度的影响

用户的提议：先读取屏幕分辨率，再以左下角为原点建立直角坐标系来定位。

需要区分两件事：

  ① 坐标系的选择（原点在哪、y 轴朝上还是朝下、单位是什么）
     —— 这是【仿射变换】。而我们的回归模型本身就是"特征的仿射函数 + 岭正则"，
        变换后的坐标会被回归的截距与系数完全吸收。所以精度【理论上完全不变】。
        本脚本用真实数据实测验证这一点。

  ② 屏幕分辨率/缩放是否正确读取
     —— 这是【真问题】。CSS 像素 ≠ 物理像素：本项目实测 dpr=1.5（150% 缩放），
        如果按 CSS 尺寸生成目标点却按物理像素换算，会引入约 10% 的尺度误差。
        这一条值得单独核实（见 res_check.py）。

用法： python tools/test_coordsys.py
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


def loo_err(F, tx, ty, tr, dims=6, lam=1000.0):
    order = list(np.argsort(-np.array([max(corr(F[:, i], tx), corr(F[:, i], ty))
                                       for i in range(F.shape[1])]))[:dims])
    X = F[:, order]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    errs = []
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
        p = np.column_stack([Ae @ bx, Ae @ by])
        errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
    return float(np.mean(errs)) if errs else None


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话\n' % len(data))
    print('=' * 84)
    print('实验：同一份数据、同一套特征，只改目标坐标的【原点与轴向】')
    print('  坐标系 A：现有（左上角为原点，x 右增、y 下增）')
    print('  坐标系 B：左下角为原点，x 右增、y 上增（用户提议）')
    print('  坐标系 C：归一化到 0~1（x 右增、y 下增）')
    print('=' * 84)
    print('%-12s %-22s %-22s %-22s %s' % ('会话', 'A 左上原点', 'B 左下原点+y向上', 'C 归一化', '结论'))
    print('-' * 84)
    diffs = []
    for i, (F, tx, ty, tr) in enumerate(data):
        H = (ty.max() - ty.min()) / (1 - 2 * INSET)   # 屏幕高（像素）
        W = (tx.max() - tx.min()) / (1 - 2 * INSET)
        # A: 原始
        eA = loo_err(F, tx, ty, tr)
        # B: 左下角原点，y 轴向上 → y' = H - y
        eB = loo_err(F, tx, H - ty, tr)
        # C: 归一化
        eC = loo_err(F, tx / W, ty / H, tr)
        diffs.append(abs(eA - eB))
        same = '完全相同' if abs(eA - eB) < 1e-6 else ('差异 %.4f px' % abs(eA - eB))
        print('%-12s %-22s %-22s %-22s %s'
              % ('会话%d' % (i + 1),
                 '%.1f px' % eA, '%.1f px' % eB, '%.5f' % eC, same))

    print('\n' + '=' * 84)
    print('为什么精度必然相同（数学说明）')
    print('=' * 84)
    print('  回归模型： ŷ = Σ βⱼ·zⱼ + β₀      （z 是标准化后的特征）')
    print('  换坐标系只是一次仿射映射： y_new = a·y_old + b')
    print('  把它代进损失函数，最优解会变成：')
    print('      β_new = a·β_old ,   β₀_new = a·β₀_old + b')
    print('  即【原点的移动被截距吸收，轴向/单位的改变被系数吸收】。')
    print('  残差 (ŷ_new − y_new) = a·(ŷ_old − y_old)，误差只被整体缩放一个常数，')
    print('  归一化后完全相同。所以换原点不会带来任何精度提升。')
    if diffs and max(diffs) < 1e-6:
        print('\n  实测验证：两种坐标系的误差逐位相同（差异 < 1e-6 px）✓')

    print('\n' + '=' * 84)
    print('但你提到的"先读取屏幕分辨率"是真问题 —— 那是另一回事')
    print('=' * 84)
    print('  坐标系选择（原点/轴向/单位）      → 仿射变换，被回归吸收，无影响')
    print('  屏幕分辨率/缩放是否正确读取        → 【真实误差来源】')
    print('      本项目实测：显示器 2560×1600，devicePixelRatio = 1.5（150% 缩放）')
    print('      CSS 尺寸 1707×1067，物理像素 2560×1600')
    print('      若按 CSS 尺寸生成目标却按物理像素做换算，会引入约 10% 的尺度误差，')
    print('      表现为"越往边缘越偏"—— 这类误差是坐标系解决不了的，必须正确读取 dpr。')
    print('      核实工具：tools/res_check.py（已实现，可复跑）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
