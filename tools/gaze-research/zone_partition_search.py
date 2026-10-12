#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
zone_partition_search.py — 搜索"眼动真正能分辨"的分区方式

背景
----
真实数据测出 2x2 象限判定只有约 46%（随机基线 25%）：
    上下 二分类 63~77%     左右 二分类 75~85%     2x2 四分类 39~51%
两个方向各 75% 的准确率，组合成四象限就掉到 56% 量级，实测更低。

但注意：**上下（垂直）明显弱于左右（水平）** —— 这与本项目反复验证的
"垂直信号不可靠"完全一致。

于是有一个更合理的融合设计：
    不要用 2x2，而用【纯水平分区】（1x2 或 1x3）。
理由：
  ① 只依赖可靠的横向信号，避开不可靠的纵向
  ② 横向分区恰好解决手指的核心问题 —— 手指够不到/看不到屏幕两侧，
     而"眼动指左右、手指在左右半屏内精定位"正好互补
  ③ 分区数少，准确率高得多

本脚本用真实数据比较各种分区方式的准确率，为融合设计提供依据。

用法： python tools/zone_partition_search.py
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

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
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


def ridge(A, y, lam=10.0):
    d = A.shape[1]
    G = A.T @ A + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, A.T @ y)
    except np.linalg.LinAlgError:
        return None


def loo_acc(F, lab, tr, nz, dims=None):
    """按目标位置留一。dims 用于限制特征数（试验哪些特征最有用）。"""
    if dims is not None:
        # 用与目标的相关性挑维
        sc = []
        for i in range(F.shape[1]):
            v = F[:, i]
            if v.std() < 1e-12:
                sc.append(0); continue
            sc.append(max(abs(np.corrcoef(v, lab)[0, 1]), 0))
        order = list(np.argsort(-np.array(sc))[:dims])
        F = F[:, order]
    mu, sd = F.mean(0), F.std(0) + 1e-9
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
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
                B = None; break
            B.append(b)
        if not B:
            continue
        pred[te] = np.argmax(Z[te] @ np.array(B).T, axis=1)
    m = pred >= 0
    return (pred[m] == lab[m]).mean() if m.sum() > 20 else None


def quantile_labels(v, n):
    """按分位数把连续量切成 n 段（保证各类样本均衡）。"""
    qs = np.percentile(v, np.linspace(0, 100, n + 1)[1:-1])
    return np.digitize(v, qs)


def main():
    data = [(fn, load(os.path.join(ROOT, fn))) for fn in FILES
            if os.path.exists(os.path.join(ROOT, fn))]
    print('载入 %d 会话\n' % len(data))

    schemes = [
        ('水平 1x2', 'x', 2),
        ('水平 1x3', 'x', 3),
        ('水平 1x4', 'x', 4),
        ('垂直 2x1', 'y', 2),
        ('垂直 3x1', 'y', 3),
        ('垂直 4x1', 'y', 4),
    ]

    print('=' * 84)
    print('【不同分区方式在真实数据上的准确率】按目标位置留一')
    print('=' * 84)
    print('  %-12s %-10s %-14s %-14s %-14s %s'
          % ('分区', '类别数', '会话1', '会话2', '会话3', '平均(随机基线)'))
    print('  ' + '-' * 80)
    results = {}
    for name, axis, n in schemes:
        accs = []
        for fn, (F, tx, ty, tr) in data:
            v = tx if axis == 'x' else ty
            lab = quantile_labels(v, n)
            a = loo_acc(F, lab, tr, n)
            accs.append(a)
        valid = [a for a in accs if a is not None]
        avg = np.mean(valid) if valid else None
        results[name] = avg
        f = lambda v: ('%.1f%%' % (v * 100)) if v is not None else '  —  '
        print('  %-12s %-10d %-14s %-14s %-14s %s (%.0f%%)'
              % (name, n, f(accs[0] if len(accs) > 0 else None),
                 f(accs[1] if len(accs) > 1 else None),
                 f(accs[2] if len(accs) > 2 else None),
                 f(avg), 100.0 / n))

    print('\n' + '=' * 84)
    print('【2x2 与 1x2 的对照】确认"垂直分量在拖后腿"')
    print('=' * 84)
    for fn, (F, tx, ty, tr) in data:
        a_h2 = loo_acc(F, quantile_labels(tx, 2), tr, 2)
        a_v2 = loo_acc(F, quantile_labels(ty, 2), tr, 2)
        # 2x2：用两个轴的分段组合
        lab22 = quantile_labels(tx, 2) * 2 + quantile_labels(ty, 2)
        a_22 = loo_acc(F, lab22, tr, 4)
        f = lambda v: ('%.1f%%' % (v * 100)) if v is not None else '—'
        print('  %-26s 水平1x2 %-9s 垂直2x1 %-9s 2x2 %s'
              % (fn, f(a_h2), f(a_v2), f(a_22)))

    print('\n' + '=' * 84)
    print('【结论：融合该用哪种分区】')
    print('=' * 84)
    if results:
        best = max((k for k in results if results[k] is not None),
                   key=lambda k: results[k], default=None)
        if best:
            print('  准确率最高的分区: %s（%.1f%%）' % (best, results[best] * 100))
        h2 = results.get('水平 1x2'); h3 = results.get('水平 1x3')
        v2 = results.get('垂直 2x1'); q22 = None
        print()
        if h2 and v2:
            print('  水平 1x2 %.1f%%  vs  垂直 2x1 %.1f%%  →  %s'
                  % (h2 * 100, v2 * 100, '水平明显更可靠' if h2 > v2 + 0.05 else '两者接近'))
        if h3:
            print('  水平 1x3 %.1f%%（三段的代价，仍可能可接受）' % (h3 * 100))
        print()
        print('  融合设计建议：')
        if h3 and h3 > 0.70:
            print('    → 用【水平三分区】：眼动指"左/中/右"，手指在那一栏内精定位。')
            print('      好处：只用可靠的横向信号；且正好补上手指够不到/看不到两侧的短板。')
        elif h2 and h2 > 0.70:
            print('    → 用【水平二分屏】：眼动指"左半/右半"，手指在半屏内精定位。')
        else:
            print('    → 眼动分区也不够可靠，融合的收益应主要来自"减少手部移动"，')
            print('      而不是"提高准确率"。这个结论要如实写进 README。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
