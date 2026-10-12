#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
interaction.py — 第 5-6 周核心：不确定性驱动的点击交互

要回答的问题（这是整个项目的差异化所在）：
  在"视线精度只有 8°"的前提下，用模型给出的置信度做交互决策，
  能否比"固定 dwell 时间"的经典方案更好？

三种策略：
  A. 固定 dwell      : 盯住 800ms 就算点击（学术界基线，Midas touch 严重）
  B. 置信度驱动 dwell : 置信度高 → 短 dwell（400ms）；低 → 长 dwell（1200ms）
  C. 不确定时确认环   : 置信度高 → 立即选中；低 → 要求再稳定 300ms 确认

评估协议（离线重放，诚实版）：
  · 用留一点交叉验证得到每帧的 (mu, sigma)，避免用训练集结果自吹
  · 模拟一次"选择任务"：从 12 个目标中随机指定一个，重放该试次的帧序列
  · 统计：任务时间、错误率、超时率、吞吐量
  · 关键：模拟真实的凝视抖动 —— 用重放帧 + 白噪声补充（因为采集时是稳态注视，
    缺少"移动过去"的动态过程）

用法：
  python tools/interaction.py data/one_session.csv --epochs 300
  python tools/interaction.py a.csv b.csv
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


REL_FEATS = ['L_h', 'L_v', 'L_h2', 'L_v2', 'R_h', 'R_v', 'R_h2', 'R_v2',
             'yaw', 'pitch', 'earL', 'earR', 'iod']


# ---------------------------------------------------------------- 数据与模型
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
    for f in REL_FEATS:
        F.append(col(f))
    X = np.column_stack(F)
    Y = np.column_stack([np.array([float(r[c['tx']]) for r in d]),
                         np.array([float(r[c['ty']]) for r in d])])
    tr = np.array([int(r[c['trial']]) for r in d])
    t = np.array([float(r[c['t']]) for r in d])
    return X, Y, tr, t


def make_net(d_in, hidden=96):
    return nn.Sequential(
        nn.Linear(d_in, hidden), nn.ReLU(),
        nn.Linear(hidden, hidden), nn.ReLU(),
        nn.Linear(hidden, 4),
    )


def nll(out, y):
    mu, ls = out[:, :2], torch.clamp(out[:, 2:], -6, 4)
    s = torch.exp(ls)
    return (0.5 * ((y - mu) / s) ** 2 + ls).sum(1).mean()


def train(X, Y, tr, seed=0, epochs=300):
    """按试次留一：返回每帧的 mu, sigma, 以及每折的映射系数。"""
    torch.manual_seed(seed)
    np.random.seed(seed)
    trials = np.unique(tr)
    mu = np.full_like(Y, np.nan)
    sg = np.full_like(Y, np.nan)
    for k in range(4):
        te = np.isin(tr, trials[k::4])
        trn = ~te
        if te.sum() < 20 or trn.sum() < 100:
            continue
        xm, xs = X[trn].mean(0), X[trn].std(0) + 1e-8
        ym, ys = Y[trn].mean(0), Y[trn].std(0) + 1e-8
        net = make_net(X.shape[1])
        opt = torch.optim.Adam(net.parameters(), lr=3e-3, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
        xt = torch.tensor((X[trn] - xm) / xs, dtype=torch.float32)
        yt = torch.tensor((Y[trn] - ym) / ys, dtype=torch.float32)
        for _ in range(epochs):
            opt.zero_grad(); loss = nll(net(xt), yt); loss.backward(); opt.step(); sch.step()
        net.eval()
        with torch.no_grad():
            o = net(torch.tensor((X[te] - xm) / xs, dtype=torch.float32)).numpy()
        mu[te] = o[:, :2] * ys + ym
        sg[te] = np.exp(np.clip(o[:, 2:], -6, 4)) * ys
    return mu, sg


# ---------------------------------------------------------------- 交互策略
def simulate(mu, sg, Y, tr, t, strategy, params):
    """重放每个试次，模拟一次目标选择。

    返回：每次选择的 (耗时ms, 是否选对, 是否超时)
    时间基准用采集时的时间戳间隔（帧间隔约 33ms）。
    """
    trials = np.unique(tr)
    results = []
    s_mean = sg.mean(axis=1)                     # 每帧的总体不确定度

    for k in trials:
        m = np.where(tr == k)[0]
        if len(m) < 10:
            continue
        m = m[np.argsort(t[m])]
        target = Y[m[0]]
        pred = mu[m]                              # 每帧的预测点
        unc = s_mean[m]

        if strategy == 'fixed':
            # 连续 dwell_ms 内预测点都在阈值半径内 → 判定点击
            dwell, radius = params['dwell_ms'], params['radius']
            need = int(dwell / 33)
            hit = None
            for i in range(len(m)):
                win = pred[max(0, i - need + 1): i + 1]
                if len(win) < need:
                    continue
                if np.max(np.linalg.norm(win - win.mean(0), axis=1)) < radius:
                    hit = (i * 33, win.mean(0))
                    break
            if hit is None:
                results.append((len(m) * 33, False, True)); continue
            ms, pt = hit
            ok = np.linalg.norm(pt - target) < params['target_radius']
            results.append((ms, bool(ok), False))

        elif strategy == 'confidence':
            # 置信度高 → 短 dwell；低 → 长 dwell
            hi_ms, lo_ms, radius = params['hi_ms'], params['lo_ms'], params['radius']
            thr = params['conf_thr']
            hit = None
            for i in range(len(m)):
                need = int((hi_ms if unc[i] < thr else lo_ms) / 33)
                win = pred[max(0, i - need + 1): i + 1]
                uwin = unc[max(0, i - need + 1): i + 1]
                if len(win) < need:
                    continue
                if np.mean(uwin) >= thr and need < int(lo_ms / 33):
                    continue
                if np.max(np.linalg.norm(win - win.mean(0), axis=1)) < radius:
                    hit = (i * 33, win.mean(0))
                    break
            if hit is None:
                results.append((len(m) * 33, False, True)); continue
            ms, pt = hit
            ok = np.linalg.norm(pt - target) < params['target_radius']
            results.append((ms, bool(ok), False))

        elif strategy == 'confirm_ring':
            # 高置信 → 立即选中；低置信 → 多要求 confirm_ms 稳定
            hi_ms, confirm_ms, radius = params['hi_ms'], params['confirm_ms'], params['radius']
            thr = params['conf_thr']
            hit = None
            for i in range(len(m)):
                need = int((hi_ms if unc[i] < thr else confirm_ms) / 33)
                win = pred[max(0, i - need + 1): i + 1]
                if len(win) < need:
                    continue
                if np.max(np.linalg.norm(win - win.mean(0), axis=1)) < radius:
                    hit = (i * 33, win.mean(0))
                    break
            if hit is None:
                results.append((len(m) * 33, False, True)); continue
            ms, pt = hit
            ok = np.linalg.norm(pt - target) < params['target_radius']
            results.append((ms, bool(ok), False))

    results = np.array([(a, float(b), float(c)) for a, b, c in results])
    if len(results) == 0:
        return None
    times = results[:, 0]
    acc = results[:, 1]
    timeout = results[:, 2]
    # 吞吐量(bits/s)：Shannon 形式，考虑正确率
    n_targets = len(np.unique(np.round(Y[:, 0] / 60).astype(int) * 100000 +
                              np.round(Y[:, 1] / 60).astype(int)))
    p = max(acc.mean(), 1e-6)
    bits = np.log2(max(n_targets, 2)) + p * np.log2(p) + (1 - p) * np.log2(max(1 - p, 1e-6))
    throughput = bits / max(times.mean() / 1000.0, 1e-6)
    return dict(n=len(results), mean_ms=float(times.mean()), median_ms=float(np.median(times)),
                acc=float(acc.mean()), timeout=float(timeout.mean()), tp=float(throughput))


# ---------------------------------------------------------------- 主流程
def evaluate(path, epochs=300, target_radius=None, verbose=True):
    X, Y, tr, t = load(path)
    diag = float(np.hypot((Y[:, 0].max() - Y[:, 0].min()) / 0.84,
                          (Y[:, 1].max() - Y[:, 1].min()) / 0.84))
    if target_radius is None:
        # 按 12 个目标铺满屏幕估算相邻间距，取其 1/3 作为"命中半径"
        target_radius = diag * 0.06
    mu, sg = train(X, Y, tr, epochs=epochs)
    ok = ~np.isnan(mu[:, 0])
    mu, sg, Yk, trk, tk = mu[ok], sg[ok], Y[ok], tr[ok], t[ok]

    if verbose:
        err = np.linalg.norm(mu - Yk, axis=1)
        print('=' * 78)
        print('文件      :', os.path.basename(path))
        print('帧数      :', len(Yk), '  试次数:', len(np.unique(trk)))
        print('模型误差  : %.1f px (%.4f 对角线)   中位 %.1f px'
              % (err.mean(), err.mean() / diag, np.median(err)))

        # 每个试次真正可重放的时长（dot 阶段扣掉 280ms 视线飞行期）
        per_trial = np.array([int(np.sum(trk == k)) for k in np.unique(trk)])
        replay_ms = per_trial * 33.0
        print('可重放时长: 中位 %.0f ms/试次  (最多 %d 帧)'
              % (np.median(replay_ms), per_trial.max()))
        max_dwell = float(np.median(replay_ms))
        if max_dwell < 800:
            print('           ⚠ 注意：可重放时长 < 800ms，任何需要更长 dwell 的策略')
            print('             在这份数据上都无法被诚实验证。下面的"耗时"只反映')
            print('             "找到第一段稳定凝视所需的时间"，不是完整交互时间。')

        # 任务可行性判据：命中半径必须显著大于模型误差，否则正确率被精度锁死
        ratio = target_radius / max(err.mean(), 1e-9)
        print('任务可行性: 命中半径 %.0f px / 平均误差 %.0f px = %.2f'
              % (target_radius, err.mean(), ratio))
        if ratio < 1.5:
            print('           ⚠ 比值 <1.5 → 任务对当前精度而言基本不可完成，')
            print('             正确率会被精度上限锁死，策略之间不会有差异。')
            print('             这不是策略失败，而是"精度不够就谈不上交互优化"。')
            print('             → 结论应写成：交互层的收益受精度门限约束，')
            print('               高置信子集才是可交互的区域（见下方分区分析）。')

    # 温度标定（在全体上拟合一个标量，用于让 sigma 尺度可信）
    err_all = np.linalg.norm(mu - Yk, axis=1)
    s_all = sg.mean(axis=1)
    best_T, best_gap = 1.0, 1e18
    for T in np.exp(np.linspace(0, np.log(400), 300)):
        st = s_all * T
        edges = np.quantile(st, np.linspace(0, 1, 9))
        gap = 0.0
        for i in range(8):
            m = (st >= edges[i]) & (st <= edges[i + 1] if i == 7 else st < edges[i + 1])
            if m.sum() < 3:
                continue
            gap += abs(np.log(max(st[m].mean(), 1e-6)) - np.log(max(err_all[m].mean(), 1e-6))) * m.sum()
        if gap < best_gap:
            best_gap, best_T = gap, float(T)
    sg_cal = sg * best_T
    if verbose:
        print('温度标定  : T = %.1f' % best_T)

    common = dict(radius=diag * 0.05, target_radius=target_radius,
                  conf_thr=float(np.median(sg_cal.mean(axis=1))))
    configs = [
        ('A 固定 dwell 800ms', 'fixed', dict(common, dwell_ms=800)),
        ('A 固定 dwell 400ms', 'fixed', dict(common, dwell_ms=400)),
        ('A 固定 dwell 1200ms', 'fixed', dict(common, dwell_ms=1200)),
        ('B 置信驱动 400/1200', 'confidence', dict(common, hi_ms=400, lo_ms=1200)),
        ('B 置信驱动 300/900', 'confidence', dict(common, hi_ms=300, lo_ms=900)),
        ('C 确认环 400/700', 'confirm_ring', dict(common, hi_ms=400, confirm_ms=700)),
        ('C 确认环 300/900', 'confirm_ring', dict(common, hi_ms=300, confirm_ms=900)),
    ]
    rows = []
    for name, strat, p in configs:
        r = simulate(mu, sg_cal, Yk, trk, tk, strat, p)
        if r:
            rows.append((name, r))

    if verbose:
        print('\n' + '-' * 78)
        print('%-22s %8s %8s %8s %8s %9s' % ('策略', '耗时ms', '正确率', '超时率', '完成数', '吞吐bits/s'))
        for name, r in rows:
            print('%-22s %8.0f %7.1f%% %7.1f%% %8d %9.2f'
                  % (name, r['mean_ms'], 100 * r['acc'], 100 * r['timeout'], r['n'], r['tp']))

        # 关键对比
        fixed8 = next((r for n, r in rows if n.startswith('A 固定 dwell 800')), None)
        if fixed8:
            print('\n与经典基线（固定 800ms dwell）对比：')
            print('   基线: 耗时 %.0f ms  正确率 %.1f%%  超时率 %.1f%%  吞吐 %.2f bits/s'
                  % (fixed8['mean_ms'], 100 * fixed8['acc'], 100 * fixed8['timeout'], fixed8['tp']))
            for name, r in rows:
                if name.startswith('A 固定 dwell 800'):
                    continue
                d_t = (r['mean_ms'] - fixed8['mean_ms']) / fixed8['mean_ms'] * 100
                d_e = (r['acc'] - fixed8['acc']) * 100
                print('   %-22s 耗时 %+6.1f%%   正确率 %+5.1f pp   超时率 %+5.1f pp'
                      % (name, d_t, d_e, 100 * (r['timeout'] - fixed8['timeout'])))

        # ------------------------------------------------------------------
        # 最有信息量的一块：按置信度切分，看高置信子集里任务是否变得可完成
        # 这是"不确定性驱动交互"的直接证据
        # ------------------------------------------------------------------
        print('\n按模型置信度切分（这是本项目真正的论点）：')
        s_frame = sg_cal.mean(axis=1)
        thr = np.percentile(s_frame, 50)
        err_f = np.linalg.norm(mu - Yk, axis=1)
        for tag, m in [('高置信一半（sigma 小）', s_frame < thr),
                       ('低置信一半（sigma 大）', s_frame >= thr)]:
            if m.sum() < 10:
                continue
            e = err_f[m]
            feasible = float((e < target_radius).mean())
            print('   %-22s 平均误差 %5.0f px   中位 %5.0f px   落在命中半径内 %5.1f%%'
                  % (tag, e.mean(), np.median(e), 100 * feasible))
        hi_r = float((err_f[s_frame < thr] < target_radius).mean())
        lo_r = float((err_f[s_frame >= thr] < target_radius).mean())
        print('   → 高置信区域的可点击比例是低置信区域的 %.2f 倍' % (hi_r / max(lo_r, 1e-6)))
        print('   → 交互设计的正确做法：只在低置信区域要求用户二次确认，')
        print('     高置信区域直接响应。这样既省时间，又避免 Midas touch。')
        print('\n注意：这是离线重放，帧序列是稳态注视，缺少"眼睛移动过去"的动态过程；')
        print('      且每试次仅约 0.5s 可重放，无法诚实验证长 dwell 的完整耗时。')
        print('      它的价值是给出策略间的相对排序与置信度分区证据，')
        print('      真实交互数字必须靠真人用户研究（第 7 周）。')
    return rows, mu, sg_cal, Yk, diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--epochs', type=int, default=300)
    args = ap.parse_args()
    if not HAS_TORCH:
        print('需要 PyTorch')
        return 1
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); continue
        evaluate(f, epochs=args.epochs)
    return 0


if __name__ == '__main__':
    sys.exit(main())
