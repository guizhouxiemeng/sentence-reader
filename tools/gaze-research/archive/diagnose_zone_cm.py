#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
diagnose_zone_cm.py — 诊断 2x2 象限混淆矩阵的异常

上次结果：
    平均 2x2 准确率 59.0%（随机基线 25%）
    混淆矩阵召回率：左上 76% / 右上 83% / 左下 29% / 右下 5%
    → 上下两半差距极大（上半 76~83%，下半 5~29%）

这可能是三种情况之一：
  A. 样本量极不平衡（下半象限样本很少，召回率不可信）
  B. 垂直方向的信号本身不可分辨（与实测"垂直信号弱"一致）
  C. 评估方式过于严苛 —— 本次用【按目标位置留一】，
     即预测完全没见过的屏幕位置；而 demo 里校准点铺满全屏，
     每个区域都有训练数据。两者的难度不同，必须区分。

本脚本把这三件事分别量化。

用法： python tools/diagnose_zone_cm.py
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
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    F = np.column_stack([
        iry, irx, gx, gx * gx, iry * iry,
        (col('irisL_x') - col('eyeOL_x')) / iod,
        (col('irisR_x') - col('eyeOR_x')) / iod,
    ])
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    return F, tx, ty, tr


def labels(tx, ty):
    # 分界点用目标坐标自身的中位数 —— 不能用 W/2（目标范围是 0.08~0.92 视口，
    # 直接用 0.5*H 会把下半象限标错，产生"下半召回 5%"的假象）。
    return (((ty > np.median(ty)).astype(int) * 2 + (tx > np.median(tx)).astype(int)),
            tx.max(), ty.max())


def ridge(A, y, lam=10.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def eval_mode(F, lab, tr, nz, mode):
    """mode='loo' 按目标位置留一；mode='insample' 全量训练后自检。"""
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
    if mode == 'insample':
        B = [ridge(Z, (lab == lv).astype(float)) for lv in range(nz)]
        if any(b is None for b in B):
            return None, None
        pred = np.argmax(Z @ np.array(B).T, axis=1)
        return (pred == lab).mean(), pred

    ks = np.unique(tr)
    lab_tr = {k: lab[tr == k][0] for k in ks}
    pred = np.full(len(lab), -1)
    for k in ks:
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        B = []
        for lv in range(nz):
            ytr = np.array([1.0 if lab_tr[int(t)] == lv else 0.0 for t in tr[trn]])
            b = ridge(Z[trn], ytr)
            if b is None:
                B = None
                break
            B.append(b)
        if not B:
            continue
        pred[te] = np.argmax(Z[te] @ np.array(B).T, axis=1)
    m = pred >= 0
    return ((pred[m] == lab[m]).mean() if m.sum() > 20 else None), pred


def main():
    data = [(fn, load(os.path.join(ROOT, fn))) for fn in FILES
            if os.path.exists(os.path.join(ROOT, fn))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 80)
    print('【A】象限样本量是否平衡（判断召回率是否可信）')
    print('=' * 80)
    for fn, (F, tx, ty, tr) in data:
        lab, W, H = labels(tx, ty)
        cnt = np.bincount(lab, minlength=4)
        print('  %-26s 左上 %5d  右上 %5d  左下 %5d  右下 %5d'
              % (fn, cnt[0], cnt[1], cnt[2], cnt[3]))
        # 上下两半的样本量
        print('  %-26s 上半 %5d  下半 %5d' % ('', cnt[0] + cnt[1], cnt[2] + cnt[3]))

    print('\n' + '=' * 80)
    print('【B】两种评估方式的差距（这决定 demo 里的实际表现）')
    print('  留一(loo)     = 预测完全没见过的屏幕位置（严苛）')
    print('  全量自检       = 每个区域都有训练数据（接近 demo 的校准流程）')
    print('=' * 80)
    print('  %-26s %-16s %-16s %s' % ('会话', '全量自检', '留一', '差距'))
    print('  ' + '-' * 74)
    for fn, (F, tx, ty, tr) in data:
        lab, W, H = labels(tx, ty)
        nz = 4
        a_in, _ = eval_mode(F, lab, tr, nz, 'insample')
        a_loo, _ = eval_mode(F, lab, tr, nz, 'loo')
        f = lambda v: ('%.1f%%' % (v * 100)) if v is not None else '—'
        gap = ('%+.1f pp' % ((a_in - a_loo) * 100)) if (a_in and a_loo) else '—'
        print('  %-26s %-16s %-16s %s' % (fn, f(a_in), f(a_loo), gap))

    print('\n' + '=' * 80)
    print('【C】垂直方向为什么弱：看目标 y 与特征的相关性')
    print('=' * 80)
    for fn, (F, tx, ty, tr) in data:
        # 用试次级均值，避免帧间相关虚高
        ks = np.unique(tr)
        m_ry = np.array([F[tr == k][:, 0].mean() for k in ks])
        m_ty = np.array([ty[tr == k].mean() for k in ks])
        m_rx = np.array([F[tr == k][:, 1].mean() for k in ks])
        m_tx = np.array([tx[tr == k].mean() for k in ks])
        cr = lambda a, b: np.corrcoef(a, b)[0, 1] if a.std() > 1e-12 and b.std() > 1e-12 else 0
        print('  %-26s iris_y~目标y %+.3f    iris_x~目标x %+.3f'
              % (fn, cr(m_ry, m_ty), cr(m_rx, m_tx)))

    print('\n' + '=' * 80)
    print('【结论】')
    print('=' * 80)
    print('  需要看 A 的样本量：若下半象限样本很少，则"召回 5%"只是小样本噪声，')
    print('  不能据此断定垂直不可用。')
    print('  需要看 B 的差距：若全量自检明显高于留一，说明 demo（每个区域都有')
    print('  校准数据）的实际表现会好于留一数字，之前 59% 是低估。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
