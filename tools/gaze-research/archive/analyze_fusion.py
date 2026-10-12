#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
analyze_fusion.py — 融合对照实验的离线分析

读入 demo 导出的 fusion_experiment.csv，对三个条件做配对比较：
    A 纯指尖（手做全屏移动，无眼动）
    B 纯眼动（区域判定 + dwell，无手）
    C 融合  （眼动选区域 → 手指区域内精定位）

三项指标（目标里明确要求的）：
    ① 选择时间（ms）
    ② 错误率
    ③ 手部移动距离（px）

方法：
  · 三个条件跑的是【同一随机目标序列】（makeTrialOrder 固定种子），
    所以可以按 trial 配对，用配对差值而非独立样本比较 —— 统计效力高得多。
  · 置信区间用配对 bootstrap（10000 次重采样），不依赖正态假设。
  · 同时报效应量与样本量，避免把小样本噪声当结论。
  · 明确标注能力边界：单被试重复测量属于弱证据，只能给方向性结论。

用法：
    python tools/analyze_fusion.py                      # 读默认路径
    python tools/analyze_fusion.py path/to/xxx.csv
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
DEFAULT_CSV = os.path.join(ROOT, 'fusion_experiment.csv')

COND_NAMES = {'A': 'A 纯指尖', 'B': 'B 纯眼动', 'C': 'C 融合'}


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.DictReader(f)
        rows = list(rd)
    out = []
    for r in rows:
        try:
            out.append({
                'cond': r['cond'].strip(),
                'trial': int(r['trial']),
                'target': r.get('target', ''),
                'correct': int(r['correct']),
                'ms': float(r['ms']),
                'travel': float(r['travel']),
                'zoneActive': int(r.get('zoneActive', 0) or 0),
            })
        except (KeyError, ValueError):
            continue
    return out


def paired_bootstrap_ci(diff, n_boot=10000, seed=0):
    """配对差值的 bootstrap 95% 置信区间。"""
    if len(diff) < 3:
        return None, None
    rng = np.random.default_rng(seed)
    n = len(diff)
    means = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, n)
        means[i] = diff[idx].mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def by_trial(rows, cond):
    """按 trial 索引取某条件的记录，用于配对。"""
    return {r['trial']: r for r in rows if r['cond'] == cond}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    if not os.path.exists(path):
        print('找不到数据文件: %s' % path)
        print('请先在 demo 里跑完实验并按 F 导出 fusion_experiment.csv')
        return 1

    rows = load(path)
    if not rows:
        print('数据文件为空或格式不符')
        return 1

    print('=' * 80)
    print('融合对照实验分析')
    print('=' * 80)
    print('  数据文件: %s' % path)
    print('  总记录数: %d' % len(rows))

    conds = sorted(set(r['cond'] for r in rows))
    print('  条件: %s' % ', '.join(COND_NAMES.get(c, c) for c in conds))
    print()

    # ---------------- 各条件汇总 ----------------
    print('=' * 80)
    print('【各条件汇总】')
    print('=' * 80)
    print('  %-12s %-8s %-12s %-14s %-16s %s'
          % ('条件', 'n', '错误率', '中位耗时ms', '中位手部移动px', '区域锁定率'))
    print('  ' + '-' * 76)
    summary = {}
    for c in conds:
        rs = [r for r in rows if r['cond'] == c]
        n = len(rs)
        if not n:
            continue
        err = 1 - np.mean([r['correct'] for r in rs])
        med_ms = np.median([r['ms'] for r in rs])
        med_tr = np.median([r['travel'] for r in rs])
        zl = np.mean([r['zoneActive'] for r in rs])
        summary[c] = dict(n=n, err=err, ms=[r['ms'] for r in rs],
                          travel=[r['travel'] for r in rs],
                          correct=[r['correct'] for r in rs])
        print('  %-12s %-8d %-12s %-14.0f %-16.0f %.0f%%'
              % (COND_NAMES.get(c, c), n, '%.1f%%' % (err * 100), med_ms, med_tr, zl * 100))

    # ---------------- 配对比较 ----------------
    print()
    print('=' * 80)
    print('【配对比较】三项指标（同 trial 配对，配对 bootstrap 95% CI）')
    print('=' * 80)

    pairs = [('A', 'C'), ('B', 'C'), ('A', 'B')]
    for x, y in pairs:
        if x not in summary or y not in summary:
            continue
        bx, by = by_trial(rows, x), by_trial(rows, y)
        common = sorted(set(bx) & set(by))
        if len(common) < 3:
            print('\n  %s vs %s: 共同 trial 不足（%d），跳过'
                  % (COND_NAMES.get(x, x), COND_NAMES.get(y, y), len(common)))
            continue
        print('\n  %s  vs  %s    共同 trial = %d'
              % (COND_NAMES.get(x, x), COND_NAMES.get(y, y), len(common)))

        # ① 选择时间
        d_ms = np.array([bx[t]['ms'] - by[t]['ms'] for t in common])
        lo, hi = paired_bootstrap_ci(d_ms)
        sig = '' if (lo is not None and lo <= 0 <= hi) else '  ★ 显著'
        print('    ① 选择时间   差值(左-右) 均值 %+8.0f ms' % d_ms.mean())
        if lo is not None:
            print('        95%% CI [%+.0f, %+.0f] ms%s' % (lo, hi, sig))

        # ② 错误率
        d_err = np.array([bx[t]['correct'] - by[t]['correct'] for t in common])
        lo2, hi2 = paired_bootstrap_ci(d_err.astype(float))
        sig2 = '' if (lo2 is not None and lo2 <= 0 <= hi2) else '  ★ 显著'
        print('    ② 错误率     差值(左-右) 均值 %+8.3f' % d_err.mean())
        if lo2 is not None:
            print('        95%% CI [%+.3f, %+.3f]%s' % (lo2, hi2, sig2))

        # ③ 手部移动距离
        d_tr = np.array([bx[t]['travel'] - by[t]['travel'] for t in common])
        lo3, hi3 = paired_bootstrap_ci(d_tr)
        sig3 = '' if (lo3 is not None and lo3 <= 0 <= hi3) else '  ★ 显著'
        print('    ③ 手部移动   差值(左-右) 均值 %+8.0f px' % d_tr.mean())
        if lo3 is not None:
            print('        95%% CI [%+.0f, %+.0f] px%s' % (lo3, hi3, sig3))

    # ---------------- 结论 ----------------
    print()
    print('=' * 80)
    print('【结论判读】')
    print('=' * 80)
    if 'C' in summary and ('A' in summary or 'B' in summary):
        bA, bC = by_trial(rows, 'A'), by_trial(rows, 'C')
        cA = sorted(set(bA) & set(bC))
        if len(cA) >= 3:
            d_ms = np.array([bA[t]['ms'] - bC[t]['ms'] for t in cA])
            d_tr = np.array([bA[t]['travel'] - bC[t]['travel'] for t in cA])
            lo, hi = paired_bootstrap_ci(d_ms)
            lo3, hi3 = paired_bootstrap_ci(d_tr)
            print('  融合(C) 相对 纯指尖(A):')
            print('    · 选择时间 %s' % ('更快' if d_ms.mean() > 0 else '更慢'))
            print('    · 手部移动 %s' % ('更少' if d_tr.mean() > 0 else '更多'))
            if lo is not None and lo > 0:
                print('    · 时间优势的 95% CI 不跨 0 → 【显著更快】')
            elif lo is not None:
                print('    · 时间优势的 95% CI 跨 0 → 【不显著】')
        bB = by_trial(rows, 'B')
        cB = sorted(set(bB) & set(bC))
        if len(cB) >= 3:
            d_c = np.array([bB[t]['correct'] - bC[t]['correct'] for t in cB])
            print('  融合(C) 相对 纯眼动(B):')
            print('    · 正确率差值均值 %+.3f（正=融合更准）' % d_c.mean())

    print()
    print('=' * 80)
    print('【能力边界（必须如实写进 README）】')
    print('=' * 80)
    print('  · 本实验为【单被试重复测量】，属弱证据，只能给方向性结论，')
    print('    不能外推为"对所有人有效"。')
    print('  · n = %d 次/条件；配对设计提高了效力，但仍需谨慎解读。'
          % (summary.get('C', {}).get('n', 0)))
    print('  · 三个条件同一目标序列，配对有效；但条件间的学习效应无法完全排除')
    print('    （建议按 A→B→C 与 C→B→A 各跑一轮做顺序对照）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
