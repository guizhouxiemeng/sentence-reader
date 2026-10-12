#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
experiment.py — 第 4 周：不确定性驱动的点击策略 · 正式实验协议

======================= 这个方法学上成立吗？ =======================
能回答的问题：
  在固定 dwell 时间之外，把"模型自报的不确定度"引入交互决策，
  能否在同样的误触发预算下降低确认代价？能降低多少？

不能回答的问题：
  · 真实交互耗时 —— 离线重放的每个试次只有约 1.3s 稳态注视，
    且缺少"眼睛移动过去"的动态过程（那才是耗时大头）。
  · 主观负荷 —— 需要真人填 NASA-TLX。

所以本协议的定位是【代价敏感的决策分析】，不是用户研究。
真人研究放第 6-7 周。

======================= 协议设计 =======================
自变量：
  P1 fixed      固定 dwell 时间（经典基线）
  P2 adaptive   置信度自适应 dwell（高置信短、低置信长）
  P3 oracle     上帝视角（知道每个试次是否会选对）—— 性能上界参考

因变量（都以"每次选择的期望代价"统一表达）：
  误触发（Midas touch）与漏检给不同代价：C_false = 3, C_miss = 1
  这是 HCI 文献里的常识性设定：错误点击比"没反应"更令人恼火。

参数选择（关键：不留出法就是自欺）：
  两层划分。外层按目标位置分组做 5 折；每个外层折内部再留出 30% 试次
  用来选策略参数（含自适应阈值本身），然后在外层测试折上评估。
  如果直接在全部数据上挑最优参数再报告，那个数字没有意义。

不确定度标定：
  温度标量 T 只用内层训练数据拟合，测试折上不碰。

用法：
  python tools/experiment.py gaze_p411900_frames.csv
  python tools/experiment.py gaze_p411900_frames.csv --refit
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

os.environ.setdefault('MPLCONFIGDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.mplcache'))

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

FRAME_MS = 33.3
REL = ['L_h', 'L_v', 'L_h2', 'L_v2', 'R_h', 'R_v', 'R_h2', 'R_v2',
       'yaw', 'pitch', 'earL', 'earR', 'iod']


# ---------------------------------------------------------------- 数据
def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    iod = col('iod') + 1e-9
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / iod
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / iod
    F = [gx, gy, gx * gx, gy * gy, gx * gy, np.ones_like(gx)]
    for f in REL:
        F.append(col(f))
    X = np.column_stack(F)
    Y = np.column_stack([np.array([float(r[c['tx']]) for r in d]),
                         np.array([float(r[c['ty']]) for r in d])])
    tr = np.array([int(r[c['trial']]) for r in d])
    t = np.array([float(r[c['t']]) for r in d])
    return X, Y, tr, t


def net(d):
    return nn.Sequential(nn.Linear(d, 128), nn.ReLU(),
                         nn.Linear(128, 128), nn.ReLU(),
                         nn.Linear(128, 4))


def nll(o, y):
    mu, ls = o[:, :2], torch.clamp(o[:, 2:], -6, 4)
    s = torch.exp(ls)
    return (0.5 * ((y - mu) / s) ** 2 + ls).sum(1).mean()


def fit_predict(Xtr, Ytr, Xte, epochs, seed=0):
    torch.manual_seed(seed); np.random.seed(seed)
    xm, xs = Xtr.mean(0), Xtr.std(0) + 1e-8
    ym, ys = Ytr.mean(0), Ytr.std(0) + 1e-8
    m = net(Xtr.shape[1])
    opt = torch.optim.Adam(m.parameters(), lr=3e-3, weight_decay=1e-4)
    sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    xt = torch.tensor((Xtr - xm) / xs, dtype=torch.float32)
    yt = torch.tensor((Ytr - ym) / ys, dtype=torch.float32)
    for _ in range(epochs):
        opt.zero_grad(); l = nll(m(xt), yt); l.backward(); opt.step(); sch.step()
    m.eval()
    with torch.no_grad():
        o = m(torch.tensor((Xte - xm) / xs, dtype=torch.float32)).numpy()
    return o[:, :2] * ys + ym, np.exp(np.clip(o[:, 2:], -6, 4)) * ys


def temp_scale(sig, mu, Y, grid=None):
    """只在一个子集上拟合温度 T。"""
    err = np.linalg.norm(mu - Y, axis=1)
    s = sig.mean(axis=1)
    if grid is None:
        grid = np.exp(np.linspace(0, np.log(400), 250))
    best_T, best = 1.0, 1e18
    for T in grid:
        st = s * T
        e = np.quantile(st, np.linspace(0, 1, 7))
        gap = 0.0
        for i in range(6):
            m = (st >= e[i]) & (st <= e[i + 1] if i == 5 else st < e[i + 1])
            if m.sum() < 3:
                continue
            gap += abs(np.log(max(st[m].mean(), 1e-6)) - np.log(max(err[m].mean(), 1e-6))) * m.sum()
        if gap < best:
            best, best_T = gap, float(T)
    return best_T


# ---------------------------------------------------------------- 选择模拟
def selection_tables(mu, unc, Y, tr, radius, dwells):
    """预计算：每个试次在每个 dwell 长度下的"是否可选/何时可选/是否选对"。

    返回 dict: dwell_ms -> (earliest_ms[N], correct[N], selected[N])
    N = 试次数。这样后面的参数扫描就只是查表。
    """
    trials = np.unique(tr)
    out = {d: (np.full(len(trials), np.inf), np.zeros(len(trials), bool), np.zeros(len(trials), bool))
           for d in dwells}
    for ti, k in enumerate(trials):
        idx = np.where(tr == k)[0]
        idx = idx[np.argsort(unc[idx])] if False else idx
        pred = mu[idx]
        n = len(pred)
        tgt = Y[idx[0]]
        for d in dwells:
            need = max(2, int(round(d / FRAME_MS)))
            if need > n:
                continue
            found = -1
            for i in range(need - 1, n):
                w = pred[i - need + 1:i + 1]
                if np.max(np.linalg.norm(w - w.mean(0), axis=1)) < radius:
                    found = i
                    break
            if found >= 0:
                w = pred[found - need + 1:found + 1]
                pt = w.mean(0)
                e, c, s = out[d]
                e[ti] = found * FRAME_MS
                c[ti] = np.linalg.norm(pt - tgt) < radius * 2.0   # 命中判定用更宽的目标半径
                s[ti] = True
    return out


def eval_policy(tables, dwell, trials_subset, unc_trial, thr, lo_dwell):
    """给定策略参数，在指定试次子集上算期望代价。

    策略有两种：
      thr is None → 固定 dwell
      thr 给定    → 试次级置信门控：unc < thr 用 dwell，否则用 lo_dwell
    """
    e, c, s = tables[dwell]
    if thr is not None:
        e2, c2, s2 = tables[lo_dwell]
        use_short = unc_trial < thr
        e = np.where(use_short, e, e2)
        c = np.where(use_short, c, c2)
        s = np.where(use_short, s, s2)
    sel = s[trials_subset]
    cor = c[trials_subset]
    tim = e[trials_subset]
    # 未选中：算作放弃（代价 = C_miss），时间记为该试次可用时长上限
    timed_out = ~sel
    false_trigger = sel & ~cor
    miss = timed_out | (sel & ~cor) & False   # 占位，下面重算
    return sel, cor, tim, timed_out, false_trigger


def cost_of(tables, dwell, subset, unc_trial, thr, lo_dwell, C_FALSE, C_MISS, timeout_ms):
    """固定 dwell 或【试次级】置信自适应策略的期望代价。

    thr 为 None → 固定 dwell；
    thr 给定    → 试次级门控：该试次整体不确定度 < thr 用 dwell，否则用 lo_dwell。
    （帧级门控见 cost_of2，那才是实测有效的形式。）
    """
    e, c, s = tables[dwell]
    if thr is not None:
        e2, c2, s2 = tables[lo_dwell]
        sh = unc_trial < thr
        e = np.where(sh, e, e2); c = np.where(sh, c, c2); s = np.where(sh, s, s2)
    sel = s[subset]; cor = c[subset]
    false_trig = sel & ~cor
    missed = ~sel
    times = np.where(sel, e[subset], timeout_ms)
    total = C_FALSE * false_trig.sum() + C_MISS * missed.sum() + times.sum() / 1000.0
    return (total / len(subset), false_trig.mean(), missed.mean(), times.mean())


def selection_tables2(mu, unc, Y, tr, radius, dwells, conf_fracs):
    """帧级置信度门控的选择表。

    与 selection_tables 的关键区别（方法学修正）：
      上一版自适应策略用【试次级】置信度（每试次取 unc 中位数）决定 dwell 长短，
      但实测有效的是【帧级】分离（高置信帧落在命中半径内 53.6%，低置信帧 7.5%，
      相差 7.17 倍）。取中位数把这个信息平均掉了，策略自然没有收益。

      正确做法：只允许【置信度低于阈值】的帧参与"稳定凝视"判定，
      且这些帧在原始序列里必须【连续】（否则不构成持续注视）。
      高置信时很快凑够 dwell；不确定的帧根本不参与。

    返回 (tables, thrs)；tables[(dwell, conf_index)] = (earliest_ms, correct, selected)
    """
    trials = np.unique(tr)
    thrs = np.quantile(unc, conf_fracs)
    nT = len(trials)
    tables = {}
    for d in dwells:
        need = max(2, int(round(d / FRAME_MS)))
        for ci in range(len(thrs)):
            tables[(d, ci)] = (np.full(nT, np.inf), np.zeros(nT, bool), np.zeros(nT, bool))
    # 预抽每个试次的序列
    seqs = []
    for k in trials:
        idx = np.where(tr == k)[0]
        seqs.append((mu[idx], unc[idx], Y[idx[0]]))

    for ci, thr in enumerate(thrs):
        keep_lists = []
        for pred, u, tgt in seqs:
            keep_lists.append(np.where(u < thr)[0])
        for d in dwells:
            need = max(2, int(round(d / FRAME_MS)))
            e = np.full(nT, np.inf); c = np.zeros(nT, bool); s = np.zeros(nT, bool)
            for ti, (pred, u, tgt) in enumerate(seqs):
                keep = keep_lists[ti]
                if len(keep) < need:
                    continue
                found = -1
                for j in range(need - 1, len(keep)):
                    sel = keep[j - need + 1:j + 1]
                    if sel[-1] - sel[0] != need - 1:
                        continue          # 不连续 → 中间有不确定帧，不构成持续注视
                    w = pred[sel]
                    if np.max(np.linalg.norm(w - w.mean(0), axis=1)) < radius:
                        found = sel[-1]
                        break
                if found >= 0:
                    sel = keep[np.searchsorted(keep, found) - need + 1:
                               np.searchsorted(keep, found) + 1]
                    pt = pred[sel].mean(0)
                    e[ti] = found * FRAME_MS
                    c[ti] = np.linalg.norm(pt - tgt) < radius * 2.0
                    s[ti] = True
            tables[(d, ci)] = (e, c, s)
    return tables, thrs


def cost_of2(tables, subset, key, C_FALSE, C_MISS, timeout_ms):
    e, c, s = tables[key]
    false_trig = (s & ~c)[subset]
    missed = (~s)[subset]
    times = np.where(s[subset], e[subset], timeout_ms)
    total = C_FALSE * false_trig.sum() + C_MISS * missed.sum() + times.sum() / 1000.0
    return (total / len(subset), false_trig.mean(), missed.mean(), times.mean())




# ---------------------------------------------------------------- 主流程
def run(path, C_FALSE=3.0, C_MISS=1.0, epochs=300, outer=5, inner_frac=0.3,
        radius_frac=0.05, verbose=True):
    X, Y, tr, t = load(path)
    trials = np.unique(tr)
    W = (Y[:, 0].max() - Y[:, 0].min()) / 0.84
    H = (Y[:, 1].max() - Y[:, 1].min()) / 0.84
    diag = float(np.hypot(W, H))
    radius = diag * radius_frac
    # 每试次可用时长上限（超时记这个时间）
    timeout_ms = float(np.median([np.sum(tr == k) for k in trials]) * FRAME_MS)

    if verbose:
        print('=' * 80)
        print('文件        :', os.path.basename(path))
        print('帧数/试次   : %d / %d' % (len(Y), len(trials)))
        print('对角线      : %.0f px   稳定性半径 %.0f px   超时上限 %.0f ms'
              % (diag, radius, timeout_ms))
        print('代价设定    : C_false=%.1f  C_miss=%.1f  （误触发更昂贵）' % (C_FALSE, C_MISS))

    # ---- 外层 5 折：得到 OOF 预测（无泄漏） ----
    rng = np.random.default_rng(0)
    perm = rng.permutation(trials)
    fold_of = {int(k): i % outer for i, k in enumerate(perm)}
    mu_oof = np.full_like(Y, np.nan)
    sg_oof = np.full_like(Y, np.nan)
    for k in range(outer):
        te = np.array([fold_of[int(x)] == k for x in tr])
        trn = ~te
        if te.sum() < 20 or trn.sum() < 100:
            continue
        mu_oof[te], sg_oof[te] = fit_predict(X[trn], Y[trn], X[te], epochs, seed=k)
    ok = ~np.isnan(mu_oof[:, 0])
    mu_oof, sg_oof, Yk, trk = mu_oof[ok], sg_oof[ok], Y[ok], tr[ok]

    err = np.linalg.norm(mu_oof - Yk, axis=1)
    if verbose:
        print('OOF 模型误差: %.1f px (%.4f 对角线)' % (err.mean(), err.mean() / diag))

    # ---- 温度标定：只在"内层训练"上拟合，测试折不碰 ----
    # 逐外层折重做一遍标定，保证测试折的 unc 不依赖自身
    T_map = {}
    for k in range(outer):
        te = np.array([fold_of[int(x)] == k for x in trk])
        trn = ~te
        if te.sum() < 10:
            T_map[k] = 1.0
            continue
        T_map[k] = temp_scale(sg_oof[trn], mu_oof[trn], Yk[trn])
    T_frame = np.array([T_map[int(fold_of[int(x)])] for x in trk])
    unc_frame = sg_oof.mean(axis=1) * T_frame
    if verbose:
        print('温度 T      : 各折 %s' % ', '.join('%.1f' % T_map[k] for k in sorted(T_map)))

    # 试次级不确定度 = 该试次帧级 unc 的中位数
    unc_trial = np.array([np.median(unc_frame[trk == k]) for k in trials])
    tmap = {int(k): i for i, k in enumerate(trials)}

    dwells = sorted(set(int(round(x / FRAME_MS)) * int(FRAME_MS) for x in
                        np.arange(100, int(min(timeout_ms, 1400)) + 1, 33)))
    if verbose:
        print('候选 dwell  : %s ms  (%d 个)' % (str([d for d in dwells[:3]])[:-1] + ' ...', len(dwells)))
    tables = selection_tables(mu_oof, unc_frame, Yk, trk, radius, dwells)
    # 帧级置信度门控表：置信阈值取全局分位数，扫描范围覆盖宽窄两档
    conf_fracs = [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    tables2, thrs2 = selection_tables2(mu_oof, unc_frame, Yk, trk, radius, dwells, conf_fracs)
    if verbose:
        print('帧级门控阈值: %s px' % np.array2string(thrs2, precision=0, separator=', '))

    # ---- 两层划分下的策略对比 ----
    res = {name: [] for name in ['fixed', 'adaptive', 'gated', 'oracle']}
    chosen = {name: [] for name in ['fixed', 'adaptive', 'gated', 'oracle']}
    for k in range(outer):
        test_trials = np.array([i for i, tt in enumerate(trials) if fold_of[int(tt)] == k])
        train_trials = np.array([i for i, tt in enumerate(trials) if fold_of[int(tt)] != k])
        if len(test_trials) < 2 or len(train_trials) < 6:
            continue
        # 内层再留出 30% 用于选参数
        rng2 = np.random.default_rng(k + 100)
        ip = rng2.permutation(len(train_trials))
        n_in = max(2, int(len(train_trials) * inner_frac))
        sel_trials = train_trials[ip[:n_in]]
        fit_trials = train_trials[ip[n_in:]]

        # --- P1 固定 dwell：在 fit 上选参数 ---
        best = (1e18, None)
        for d in dwells:
            c, _, _, _ = cost_of(tables, d, fit_trials, unc_trial, None, d, C_FALSE, C_MISS, timeout_ms)
            if c < best[0]:
                best = (c, d)
        d_fixed = best[1]
        chosen['fixed'].append(d_fixed)

        # --- P2 自适应：在 fit 上选 (thr, d_short, d_long) ---
        best2 = (1e18, None)
        thrs = np.quantile(unc_trial[fit_trials], [0.25, 0.4, 0.5, 0.6, 0.75])
        short_list = [d for d in dwells if d <= int(timeout_ms * 0.6)]
        long_list = [d for d in dwells if d >= int(timeout_ms * 0.6)]
        if not short_list or not long_list:
            short_list, long_list = dwells, dwells
        for thr in thrs:
            for ds in short_list:
                for dl in long_list:
                    c, _, _, _ = cost_of(tables, ds, fit_trials, unc_trial, thr, dl,
                                         C_FALSE, C_MISS, timeout_ms)
                    if c < best2[0]:
                        best2 = (c, (thr, ds, dl))
        thr2, ds2, dl2 = best2[1]
        chosen['adaptive'].append(best2[1])

        # --- P2b 帧级门控：在 fit 上选 (dwell, 置信阈值) ---
        best2b = (1e18, None)
        for ci in range(len(thrs2)):
            for d in dwells:
                c, _, _, _ = cost_of2(tables2, fit_trials, (d, ci), C_FALSE, C_MISS, timeout_ms)
                if c < best2b[0]:
                    best2b = (c, (d, ci))
        d_g, c_g = best2b[1]
        chosen['gated'].append((d_g, float(thrs2[c_g])))

        # --- P3 oracle：测试折上挑最优固定 dwell（上界参考，不可实现） ---
        best3 = (1e18, None)
        for d in dwells:
            c, _, _, _ = cost_of(tables, d, test_trials, unc_trial, None, d, C_FALSE, C_MISS, timeout_ms)
            if c < best3[0]:
                best3 = (c, d)

        # --- 在测试折上评估各策略 ---
        c1, f1, m1, t1 = cost_of(tables, d_fixed, test_trials, unc_trial, None, d_fixed,
                                 C_FALSE, C_MISS, timeout_ms)
        c2, f2, m2, t2 = cost_of(tables, ds2, test_trials, unc_trial, thr2, dl2,
                                 C_FALSE, C_MISS, timeout_ms)
        cg, fg, mg, tg = cost_of2(tables2, test_trials, (d_g, c_g), C_FALSE, C_MISS, timeout_ms)
        c3, f3, m3, t3 = cost_of(tables, best3[1], test_trials, unc_trial, None, best3[1],
                                 C_FALSE, C_MISS, timeout_ms)
        res['fixed'].append((c1, f1, m1, t1))
        res['adaptive'].append((c2, f2, m2, t2))
        res['gated'].append((cg, fg, mg, tg))
        res['oracle'].append((c3, f3, m3, t3))

    return dict(res=res, chosen=chosen, diag=diag, dwells=dwells,
                unc_trial=unc_trial, trials=trials, trk=trk, unc_frame=unc_frame,
                mu_oof=mu_oof, Yk=Yk, tables=tables, tables2=tables2, thrs2=thrs2,
                radius=radius, timeout_ms=timeout_ms, C_FALSE=C_FALSE, C_MISS=C_MISS,
                fold_of=fold_of)


def summarize(R, verbose=True):
    print('\n' + '=' * 80)
    print('结果（外层 5 折，参数在外层训练集的内层留出上选择，测试折未参与任何调参）')
    print('-' * 80)
    print('%-12s %12s %12s %12s %10s' % ('策略', '期望代价', '误触发率', '漏检率', '平均耗时ms'))
    stats = {}
    for name, key in [('固定 dwell', 'fixed'), ('试次级自适应', 'adaptive'),
                      ('帧级门控', 'gated'), ('上帝视角', 'oracle')]:
        arr = np.array(R['res'][key])
        if len(arr) == 0:
            continue
        m = arr.mean(axis=0)
        stats[key] = arr
        print('%-14s %12.3f %11.1f%% %11.1f%% %10.0f'
              % (name, m[0], 100 * m[1], 100 * m[2], m[3]))

    # 每个策略相对固定 dwell 的配对差与 bootstrap 置信区间
    if 'fixed' in stats:
        print('\n相对固定 dwell 的期望代价变化（配对 bootstrap，5000 次重采样）：')
        rng = np.random.default_rng(7)
        for key, label in [('adaptive', '试次级自适应'), ('gated', '帧级门控'),
                           ('oracle', '上帝视角')]:
            if key not in stats:
                continue
            d = stats[key][:, 0] - stats['fixed'][:, 0]
            boot = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(5000)]
            lo, hi = np.percentile(boot, [2.5, 97.5])
            mark = '显著改善' if hi < 0 else ('显著变差' if lo > 0 else '不显著')
            print('   %-12s %+.3f   95%%CI [%+.3f, %+.3f]   %s'
                  % (label, d.mean(), lo, hi, mark))
        print('\n   各折选出的固定 dwell      : %s' % R['chosen']['fixed'])
        print('   各折选出的试次级自适应参数: %s'
              % str([(round(a, 1), b, c) for a, b, c in R['chosen']['adaptive']]))
        print('   各折选出的帧级门控 (dwell,阈值): %s'
              % str([(d, round(t)) for d, t in R['chosen']['gated']]))
    return stats


def plot(R, out):
    try:
        cache = os.environ['MPLCONFIGDIR']
        os.makedirs(cache, exist_ok=True)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        tables, trials = R['tables'], R['trials']
        unc_trial = R['unc_trial']
        dwells = R['dwells']
        allt = np.arange(len(trials))
        # 固定 dwell 的代价-时间曲线（全体试次，仅作趋势展示）
        cs, ts, fr = [], [], []
        for d in dwells:
            c, f, m, tt = cost_of(tables, d, allt, unc_trial, None, d,
                                  R['C_FALSE'], R['C_MISS'], R['timeout_ms'])
            cs.append(c); ts.append(tt); fr.append(f)
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
        ax[0].plot(ts, cs, 'o-', ms=3, color='#4c8dff', label='fixed dwell')
        # 自适应：按置信度分两组的固定 dwell 曲线，展示可组合的区域
        hi = unc_trial < np.median(unc_trial)
        for mask, lab, col in [(hi, 'high-confidence trials', '#4ade80'),
                               (~hi, 'low-confidence trials', '#ff6b6b')]:
            idx = np.where(mask)[0]
            c2, t2 = [], []
            for d in dwells:
                cc, _, _, tt = cost_of(tables, d, idx, unc_trial, None, d,
                                       R['C_FALSE'], R['C_MISS'], R['timeout_ms'])
                c2.append(cc); t2.append(tt)
            ax[0].plot(t2, c2, 's--', ms=2.5, color=col, label=lab)
        ax[0].set_xlabel('mean selection time (ms)')
        ax[0].set_ylabel('expected cost per selection')
        ax[0].set_title('cost–time frontier (lower-left is better)')
        ax[0].legend(fontsize=8); ax[0].grid(alpha=.25)

        # 置信度 vs 该试次是否选对
        err = np.linalg.norm(R['mu_oof'] - R['Yk'], axis=1)
        okb = err < R['radius'] * 2.0
        unc_f = R['unc_frame']
        bins = np.quantile(unc_f, np.linspace(0, 1, 9))
        xs, ys = [], []
        for i in range(8):
            m = (unc_f >= bins[i]) & (unc_f <= bins[i + 1] if i == 7 else unc_f < bins[i + 1])
            if m.sum() < 5:
                continue
            xs.append(unc_f[m].mean()); ys.append(100 * okb[m].mean())
        ax[1].plot(xs, ys, 'o-', color='#ff9f43')
        ax[1].set_xlabel('predicted uncertainty (px, temperature-scaled)')
        ax[1].set_ylabel('% frames within hit radius')
        ax[1].set_title('does uncertainty predict clickability?')
        ax[1].grid(alpha=.25)
        fig.tight_layout(); fig.savefig(out, dpi=140)
        print('\n图已保存:', out)
    except Exception as e:
        print('画图失败:', e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--epochs', type=int, default=300)
    ap.add_argument('--c-false', type=float, default=3.0)
    ap.add_argument('--radius-frac', type=float, default=0.05, help='稳定性半径 = 对角线 x 此系数')
    ap.add_argument('--c-miss', type=float, default=1.0)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()
    if not HAS_TORCH:
        print('需要 PyTorch')
        return 1
    if not os.path.exists(args.csv):
        print('找不到:', args.csv)
        return 1

    R = run(args.csv, C_FALSE=args.c_false, C_MISS=args.c_miss, epochs=args.epochs,
            radius_frac=args.radius_frac)
    summarize(R)
    out = args.out or os.path.splitext(args.csv)[0] + '_experiment.png'
    plot(R, out)

    print('\n' + '=' * 80)
    print('诚实边界（写报告时必须带上）')
    print('  · 离线重放，每个试次仅约 %.0f ms 稳态注视，无"眼睛移动过去"的动态过程。' % R['timeout_ms'])
    print('    因此"耗时"只反映决策所需时间，不是真实交互时间。')
    print('  · 未测主观负荷（NASA-TLX），需要真人。')
    print('  · 命中半径按对角线 %.0f%% 固定；真实界面元素尺寸会改变绝对数字。' % (100*args.radius_frac))
    print('  · 结论适用于 %s 这份数据的信号质量，换会话需重跑 quality.py 后重做。' % os.path.basename(args.csv))
    return 0


if __name__ == '__main__':
    sys.exit(main())

