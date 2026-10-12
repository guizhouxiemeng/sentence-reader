#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
diagnose_calib_conflict.py — 验证"校准点特征重合导致映射退化"这个推断

现场证据（诊断面板 + HUD）：
    · canvas 坐标系三个判据全部 ✓（原点/尺寸/位图都一致）→ 不是显示层
    · lastPx=778, lastPy=548 落在屏幕正中，而使用者明显在指某个目标
    · 留一误差 632px
    · 点间最小距离 0.11（偏小）
    · 手在画面内 63%（偏低）

推断：校准时多个校准点在【特征空间】里几乎重合 —— 手在那些点上位置相同，
      却被打上了不同的屏幕坐标标签。回归面对矛盾标签只能输出折中值
      （接近屏幕中心），于是"指哪都不对"。

更重要的推论：如果这是真的，那么【特征本身几乎不随屏幕位置变化】，
即这一次校准的输入信号是无效的。这可以从事后数据直接检验。

本脚本做两件事：
  ① 用手部特征模拟"特征几乎不变"的退化情形，看回归输出是否坍缩到中心
  ② 给出"可用的校准"应当满足的判据，供 demo 自查

用法： python tools/diagnose_calib_conflict.py
"""
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

W, H = 1707.0, 1067.0


def ridge(Z, y, lam=1.0):
    d = Z.shape[1]
    G = Z.T @ Z + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, Z.T @ y)
    except np.linalg.LinAlgError:
        return None


def simulate(noise_frac, seed=0):
    """模拟校准：特征 = 屏幕位置的线性映射 + 噪声。

    noise_frac = 噪声标准差 / 特征的真实变化范围。
      · 0.05  → 信号清晰，校准应当很准
      · 0.5   → 噪声与信号同量级，校准勉强可用
      · 1.5   → 噪声远大于信号，特征几乎不携带位置信息（疑似现场情形）
    """
    rng = np.random.default_rng(seed)
    # 9 点米字工作区
    wb = (0.16, 0.84, 0.23, 0.92)     # x0,x1,y0,y1（占视口比例）
    x0, x1 = wb[0] * W, wb[1] * W
    y0, y1 = wb[2] * H, wb[3] * H
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pts = [(cx, cy), (cx, y0), (cx, y1), (x0, cy), (x1, cy),
           (x0, y0), (x1, y0), (x0, y1), (x1, y1)]

    # 真实映射：特征 = 0.2 + 0.6 * 归一化位置（各维略有差异模拟共线）
    sig_x, sig_y = 0.55, 0.40          # 特征的真实变化范围
    F, Y = [], []
    for (px, py) in pts:
        t_x = (px - x0) / (x1 - x0)
        t_y = (py - y0) / (y1 - y0)
        for _ in range(20):
            fx = 0.20 + sig_x * t_x + rng.normal(0, sig_x * noise_frac)
            fy = 0.25 + sig_y * t_y + rng.normal(0, sig_y * noise_frac)
            # 8 维特征：由 (fx, fy) 派生（保持与 demo 一致的结构）
            F.append([fx, fy, fx * fx, fy * fy, fx * fy,
                      fx * 0.5 + 0.1, fy * 0.8 + 0.05, 0.3 + 0.1 * fx])
            Y.append([px, py])
    F = np.array(F); Y = np.array(Y)

    mu, sd = F.mean(0), F.std(0) + 1e-12
    Z = np.column_stack([(F - mu) / sd, np.ones(len(F))])
    bx = ridge(Z, Y[:, 0]); by = ridge(Z, Y[:, 1])
    if bx is None or by is None:
        return None

    preds = np.column_stack([Z @ bx, Z @ by])
    # 预测输出范围 vs 目标范围
    pred_span_x = preds[:, 0].max() - preds[:, 0].min()
    pred_span_y = preds[:, 1].max() - preds[:, 1].min()
    tgt_span_x = Y[:, 0].max() - Y[:, 0].min()
    tgt_span_y = Y[:, 1].max() - Y[:, 1].min()
    # 留一误差（按目标位置分组）
    errs = []
    keys = np.round(Y[:, 0] / 40).astype(int) * 1000 + np.round(Y[:, 1] / 40).astype(int)
    for k in np.unique(keys):
        te = keys == k; tr = ~te
        if tr.sum() < 20 or te.sum() < 3:
            continue
        bx2 = ridge(Z[tr], Y[tr, 0]); by2 = ridge(Z[tr], Y[tr, 1])
        if bx2 is None or by2 is None:
            continue
        p = np.column_stack([Z[te] @ bx2, Z[te] @ by2])
        errs.extend(np.hypot(p[:, 0] - Y[te, 0], p[:, 1] - Y[te, 1]).tolist())
    return dict(cv=np.mean(errs) if errs else None,
                span_ratio_x=pred_span_x / tgt_span_x,
                span_ratio_y=pred_span_y / tgt_span_y,
                feat_sd=float(np.mean(sd)),
                feat_range=float(np.mean(F.max(0) - F.min(0))))


def main():
    print('=' * 78)
    print('模拟：噪声（= 特征不随位置变化）如何摧毁校准')
    print('=' * 78)
    print('  noise_frac = 噪声 / 特征真实变化范围')
    print('  1.0 表示噪声与信号同量级，>1.5 表示特征几乎不携带位置信息')
    print()
    print('  %-12s %-14s %-16s %-16s %s'
          % ('noise_frac', '留一误差px', '输出跨度比x', '输出跨度比y', '含义'))
    print('  ' + '-' * 74)
    rows = []
    for nf in (0.05, 0.2, 0.5, 1.0, 1.5, 2.5):
        r = simulate(nf)
        if not r:
            continue
        rows.append((nf, r))
        cv = r['cv']
        note = ''
        if cv is not None:
            if cv < 80:
                note = '校准良好'
            elif cv < 200:
                note = '可用'
            elif cv < 450:
                note = '勉强'
            else:
                note = '★ 退化：指哪都不准'
        print('  %-12.2f %-14s %-16.2f %-16.2f %s'
              % (nf, ('%.0f' % cv) if cv else '—',
                 r['span_ratio_x'], r['span_ratio_y'], note))

    print()
    print('=' * 78)
    print('解读')
    print('=' * 78)
    print('  关键观察："输出跨度比" 会随噪声增大而塌缩 ——')
    print('  当特征几乎不随位置变化时，回归无法区分不同校准点，')
    print('  只能输出接近所有标签均值的位置（即屏幕中心）。')
    print()
    print('  这正是现场现象：lastPx=778, lastPy=548 恰好在屏幕正中，')
    print('  而使用者明显在指某个目标 —— 说明映射把几乎所有输入')
    print('  都映到了中心附近，也就是【校准退化】。')
    print()
    print('=' * 78)
    print('demo 应当自查的判据（建议加入校准完成时的检查）')
    print('=' * 78)
    print('  1. 输出跨度比 < 0.45  → 校准退化，直接报警并要求重做')
    print('     （正常应接近 1.0：标定网格铺满工作区，预测也应铺满）')
    print('  2. 点间最小距离 < 0.35 → 有校准点特征重合，重做')
    print('  3. 手在画面内 < 80%    → 采样不足，重做')
    print()
    print('  这三条任意一条不满足，那一轮校准的数据就是无效的 ——')
    print('  与其让使用者继续在无效校准上测试，不如当场要求重做。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
