#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
residual_map.py — 回答设计文档里那个"决定成败的假设"

设计文档第八节把下面这条列为"待验证假设"：
    把区域放大 M 倍后，手部定位误差是变成 1/M，还是纹丝不动？

这个问题的答案取决于 405px 误差的构成：
    来源 A｜全局偏置（标定整体偏移）
        → 放大不能减少它。因为误差是加性的，与格子大小无关。
    来源 B｜局部非线性（映射畸变随位置变化）
        → 放大能减少它。因为放大后每个候选占更多屏幕，局部更接近线性。

区分方法
--------
用真实校准数据，把每个校准点的【预测残差】画在屏幕上：
    · 残差方向一致（都朝一个方向）→ 主要是 A
    · 残差方向随位置系统性变化   → 主要是 B

同时做一件更有用的事：测量"插值误差"
    留一误差 = 预测【完全没见过的校准点】的误差（悲观）
    插值误差 = 预测【校准点之间位置】的误差（接近实际使用）
实际使用中手指落在校准点附近或之间，所以插值误差才是设计界面容量的依据。

用法： python tools/residual_map.py
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
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    # 用与"视线"同源的特征（这些会话只有视线数据）——
    # 但对"误差是加性偏置还是局部的"这个问题，模态不是关键，
    # 关键是残差的空间结构。
    iod = col('iod') + 1e-9
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    F = np.column_stack([iry, irx, gx, gx * gx, iry * iry,
                         col('L_h'), col('L_h2'), col('R_h'), col('R_h2')])
    return F, tx, ty, tr


def ridge(A, y, lam=100.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def fit_predict(F, tx, ty, tr, train_mask, test_mask):
    """用 train_mask 训练，预测 test_mask。返回 (pred, err)。"""
    Xtr, Xte = F[train_mask], F[test_mask]
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-9
    Ztr = np.column_stack([(Xtr - mu) / sd, np.ones(len(Xtr))])
    Zte = np.column_stack([(Xte - mu) / sd, np.ones(len(Xte))])
    bx = ridge(Ztr, tx[train_mask]); by = ridge(Ztr, ty[train_mask])
    if bx is None or by is None:
        return None, None
    px = Zte @ bx; py = Zte @ by
    err = np.hypot(px - tx[test_mask], py - ty[test_mask])
    return np.column_stack([px, py]), err


def main():
    data = [(fn, load(os.path.join(ROOT, fn))) for fn in FILES
            if os.path.exists(os.path.join(ROOT, fn))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 80)
    print('【问题一】误差是加性偏置（A）还是局部畸变（B）？')
    print('  做法：每个目标位置一组，看【残差的方向】是否随屏幕位置系统变化')
    print('=' * 80)
    print('  %-10s %-10s %-16s %-16s %s'
          % ('会话', '目标位置', '残差 dx', '残差 dy', '方向'))
    print('  ' + '-' * 74)

    global_dirs = []
    for fi, (fn, (F, tx, ty, tr)) in enumerate(data):
        ks = np.unique(tr)
        # 试次级残差（用全部其它试次训练——不严格留一，但足以看空间结构）
        rows_out = []
        for k in ks:
            te = tr == k
            trn = ~te
            if trn.sum() < 50:
                continue
            pred, err = fit_predict(F, tx, ty, tr, trn, te)
            if pred is None:
                continue
            dx = float(np.mean(pred[:, 0] - tx[te]))
            dy = float(np.mean(pred[:, 1] - ty[te]))
            ang = np.degrees(np.arctan2(dy, dx))
            rows_out.append((float(np.mean(tx[te])), float(np.mean(ty[te])), dx, dy, ang))
        if not rows_out:
            continue
        angs = np.array([r[4] for r in rows_out])
        # 方向一致性：用单位向量的合成长度衡量（1=完全同向，0=随机）
        ux = np.cos(np.radians(angs)).mean()
        uy = np.sin(np.radians(angs)).mean()
        R = float(np.hypot(ux, uy))
        global_dirs.append(R)
        print('  %-10s %-10s' % (fn[:10], '(全部)'))
        for (mx, my, dx, dy, ang) in rows_out[:6]:
            print('  %-10s (%4.0f,%4.0f)  %+8.0f       %+8.0f      %+.0f°'
                  % ('', mx, my, dx, dy, ang))
        print('  %-10s 方向一致性 R = %.3f  →  %s'
              % ('', R, '主要是加性偏置（放大无用）' if R > 0.6 else
                 ('混合' if R > 0.3 else '方向随位置变化（放大可能有效）')))
        print()

    print('=' * 80)
    print('【问题二】插值误差 vs 留一误差 —— 实际设计该用哪个数')
    print('  留一：预测完全没见过的校准点（悲观）')
    print('  插值：预测校准点【之间】的位置（接近实际使用）')
    print('=' * 80)
    print('  %-12s %-18s %-18s %s' % ('会话', '留一误差px', '中心区插值误差px', '比值'))
    print('  ' + '-' * 74)
    for fn, (F, tx, ty, tr) in data:
        ks = np.unique(tr)
        # 留一
        loo_errs = []
        for k in ks:
            te = tr == k; trn = ~te
            if trn.sum() < 50:
                continue
            _, err = fit_predict(F, tx, ty, tr, trn, te)
            if err is not None:
                loo_errs.extend(err.tolist())
        # 插值：用【外围】目标训练，预测【中心区域】的目标
        mx = np.median(tx); my = np.median(ty)
        d2 = np.hypot(tx - mx, ty - my)
        inner = d2 < np.percentile(d2, 25)     # 最中心的 25%
        outer = d2 > np.percentile(d2, 60)     # 外围
        _, ierr = fit_predict(F, tx, ty, tr, outer, inner)
        a = np.mean(loo_errs) if loo_errs else None
        b = np.mean(ierr) if ierr is not None else None
        f = lambda v: ('%.0f' % v) if v is not None else '—'
        ratio = ('%.2f' % (b / a)) if (a and b) else '—'
        print('  %-12s %-18s %-18s %s' % (fn[:12], f(a), f(b), ratio))

    print()
    print('=' * 80)
    print('【对设计文档的直接回答】')
    print('=' * 80)
    if global_dirs:
        R = float(np.mean(global_dirs))
        print('  残差方向一致性 R = %.3f（1=完全同向的加性偏置，0=纯局部畸变）' % R)
        print()
        if R > 0.6:
            print('  → 【主要是加性偏置】。这意味着：')
            print('     放大 M 倍【不会】减少这个误差的绝对像素值 ——')
            print('     偏置是加性的，格子放大后偏置照旧，只是相对更小。')
            print('     所以设计文档第八节的担心是成立的。')
            print('     但注意：如果把"偏置"作为整体在每次锁定后重新标定一次')
            print('     （即锁定后用该区域内的少量点做一次局部校正），')
            print('     偏置可以被消掉 —— 这比"靠放大"更直接有效。')
        elif R > 0.3:
            print('  → 【混合】。加性偏置与局部畸变各占一部分。')
            print('     放大能减少局部畸变那部分，但消不掉偏置。')
            print('     建议：先做一次"锁定后局部重标定"消掉偏置，')
            print('     再看放大是否还有收益。')
        else:
            print('  → 【主要是局部畸变】。放大【会】有效降低误差，')
            print('     设计文档的递归方案成立，且可以安全使用多级。')
    print()
    print('  一个比"放大"更直接的思路（由本分析引出）：')
    print('    如果误差主要是加性偏置，那么在【每次锁定后】用该区域内的')
    print('    几个已知点做一次局部校正，就能把偏置消掉 ——')
    print('    这不需要用户额外操作，因为锁定后的重排界面本身就知道')
    print('    每个格子在哪。这比"多级放大"代价低得多。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
