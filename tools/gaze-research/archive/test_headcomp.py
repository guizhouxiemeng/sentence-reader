#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_headcomp.py — 显式扣除头位后，全屏坐标捕捉能否救回来

动机
----
项目一直卡在"逐帧抖动、垂直不可用"。但有一个混淆一直没处理：

    校准/采集时，人看向屏幕不同位置会自然带头部转动，
    所以 iris 位置与头位高度相关（实测 r = 0.99），
    而它与目标的直接相关只有 0.17~0.25。

这意味着我们学到的东西里混着"头在哪"。而这也指向一条一直没试过的路：
**先把头位的影响显式扣掉，再看残差里有没有真正的视线信号。**

做法（两步回归）
--------------
  第一步：用头位特征（鼻尖/额头/下巴/眼中心 的 x,y + 瞳距等）
          预测虹膜位置，得到"头位能解释的部分"
  第二步：取残差（虹膜位置 − 头位可解释部分），看残差与目标位置的相关
          并用残差做回归，用真实目标的留一交叉验证评估精度

判据
----
  · 若残差与目标的相关明显高于原始特征 → 头位混淆确实存在，扣除后信号变清晰
  · 若残差的留一误差明显低于 0.145 对角线 → 全屏坐标捕捉有救
  · 若残差与目标几乎不相关 → 视线信号确实不存在，全屏坐标不成立

另外做"同头位条件"检验：只挑头位接近的帧，看这些帧内特征能否区分目标位置。
这直接回答"头不动时，眼睛能否定位"。

用法： python tools/test_headcomp.py
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

    # 头位特征（表示"头在哪、朝哪"）
    head = np.column_stack([
        col('nose_x'), col('nose_y'),
        col('eyecenter_x'), col('eyecenter_y'),
        col('chin_x'), col('chin_y'),
        col('fore_x'), col('fore_y'),
        iod, col('yaw'), col('pitch'),
    ])
    # 当前 demo 用的特征（供对比）
    gx = (irx - (col('eyeOL_x') + col('eyeOR_x')) / 2) / iod
    gy = (iry - (col('eyeOL_y') + col('eyeOR_y')) / 2) / iod
    cur = np.column_stack([iry, irx, gx, gx * gx, iry * iry,
                           col('L_h'), col('L_h2'), col('R_h'), col('R_h2')])
    return dict(tr=tr, tx=tx, ty=ty, iris=np.column_stack([irx, iry]),
                head=head, cur=cur, iod=iod, irx=irx, iry=iry)


def ridge(A, y, lam=1.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * d)
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def loo_grid_err(X, tx, ty, tr, lam=1000.0, dims=None):
    """按目标位置做留一交叉验证，返回平均像素误差与对角线归一化。"""
    if dims:
        def corr(a, b):
            if a.std() < 1e-12 or b.std() < 1e-12:
                return 0.0
            v = np.corrcoef(a, b)[0, 1]
            return 0.0 if not np.isfinite(v) else abs(v)
        order = list(np.argsort(-np.array([max(corr(X[:, i], tx), corr(X[:, i], ty))
                                           for i in range(X.shape[1])]))[:dims])
        X = X[:, order]
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    W = (tx.max() - tx.min()) / (1 - 2 * INSET)
    H = (ty.max() - ty.min()) / (1 - 2 * INSET)
    diag = float(np.hypot(W, H))
    ks = np.unique(tr)
    errs = []
    for k in ks:
        te = tr == k
        trn = ~te
        if trn.sum() < 50:
            continue
        A = np.column_stack([Z[trn], np.ones(trn.sum())])
        bx = ridge(A, tx[trn], lam); by = ridge(A, ty[trn], lam)
        if bx is None or by is None:
            continue
        Ae = np.column_stack([Z[te], np.ones(te.sum())])
        p = np.column_stack([Ae @ bx, Ae @ by])
        errs.extend(np.linalg.norm(p - np.column_stack([tx[te], ty[te]]), axis=1).tolist())
    if not errs:
        return None, None
    return float(np.mean(errs)), float(np.mean(errs) / diag)


def main():
    data = [load(f) for f in FILES if os.path.exists(os.path.join(ROOT, f))]
    print('载入 %d 会话\n' % len(data))

    print('=' * 84)
    print('【第一步】头位能解释多少虹膜位置？')
    print('=' * 84)
    print('%-10s %-14s %-14s %s' % ('会话', 'iris_x R²', 'iris_y R²', '说明'))
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        r2 = []
        for j in range(2):
            b = ridge(H, D['iris'][:, j], 1e-6)
            pred = H @ b
            ss = ((D['iris'][:, j] - pred) ** 2).sum()
            tot = ((D['iris'][:, j] - D['iris'][:, j].mean()) ** 2).sum()
            r2.append(1 - ss / tot)
        print('%-10s %-14.3f %-14.3f %s' % ('会话%d' % (i + 1), r2[0], r2[1],
              '头位主导虹膜位置' if max(r2) > 0.9 else ''))

    print('\n' + '=' * 84)
    print('【第二步】扣除头位后，残差里还有多少视线信号？')
    print('=' * 84)
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        res = np.zeros_like(D['iris'])
        for j in range(2):
            b = ridge(H, D['iris'][:, j], 1e-6)
            res[:, j] = D['iris'][:, j] - H @ b

        def corr(a, b):
            if a.std() < 1e-12 or b.std() < 1e-12:
                return 0.0
            return float(np.corrcoef(a, b)[0, 1])

        print('  会话%d:' % (i + 1))
        print('     原始 iris_x 与目标x: %+.3f    残差与目标x: %+.3f'
              % (corr(D['iris'][:, 0], D['tx']), corr(res[:, 0], D['tx'])))
        print('     原始 iris_y 与目标y: %+.3f    残差与目标y: %+.3f'
              % (corr(D['iris'][:, 1], D['ty']), corr(res[:, 1], D['ty'])))
        # 残差的动态范围 vs 组内噪声
        l2 = res.std()
        within = np.mean([res[D['tr'] == k].std() for k in np.unique(D['tr'])
                          if (D['tr'] == k).sum() >= 5])
        print('     残差 L2/L1 = %.2f（%.5f / %.5f）' % (l2 / (within + 1e-12), l2, within))

    print('\n' + '=' * 84)
    print('【第三步】同头位条件下，眼睛能否区分目标位置？')
    print('  做法：把帧按头位聚类，只在"头位接近"的帧内部比较不同目标')
    print('=' * 84)
    for i, D in enumerate(data):
        H = D['head']
        # 用头位前两维（鼻尖 x,y）做 5x5 分箱，取最大的一箱
        bx = np.digitize(H[:, 0], np.percentile(H[:, 0], [20, 40, 60, 80]))
        by = np.digitize(H[:, 1], np.percentile(H[:, 1], [20, 40, 60, 80]))
        cell = bx * 5 + by
        best_cell, best_n = 0, 0
        for c in np.unique(cell):
            n = (cell == c).sum()
            if n > best_n:
                best_n, best_cell = n, c
        m = cell == best_cell
        # 这一箱里覆盖了几个目标位置
        ntar = len(np.unique(np.round(D['tx'][m] / 40).astype(int) * 1000 +
                             np.round(D['ty'][m] / 40).astype(int)))
        if ntar < 3:
            print('  会话%d: 最大同头位箱只有 %d 帧、%d 个目标，样本不足' % (i + 1, best_n, ntar))
            continue
        e, en = loo_grid_err(D['cur'][m], D['tx'][m], D['ty'][m], D['tr'][m], dims=6)
        print('  会话%d: 同头位箱 %d 帧 / %d 个目标 → 留一误差 %s'
              % (i + 1, best_n, ntar, ('%.0f px (%.4f 对角线)' % (e, en)) if e else '样本不足'))

    print('\n' + '=' * 84)
    print('【第四步】用"头位残差"重建特征，重新做全屏坐标回归')
    print('=' * 84)
    print('%-12s %-18s %-18s %s' % ('会话', '当前特征(demo用)', '头位残差特征', '结论'))
    for i, D in enumerate(data):
        H = np.column_stack([D['head'], np.ones(len(D['head']))])
        res = np.zeros_like(D['iris'])
        for j in range(2):
            b = ridge(H, D['iris'][:, j], 1e-6)
            res[:, j] = D['iris'][:, j] - H @ b
        ids = D['iod']
        rx = res[:, 0] / ids
        ry = res[:, 1] / ids
        # 残差特征集：残差 + 二次项 + 相对眼角（不含被眼皮污染的 L_v/R_v）
        F = np.column_stack([rx, ry, rx * rx, ry * ry, rx * ry,
                             (D['irx'] - (D['head'][:, 2])) / ids,
                             D['cur'][:, 5], D['cur'][:, 6], D['cur'][:, 7], D['cur'][:, 8]])
        e1, n1 = loo_grid_err(D['cur'], D['tx'], D['ty'], D['tr'], dims=6)
        e2, n2 = loo_grid_err(F, D['tx'], D['ty'], D['tr'], dims=6)
        verdict = ''
        if e1 and e2:
            if e2 < e1 * 0.9:
                verdict = '✓ 头位补偿明显改善'
            elif e2 < e1:
                verdict = '略有改善'
            else:
                verdict = '无改善'
        print('%-12s %-18s %-18s %s'
              % ('会话%d' % (i + 1),
                 ('%.0f px (%.4f)' % (e1, n1)) if e1 else '-',
                 ('%.0f px (%.4f)' % (e2, n2)) if e2 else '-',
                 verdict))

    print('\n判据：')
    print('  · 头位 R² 接近 1 → 虹膜位置几乎完全由头位决定，这是本项目最大的混淆')
    print('  · 残差与目标的相关若明显高于原始 → 扣除头位后信号变清晰')
    print('  · 第四步若显示"明显改善" → 全屏坐标捕捉有救，值得重做特征层')
    return 0


if __name__ == '__main__':
    sys.exit(main())
