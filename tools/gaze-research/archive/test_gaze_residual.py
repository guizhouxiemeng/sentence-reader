#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_gaze_residual.py — 弄清"虹膜相对眼角"里到底有没有视线信号

上一个脚本（test_headcomp）的第四步有缺陷：它测的是【绝对虹膜位置】的
头位残差，而绝对虹膜位置本身被头位主导（R²=0.999），扣掉头位后剩下的是噪声。
这不能说明"虹膜相对眼角"这种相对量里也没有信号。

本脚本做正确的测量：
  对【虹膜相对眼角】这个相对量，扣除头位的影响，看残差里还有多少视线信息。

三个层次：
  A. 相对量对头位的依赖有多强（R²）
  B. 相对量的残差与目标位置的相关性
  C. 用"相对量的残差"做留一交叉验证，对比原始相对量

另外做一次更有说服力的检验：
  **用"固定头位"的子集**做校准与测试 —— 只取头位最集中的一批帧，
  在它们内部做留一网格点交叉验证。这直接回答
  "头不动的时候，能不能靠眼睛区分屏幕位置"。

用法： python tools/test_gaze_residual.py
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
    # 相对量：虹膜相对左右外角（这是 demo 用的水平特征）
    hx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    hy = (iry - (col('eyeOL_y') + col('eyeOR_y')) / 2) / iod
    # 头位特征
    head = np.column_stack([col('nose_x'), col('nose_y'),
                            col('eyecenter_x'), col('eyecenter_y'),
                            col('chin_x'), col('chin_y'),
                            col('fore_x'), col('fore_y'),
                            iod, col('yaw'), col('pitch')])
    return dict(tr=tr, tx=tx, ty=ty, hx=hx, hy=hy, head=head,
                irx=irx, iry=iry, iod=iod, col=col)


def ridge(A, y, lam=1e-3):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * d)
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def r2(y, pred):
    ss = ((y - pred) ** 2).sum()
    tot = ((y - y.mean()) ** 2).sum()
    return 1 - ss / max(tot, 1e-12)


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def loo_err(F, tx, ty, tr, lam=100.0):
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = (F - mu) / sd
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    diag = float(np.hypot(W, H))
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
    return (float(np.mean(errs)), float(np.mean(errs) / diag)) if errs else (None, None)


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 84)
    print('【A】"虹膜相对眼角"这个相对量，有多少被头位解释？')
    print('=' * 84)
    print('%-10s %-16s %-16s %s' % ('会话', 'hx 的头位 R²', 'hy 的头位 R²', '说明'))
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        out = []
        for key in ('hx', 'hy'):
            b = ridge(H, D[key])
            out.append(r2(D[key], H @ b))
        note = '相对量也被头位强烈影响' if max(out) > 0.8 else ('中等' if max(out) > 0.4 else '基本不受头位影响')
        print('%-10s %-16.3f %-16.3f %s' % ('会话%d' % (i + 1), out[0], out[1], note))

    print('\n' + '=' * 84)
    print('【B】相对量的【头位残差】与目标位置的相关（对比原始相对量）')
    print('=' * 84)
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        rx = D['hx'] - H @ ridge(H, D['hx'])
        ry = D['hy'] - H @ ridge(H, D['hy'])
        print('  会话%d:' % (i + 1))
        print('     hx 与目标x: %+.3f     残差与目标x: %+.3f' % (corr(D['hx'], D['tx']), corr(rx, D['tx'])))
        print('     hy 与目标y: %+.3f     残差与目标y: %+.3f' % (corr(D['hy'], D['ty']), corr(ry, D['ty'])))
        l2 = rx.std(); l1 = np.mean([rx[D['tr'] == k].std() for k in np.unique(D['tr']) if (D['tr'] == k).sum() >= 5])
        print('     hx 残差 L2/L1 = %.2f' % (l2 / (l1 + 1e-12)))

    print('\n' + '=' * 84)
    print('【C】留一网格点交叉验证：原始特征 vs 头位残差特征')
    print('=' * 84)
    print('%-10s %-22s %-22s %s' % ('会话', '原始(相对量+二次项)', '头位残差特征', '结论'))
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        rx = D['hx'] - H @ ridge(H, D['hx'])
        ry = D['hy'] - H @ ridge(H, D['hy'])
        F1 = np.column_stack([D['hx'], D['hy'], D['hx'] ** 2, D['hy'] ** 2, D['hx'] * D['hy'],
                              D['col']('irisL_x') / D['iod'], D['col']('irisR_x') / D['iod']])
        F2 = np.column_stack([rx, ry, rx ** 2, ry ** 2, rx * ry,
                              D['col']('irisL_x') / D['iod'], D['col']('irisR_x') / D['iod']])
        e1, n1 = loo_err(F1, D['tx'], D['ty'], D['tr'])
        e2, n2 = loo_err(F2, D['tx'], D['ty'], D['tr'])
        verdict = '—'
        if e1 and e2:
            verdict = ('✓ 改善 %.0f%%' % (100 * (e1 - e2) / e1)) if e2 < e1 * 0.95 else \
                      ('略差' if e2 > e1 * 1.05 else '持平')
        print('%-10s %-22s %-22s %s' % ('会话%d' % (i + 1),
              ('%.0f px (%.4f)' % (e1, n1)) if e1 else '-',
              ('%.0f px (%.4f)' % (e2, n2)) if e2 else '-', verdict))

    print('\n' + '=' * 84)
    print('【D】固定头位子集：头不动时，眼睛能区分屏幕位置吗？')
    print('  取头位最集中的一批帧（鼻尖 x,y 都在最密的 20% 区间内）')
    print('=' * 84)
    for i, D in enumerate(data):
        hx0, hy0 = D['col']('nose_x'), D['col']('nose_y')
        qx = np.percentile(hx0, [40, 60]); qy = np.percentile(hy0, [40, 60])
        m = (hx0 > qx[0]) & (hx0 < qx[1]) & (hy0 > qy[0]) & (hy0 < qy[1])
        if m.sum() < 80:
            print('  会话%d: 固定头位帧仅 %d，样本不足' % (i + 1, m.sum()))
            continue
        ntar = len(np.unique(np.round(D['tx'][m] / 40).astype(int) * 1000 +
                             np.round(D['ty'][m] / 40).astype(int)))
        F = np.column_stack([D['hx'][m], D['hy'][m], D['hx'][m] ** 2, D['hy'][m] ** 2,
                             D['hx'][m] * D['hy'][m]])
        e, en = loo_err(F, D['tx'][m], D['ty'][m], D['tr'][m])
        print('  会话%d: 固定头位 %d 帧 / %d 个目标 → 留一误差 %s'
              % (i + 1, m.sum(), ntar, ('%.0f px (%.4f 对角线)' % (e, en)) if e else '样本不足'))

    print('\n判据：')
    print('  · A 若接近 1 → 连"相对量"都被头位主导，问题比预想更严重')
    print('  · C 若残差特征明显更好 → 头位补偿能救回全屏坐标')
    print('  · D 的结论最关键：头位固定时若误差仍在 0.3+ 对角线，')
    print('    说明"看不同位置"这件事在特征上根本不可分，全屏坐标不成立')
    return 0


if __name__ == '__main__':
    sys.exit(main())
