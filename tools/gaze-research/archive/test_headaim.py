#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_headaim.py — 验证"用头部姿态做全屏瞄准"的可行性

用户思路：既然让头随视线动，那就能用头位做全屏瞄准。
（这也是人类的自然行为 —— 大范围注视本来就会转头，专业眼动仪也靠"眼球+头"两级覆盖。）

可验证的部分
------------
虽然我们采集时"要求头不动"，但实际数据里仍有头位变化（尤其第一份数据漂移很大）。
这些变化里有没有与目标位置相关的成分？如果有，说明头位瞄准是可学的。

测三件事：
  A. 头位特征与目标位置的相关（试次级，即每个目标位置的头位均值）
  B. 只用头位特征做留一网格点交叉验证，精度如何
  C. 头位 + 眼球特征的联合精度，对比纯眼球

判据
----
  · 若纯头位精度就接近或超过纯眼球 → 头位瞄准值得做，且比眼球更稳
  · 若头位精度明显更好，说明"让头参与"确实能救回全屏坐标
  · 注意：本数据是在"要求头不动"下采的，头位变化幅度有限，
    所以这里测出的是【保守下界】—— 真正让用户自由转头时效果会更好

用法： python tools/test_headaim.py
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

    # 头位特征（位置类 + 现有姿态代理）
    head = np.column_stack([
        col('nose_x'), col('nose_y'), col('nose_x') ** 2, col('nose_y') ** 2,
        col('eyecenter_x'), col('eyecenter_y'),
        col('fore_x'), col('fore_y'), col('chin_x'), col('chin_y'),
        col('yaw'), col('pitch'), col('yaw') * col('pitch'),
        iod,
    ])
    # 眼球特征（相对量）
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    hx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    hy = (iry - (col('eyeOL_y') + col('eyeOR_y')) / 2) / iod
    eye = np.column_stack([hx, hy, hx * hx, hy * hy, hx * hy])
    both = np.column_stack([head, eye])
    return dict(tr=tr, tx=tx, ty=ty, head=head, eye=eye, both=both,
                col=col, iod=iod, yaw=col('yaw'), pitch=col('pitch'),
                nose_x=col('nose_x'), nose_y=col('nose_y'))


def ridge(A, y, lam=100.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * d)
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def loo_err(F, tx, ty, tr, lam=100.0):
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = (F - mu) / sd
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    diag = float(np.hypot(W, H))
    errs = []
    for k in np.unique(tr):
        te = tr == k; trn = ~te
        if trn.sum() < 40:
            continue
        A = np.column_stack([Z[trn], np.ones(trn.sum())])
        bx = ridge(A, tx[trn], lam); by = ridge(A, ty[trn], lam)
        if bx is None or by is None:
            continue
        Ae = np.column_stack([Z[te], np.ones(te.sum())])
        p = np.column_stack([Ae @ bx, Ae @ by])
        errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
    return (float(np.mean(errs)), float(np.mean(errs) / diag)) if errs else (None, None)


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else float(v)


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话' % len(data))
    print('注意：本数据是在"要求头不动"下采集的，头位变化幅度有限，')
    print('      所以下面测出的是【保守下界】。真正让用户自由转头时效果会更好。\n')

    print('=' * 84)
    print('【A】头位与目标位置的相关（试次级）')
    print('=' * 84)
    print('%-10s %-8s %-16s %-16s %s' % ('会话', '试次数', 'r(头位x, 目标x)', 'r(头位y, 目标y)', '说明'))
    for i, D in enumerate(data):
        ks = np.unique(D['tr'])
        mx = np.array([D['nose_x'][D['tr'] == k].mean() for k in ks])
        my = np.array([D['nose_y'][D['tr'] == k].mean() for k in ks])
        tx = np.array([D['tx'][D['tr'] == k].mean() for k in ks])
        ty = np.array([D['ty'][D['tr'] == k].mean() for k in ks])
        rx, ry = corr(mx, tx), corr(my, ty)
        note = '头位与目标强相关' if max(abs(rx), abs(ry)) > 0.6 else \
               ('中等' if max(abs(rx), abs(ry)) > 0.35 else '弱（因为要求头不动）')
        print('%-10s %-8d %-16.3f %-16.3f %s' % ('会话%d' % (i + 1), len(ks), rx, ry, note))

    print('\n' + '=' * 84)
    print('【B】留一网格点交叉验证：纯头位 / 纯眼球 / 头位+眼球')
    print('=' * 84)
    print('%-10s %-24s %-24s %-24s %s' % ('会话', '纯头位', '纯眼球', '头位+眼球', '结论'))
    agg = []
    for i, D in enumerate(data):
        e1, n1 = loo_err(D['head'], D['tx'], D['ty'], D['tr'])
        e2, n2 = loo_err(D['eye'], D['tx'], D['ty'], D['tr'])
        e3, n3 = loo_err(D['both'], D['tx'], D['ty'], D['tr'])
        note = ''
        if e1 and e2 and e3:
            best = min(e1, e2, e3)
            if best == e1:
                note = '★ 头位最好'
            elif best == e3:
                note = '★ 联合最好'
            else:
                note = '眼球最好'
            agg.append((e1, e2, e3))
        print('%-10s %-24s %-24s %-24s %s' % ('会话%d' % (i + 1),
              ('%.0f px (%.4f)' % (e1, n1)) if e1 else '-',
              ('%.0f px (%.4f)' % (e2, n2)) if e2 else '-',
              ('%.0f px (%.4f)' % (e3, n3)) if e3 else '-', note))

    if agg:
        a = np.array(agg).mean(axis=0)
        print('\n  三会话平均: 纯头位 %.0f px   纯眼球 %.0f px   联合 %.0f px' % (a[0], a[1], a[2]))
        print('  对照：随机猜约 750 px (0.38 对角线)')

    print('\n' + '=' * 84)
    print('【C】头位变化的实际幅度（判断"让头参与"能提供多大范围）')
    print('=' * 84)
    for i, D in enumerate(data):
        nx, ny = D['nose_x'], D['nose_y']
        print('  会话%d: 鼻尖x 范围 %.4f（std %.4f）  鼻尖y 范围 %.4f（std %.4f）'
              % (i + 1, nx.max() - nx.min(), nx.std(), ny.max() - ny.min(), ny.std()))
        print('          yaw 范围 %.4f   pitch 范围 %.4f'
              % (D['yaw'].max() - D['yaw'].min(), D['pitch'].max() - D['pitch'].min()))

    print('\n判据：')
    print('  · B 里若"纯头位"不差于"纯眼球" → 头位瞄准值得做')
    print('  · "头位+眼球"若最好 → 两级方案成立：全屏靠头、精细靠眼')
    print('  · C 显示当前头位变化幅度。若很小（因为是"头不动"采集），')
    print('    那么让用户自由转头后，头位特征的范围会显著扩大，精度还有上升空间。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
