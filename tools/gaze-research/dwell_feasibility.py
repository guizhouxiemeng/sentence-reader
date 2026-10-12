#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
dwell_feasibility.py — "停留时长"能不能作为可靠信号？（用已有数据，不需要新采集）

背景
----
"注意力预测层"的三条信号是：停留时长（相对值）、回看次数、扫视方向。
其中【停留时长】是最核心的一条 —— 它决定"处理受阻"能不能被检测到。

但停留时长的可靠性依赖一个前提：
    当使用者盯着同一个区域不动时，预测出的位置是否足够稳定？
如果同一区域内预测位置到处乱跳，那"停留多长时间"就无法估计 ——
视线会不断"离开"又"回来"，每次都是假的进入/离开事件。

已有数据正好能测这个
--------------------
data 里每个 trial 是【注视一个固定目标】（4x3 网格 x 3 轮 = 36 trial，
共 4147 帧）。同一 trial 内目标不变，所以预测位置的帧间离散度
就是"凝视噪声"的直接测量 —— 不需要设计新实验。

本脚本回答四个问题
------------------
  1. 凝视噪声有多大（帧间标准差），与区域尺寸相比是什么量级
  2. 在给定区域尺寸下，误判"离开"的频率有多高（假的进入/离开事件）
  3. 要区分"短看"和"长看"两种行为，各需要多少样本
  4. 由此给出可执行的阈值与窗口长度建议

用法： python tools/dwell_feasibility.py
"""
import csv
import math
import sys
from collections import defaultdict

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 相对路径 —— 从仓库根目录运行即可。
#  原来写死成本机绝对路径，只在作者本机能跑。
CSV = 'gaze_p411900_frames.csv'

# 本项目 demo 的 7 维特征（CALIB_FEATS）
SELF7 = ['f_irisL_y', 'f_irisL_x', 'f_yaw', 'f_pitch',
         'f_irisR_y', 'f_irisR_x', 'f_eyeIL_x']


def load():
    with open(CSV, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return rows


def ridge_fit(Z, y, lam=1000.0):
    d = Z.shape[1]
    G = Z.T @ Z + np.diag([lam] * (d - 1) + [0.0])
    try:
        return np.linalg.solve(G, Z.T @ y)
    except np.linalg.LinAlgError:
        return np.linalg.lstsq(G, Z.T @ y, rcond=None)[0]


def main():
    rows = load()
    # 目标坐标：每个 trial 一个固定目标
    by_trial = defaultdict(list)
    for r in rows:
        by_trial[int(r['trial'])].append(r)
    trials = sorted(by_trial)
    tgt = {}
    for t in trials:
        g = by_trial[t]
        tgt[t] = (float(g[0]['tx']), float(g[0]['ty']))

    # 特征矩阵
    feats = [c for c in SELF7 if c in rows[0]]
    X = np.array([[float(r[c]) for c in feats] for r in rows])
    Y = np.array([[float(r['tx']), float(r['ty'])] for r in rows])
    T = np.array([int(r['trial']) for r in rows])
    print('=' * 84)
    print('数据')
    print('=' * 84)
    print('  帧数 %d，trial 数 %d，特征 %d 维（%s）'
          % (len(rows), len(trials), len(feats), ', '.join(feats)))
    xs = [tgt[t][0] for t in trials]; ys = [tgt[t][1] for t in trials]
    print('  目标分布: x %.0f~%.0f (跨度 %.0f)   y %.0f~%.0f (跨度 %.0f)'
          % (min(xs), max(xs), max(xs) - min(xs), min(ys), max(ys), max(ys) - min(ys)))

    # ---------------------------------------------------------------
    #  逐 trial 留一：训练 35 个 trial，预测留出的那个
    #  这样测出的离散度不含过拟合，是"真实使用"的凝视噪声
    # ---------------------------------------------------------------
    resid = defaultdict(list)
    for t in trials:
        te = (T == t)
        tr = ~te
        mu = X[tr].mean(0); sd = X[tr].std(0) + 1e-12
        Ztr = np.column_stack([(X[tr] - mu) / sd, np.ones(tr.sum())])
        Zte = np.column_stack([(X[te] - mu) / sd, np.ones(te.sum())])
        bx = ridge_fit(Ztr, Y[tr, 0]); by = ridge_fit(Ztr, Y[tr, 1])
        px = Zte @ bx; py = Zte @ by
        dx = px - tgt[t][0]; dy = py - tgt[t][1]
        resid[t] = list(zip(dx.tolist(), dy.tolist()))

    # 每 trial 的离散度（相对该 trial 的自身均值，即"抖动"）
    spreads = []
    for t in trials:
        a = np.array(resid[t])
        spreads.append((float(a[:, 0].std()), float(a[:, 1].std()), len(a)))
    sx = np.median([s[0] for s in spreads])
    sy = np.median([s[1] for s in spreads])
    jitter = math.hypot(sx, sy)
    print()
    print('=' * 84)
    print('一、凝视噪声（同一目标下的帧间离散度，逐 trial 留一）')
    print('=' * 84)
    print('  水平标准差中位 %.0f px' % sx)
    print('  垂直标准差中位 %.0f px' % sy)
    print('  合成抖动       %.0f px' % jitter)
    print()
    print('  说明：这不是"准不准"（那是系统偏差），而是"稳不稳"。')
    print('        系统偏差靠校准消除，抖动无法消除，只能靠时间平均。')
    print('        N 帧平均后抖动降为 1/sqrt(N)：')
    for n in (1, 3, 5, 10, 20, 30):
        print('          %2d 帧平均 -> %.0f px' % (n, jitter / math.sqrt(n)))

    # ---------------------------------------------------------------
    #  二、假的"离开/进入"事件频率
    #  区域尺寸 R 下，若光标因抖动偏出区域，就会产生一次假的"离开"。
    #  用正态近似估算单帧越界概率，再算连续 N 帧里发生越界的概率。
    # ---------------------------------------------------------------
    print()
    print('=' * 84)
    print('二、假"离开区域"事件的频率（决定"回看次数"可不可信）')
    print('=' * 84)
    print('  模型：区域半径 R，光标中心在区域中心，抖动为二维正态(sigma=%.0f px)' % jitter)
    print('        某一帧偏出区域即记为一次"离开" -> 造成一次假的"回看"')
    print()
    print('  %-12s %-16s %-18s %-16s %s'
          % ('区域半径', '单帧越界概率', '1 秒内至少一次', '10 秒内至少一次', '可用性'))
    print('  ' + '-' * 78)
    fps = 30.0
    for R in (200, 300, 400, 500, 700, 900):
        # P(|偏移| > R)，二维正态，sigma 各向同性
        p1 = math.exp(-(R ** 2) / (2 * jitter ** 2))
        p_1s = 1 - (1 - p1) ** fps
        p_10s = 1 - (1 - p1) ** (fps * 10)
        if p_1s < 0.05:
            v = '好（几乎不误判）'
        elif p_1s < 0.3:
            v = '可用（需时间中值滤波）'
        elif p_1s < 0.8:
            v = '差（必须强滤波）'
        else:
            v = '不可用'
        print('  %-12s %-16.4f %-18.3f %-16.3f %s'
              % ('%d px' % R, p1, p_1s, p_10s, v))
    print()
    print('  可见：区域半径 < %.0f px 时，1 秒内几乎必然出现假越界。' % (jitter * 2))
    print('        这就是"停留时长"在细粒度下失效的机制。')

    # ---------------------------------------------------------------
    #  三、用中值/均值滤波能改善多少
    # ---------------------------------------------------------------
    print()
    print('=' * 84)
    print('三、时间滤波后（抖动降为 1/sqrt(N)）的可用区域尺寸')
    print('=' * 84)
    print('  %-12s %-14s %-18s %s' % ('滤波窗口', '残余抖动', '1 秒内假越界概率(半径400)', '判读'))
    print('  ' + '-' * 78)
    for n in (1, 3, 5, 10, 20):
        j = jitter / math.sqrt(n)
        p1 = math.exp(-(400 ** 2) / (2 * j ** 2))
        p_1s = 1 - (1 - p1) ** fps
        v = 'OK' if p_1s < 0.1 else ('borderline' if p_1s < 0.4 else 'NO')
        print('  %-12s %-14s %-18.3f %s'
              % ('%d 帧 (%.0f ms)' % (n, n / fps * 1000), '%.0f px' % j, p_1s, v))

    # ---------------------------------------------------------------
    #  四、区分"短看/长看"需要多少样本
    #  设真实停留时长 400ms vs 1200ms（相差 800ms）。
    #  每次"看"的时长估计误差来自抖动造成的边界抖动，
    #  简化模型：估计误差 sigma_t = (抖动 / 区域半径) * 平均停留
    #  用该 sigma_t 算所需样本量（双侧 alpha=0.05, power=0.8）
    # ---------------------------------------------------------------
    print()
    print('=' * 84)
    print('四、区分"短看 vs 长看"需要的样本量')
    print('=' * 84)
    print('  目标：区分 400ms 与 1200ms 两种停留（真实差异 800ms）')
    print('  时长估计误差近似 sigma_t ≈ (抖动/区域半径) x 停留时长')
    print()
    print('  %-12s %-14s %-16s %-16s %s'
          % ('区域半径', '相对抖动', 'sigma_t', '效应量 d', '每组所需样本'))
    print('  ' + '-' * 78)
    z_a, z_b = 1.96, 0.84
    for R in (200, 300, 400, 500, 700):
        rel = jitter / R
        sig = rel * 800.0          # 以 800ms 差异为尺度
        d = 800.0 / sig if sig > 0 else float('inf')
        n_req = int(math.ceil(2 * (z_a + z_b) ** 2 / (d ** 2))) if d > 0 else 0
        print('  %-12s %-14s %-16.0f %-16.2f %s'
              % ('%d px' % R, '%.3f' % rel, sig, d,
                 ('%d 次' % n_req) if n_req < 100000 else '不可行（效应量过小）'))
    print()
    print('  判读：单人要重复实验数百次才够 -> 不实用；')
    print('        几十次以内 -> 可在单被试长时使用中累积。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
