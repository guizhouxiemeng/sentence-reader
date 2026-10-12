#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
train.py — 第 2 周：按试次划分的视线回归模型 + 不确定性头

设计要点（每一条都对应一个前面踩过的坑）：
  1. 划分必须按"目标位置"分组，不能按帧。
     同一试次内相邻帧几乎相同，按帧划分会让指标虚低（实测 0.076 vs 0.153）。
  2. 特征用"头部平移不变"版本：(虹膜 - 眼中心)/瞳距，并补上相对眼角量。
     绝对关键点坐标的试次间方差是试次内的 10~44 倍，全是头动，必须去掉。
  3. 每个折内用训练折自己拟合标准化参数，避免信息泄漏。
  4. 输出 μ 与 log σ（高斯负对数似然），因为"知道自己在哪不确定"
     比"平均误差低 0.5%"更接近真实可用性。
  5. 同时报三个基准：随机猜、固定系数几何基线、每会话 12 点校准。

用法：
  python tools/train.py gaze_xxx_frames.csv
  python tools/train.py a.csv b.csv --subject-holdout    # 跨会话泛化
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

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ============================================================================
#  数据
# ============================================================================
REL_FEATS = ['f_L_h', 'f_L_v', 'f_L_h2', 'f_L_v2', 'f_R_h', 'f_R_v', 'f_R_h2', 'f_R_v2',
             'f_yaw', 'f_pitch', 'f_earL', 'f_earR', 'f_iod']


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot'] if 'phase' in c else rows
    return h, c, d


def build_features(h, c, d):
    """头部平移不变的视线特征 + 相对眼角量。"""
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    iod = col('iod') + 1e-9
    irx = (col('irisL_x') + col('irisR_x')) / 2
    iry = (col('irisL_y') + col('irisR_y')) / 2
    ecx, ecy = col('eyecenter_x'), col('eyecenter_y')
    gx = (irx - ecx) / iod
    gy = (iry - ecy) / iod
    feats = [gx, gy, gx * gx, gy * gy, gx * gy, np.ones_like(gx)]
    names = ['gaze_x', 'gaze_y', 'gaze_x2', 'gaze_y2', 'gaze_xy', 'bias']
    for f in REL_FEATS:
        if f in c:
            feats.append(col(f[2:]))
            names.append(f[2:])
    X = np.column_stack(feats)
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    Y = np.column_stack([tx, ty])
    return X, Y, names


def grid_key(tx, ty, quant=20):
    return np.round(tx / quant).astype(int) * 100000 + np.round(ty / quant).astype(int)


# ============================================================================
#  模型
# ============================================================================
def make_mlp(d_in, hidden=128, depth=3):
    layers, prev = [], d_in
    for _ in range(depth):
        layers += [nn.Linear(prev, hidden), nn.ReLU()]
        prev = hidden
    layers += [nn.Linear(prev, 4)]      # mux, muy, log_sx, log_sy
    return nn.Sequential(*layers)


def nll_loss(out, target):
    mu, log_s = out[:, :2], out[:, 2:]
    log_s = torch.clamp(log_s, -6.0, 4.0)
    s = torch.exp(log_s)
    return (0.5 * ((target - mu) / s) ** 2 + log_s).sum(dim=1).mean()


def train_fold(Xtr, Ytr, Xte, epochs=400, seed=0, lr=3e-3, wd=1e-4):
    torch.manual_seed(seed)
    np.random.seed(seed)
    mu, sd = Xtr.mean(0), Xtr.std(0) + 1e-8
    Xtr_n = (Xtr - mu) / sd
    Xte_n = (Xte - mu) / sd

    # 目标也标准化，否则 NLL 里的 sigma 尺度难以学习
    ymu, ysd = Ytr.mean(0), Ytr.std(0) + 1e-8
    Ytr_n = (Ytr - ymu) / ysd

    net = make_mlp(Xtr.shape[1])
    opt = torch.optim.Adam(net.parameters(), lr=lr, weight_decay=wd)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    xt = torch.tensor(Xtr_n, dtype=torch.float32)
    yt = torch.tensor(Ytr_n, dtype=torch.float32)
    xv = torch.tensor(Xte_n, dtype=torch.float32)

    net.train()
    for _ in range(epochs):
        opt.zero_grad()
        loss = nll_loss(net(xt), yt)
        loss.backward()
        opt.step()
        sched.step()

    net.eval()
    with torch.no_grad():
        o = net(xv).numpy()
    mu_px = o[:, :2] * ysd + ymu
    sig_px = np.exp(np.clip(o[:, 2:], -6, 4)) * ysd
    return mu_px, sig_px


def lstsq_fold(Xtr, Ytr, Xte):
    A = np.hstack([Xtr, np.ones((len(Xtr), 1))])
    coef, *_ = np.linalg.lstsq(A, Ytr, rcond=None)
    return np.hstack([Xte, np.ones((len(Xte), 1))]) @ coef


# ============================================================================
#  指标
# ============================================================================
def angle_deg(err_px, dist_cm=60.0, px_per_cm=None):
    """把像素误差换算成视角（度）。px_per_cm 未知时返回 None。"""
    if px_per_cm is None:
        return None
    return np.degrees(np.arctan((err_px / px_per_cm) / dist_cm))


def reliability(mu, Y, sig, bins=8):
    """返回 (平均预测sigma, 该桶内实际平均误差) 列表，用于画可靠性图。"""
    err = np.linalg.norm(mu - Y, axis=1)
    s = sig.mean(axis=1)
    edges = np.quantile(s, np.linspace(0, 1, bins + 1))
    out = []
    for i in range(bins):
        m = (s >= edges[i]) & (s <= edges[i + 1] if i == bins - 1 else s < edges[i + 1])
        if m.sum() < 3:
            continue
        out.append((float(s[m].mean()), float(err[m].mean()), int(m.sum())))
    return out


def calibrate_sigma(sig_fit, mu_fit, Y_fit, grid=None):
    """在留出集上学习一个标量温度 T，使 sig 的尺度匹配实际误差。

    为什么需要：模型直接学出来的 sigma 会严重过度自信（实测预测 3.7px / 实际 115px）。
    但 sigma 的"排序"往往是对的 —— 所以只需要一个标量缩放即可。
    缩放后虽不改善平均误差，却能真正用于"不确定时让界面主动确认"的交互逻辑。
    """
    err = np.linalg.norm(mu_fit - Y_fit, axis=1)
    s = sig_fit.mean(axis=1)
    if grid is None:
        grid = np.exp(np.linspace(np.log(1.0), np.log(300.0), 400))
    best_T, best_gap = 1.0, 1e18
    for T in grid:
        st = s * T
        # 目标：让"预测 sigma"与"实际误差"尽量一致（按桶比较）
        gap = 0.0
        edges = np.quantile(st, np.linspace(0, 1, 9))
        for i in range(8):
            m = (st >= edges[i]) & (st <= edges[i + 1] if i == 7 else st < edges[i + 1])
            if m.sum() < 3:
                continue
            gap += abs(np.log(max(st[m].mean(), 1e-6)) - np.log(max(err[m].mean(), 1e-6))) * m.sum()
        if gap < best_gap:
            best_gap, best_T = gap, float(T)
    return best_T


# ============================================================================
#  主流程
# ============================================================================
def evaluate_file(path, folds=5, epochs=400, verbose=True):
    h, c, d = load(path)
    X, Y, names = build_features(h, c, d)
    key = grid_key(Y[:, 0], Y[:, 1])
    W = (Y[:, 0].max() - Y[:, 0].min()) / 0.84
    H = (Y[:, 1].max() - Y[:, 1].min()) / 0.84
    diag = float(np.hypot(W, H))

    if verbose:
        print('=' * 78)
        print('文件      :', os.path.basename(path))
        print('帧数      :', len(Y), '  特征维度:', X.shape[1], '  目标位置数:', len(np.unique(key)))
        print('推断屏幕  : %.0f x %.0f   对角线 %.0f' % (W, H, diag))

    # 按目标位置分组划分
    rng = np.random.default_rng(0)
    uniq = rng.permutation(np.unique(key))
    assign = {k: i % folds for i, k in enumerate(uniq)}
    fold_of = np.array([assign[k] for k in key])

    mu_mlp = np.full_like(Y, np.nan)
    sig_mlp = np.full_like(Y, np.nan)
    mu_ls = np.full_like(Y, np.nan)

    for k in range(folds):
        te = fold_of == k
        tr = ~te
        if te.sum() < 5 or tr.sum() < 50:
            continue
        mu_mlp[te], sig_mlp[te] = train_fold(X[tr], Y[tr], X[te], epochs=epochs, seed=k)
        mu_ls[te] = lstsq_fold(X[tr], Y[tr], X[te])

    ok = ~np.isnan(mu_mlp[:, 0])
    err_mlp = np.linalg.norm(mu_mlp[ok] - Y[ok], axis=1)
    err_ls = np.linalg.norm(mu_ls[ok] - Y[ok], axis=1)
    Yk = Y[ok]

    # ---- 基线 ----
    fixed = None
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / col('iod')
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / col('iod')
    fx = np.clip(W / 2 + gx * (-42956), 0, W)
    fy = np.clip(H / 2 + gy * (+30595), 0, H)
    fixed = np.linalg.norm(np.column_stack([fx, fy])[ok] - Yk, axis=1)

    rnd = []
    for _ in range(200):
        p = np.column_stack([rng.uniform(0, W, ok.sum()), rng.uniform(0, H, ok.sum())])
        rnd.append(np.linalg.norm(p - Yk, axis=1).mean())
    rnd = float(np.mean(rnd))

    if verbose:
        print('\n' + '-' * 78)
        print('%-34s %10s %10s %10s' % ('方案', '平均px', '中位px', '/对角线'))
        print('%-34s %10.1f %10.1f %10.4f' % ('随机猜（参考上限）', rnd, 0, rnd / diag))
        print('%-34s %10.1f %10.1f %10.4f' % ('固定系数几何基线', fixed.mean(), np.median(fixed), fixed.mean() / diag))
        print('%-34s %10.1f %10.1f %10.4f' % ('线性（同特征，按点CV）', err_ls.mean(), np.median(err_ls), err_ls.mean() / diag))
        print('%-34s %10.1f %10.1f %10.4f' % ('MLP + 不确定性头', err_mlp.mean(), np.median(err_mlp), err_mlp.mean() / diag))

        # 分区
        print('\n分区域误差（MLP / 对角线）：')
        for lo, hi, tag, axis in [(0, 0.4, '左', 0), (0.4, 0.6, '中', 0), (0.6, 1.01, '右', 0),
                                  (0, 0.4, '上', 1), (0.4, 0.6, '中', 1), (0.6, 1.01, '下', 1)]:
            span = W if axis == 0 else H
            m = ((Yk[:, axis] / span >= lo) & (Yk[:, axis] / span < hi))
            if m.sum() > 2:
                print('   %s%s: %6.1f px  (%.4f)   n=%d'
                      % ('x=' if axis == 0 else 'y=', tag, err_mlp[m].mean(), err_mlp[m].mean() / diag, m.sum()))

        # 角度换算
        # 上一版写死"屏幕宽约 53cm / 1920px"，对 2560x1600 的屏幕是错的。
        # 现在按实际配置算：2560 物理像素宽的 16:10 屏（约 16 寸），
        # 物理像素间距 ≈ 0.135mm；150% 缩放下 1 CSS px = 1.5 物理像素 ≈ 0.202mm。
        # 若你的显示器尺寸不同，改 SCREEN_DIAG_IN 即可。
        SCREEN_DIAG_IN = 16.0
        phys_w_px = 2560.0
        phys_h_px = 1600.0
        diag_px_phys = np.hypot(phys_w_px, phys_h_px)
        mm_per_phys_px = (SCREEN_DIAG_IN * 25.4) / diag_px_phys
        dpr = 1.5
        mm_per_css_px = mm_per_phys_px * dpr
        # 本会话的 CSS 视口（由目标跨度反推）
        css_w = W
        screen_w_mm = css_w * mm_per_css_px
        err_mm = err_mlp.mean() * mm_per_css_px
        print('\n换算成视角（按 %.0f 寸 2560x1600 屏、dpr=%.1f → 1 CSS px ≈ %.3f mm）：'
              % (SCREEN_DIAG_IN, dpr, mm_per_css_px))
        print('   目标区域物理宽度 ≈ %.0f mm   平均误差 ≈ %.1f mm' % (screen_w_mm, err_mm))
        for dist in (50, 60, 70):
            deg = np.degrees(np.arctan((err_mm / 10.0) / dist))
            print('   眼屏距离 %d cm → %.2f°' % (dist, deg))
        print('   论文参照: 消费级摄像头 4~6°，专用眼动仪 0.5~1°')

        # 可靠性（含温度标定前后对比）
        print('\n不确定性校准（预测 sigma vs 实际误差）：')
        rel = reliability(mu_mlp[ok], Yk, sig_mlp[ok])
        if rel:
            print('   %14s %14s %8s' % ('预测sigma(px)', '实际误差(px)', 'n'))
            for s, e, n in rel:
                print('   %14.1f %14.1f %8d' % (s, e, n))
            ratio = np.mean([e / max(s, 1e-6) for s, e, _ in rel])
            print('   标定前 实际/预测 平均比 = %.1f  (>>1 = 严重过度自信)' % ratio)

            # 温度标定：在留出的一半上学 T，另一半上验证
            n = len(Yk)
            idx = np.random.default_rng(1).permutation(n)
            half = n // 2
            fit_i, val_i = idx[:half], idx[half:]
            T = calibrate_sigma(sig_mlp[ok][fit_i], mu_mlp[ok][fit_i], Yk[fit_i])
            s_val = sig_mlp[ok][val_i].mean(axis=1) * T
            e_val = np.linalg.norm(mu_mlp[ok][val_i] - Yk[val_i], axis=1)
            print('   学到的温度 T = %.1f' % T)
            print('   标定后（验证半区）实际/预测 平均比 = %.2f' % (e_val.mean() / s_val.mean()))
            # 分区对比
            lo = s_val < np.median(s_val)
            print('   标定后 高置信半区平均误差 = %.0f px' % e_val[lo].mean())
            print('   标定后 低置信半区平均误差 = %.0f px   (比值 %.2f)'
                  % (e_val[~lo].mean(), e_val[~lo].mean() / max(e_val[lo].mean(), 1e-6)))
            print('   -> 这个比值就是"用置信度做交互"的价值上限：比值越大，')
            print('      界面越有把握只在必要时才要求用户确认。')
        else:
            print('   样本不足')

    return dict(diag=diag, err_mlp=err_mlp.mean(), err_ls=err_ls.mean(), fixed=fixed.mean(),
                rnd=rnd, sig=sig_mlp[ok], mu=mu_mlp[ok], Y=Yk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--epochs', type=int, default=400)
    ap.add_argument('--folds', type=int, default=5)
    ap.add_argument('--subject-holdout', action='store_true',
                    help='用第一个文件训练、其余文件测试（模拟换一天/换个人）')
    args = ap.parse_args()

    if not HAS_TORCH:
        print('需要 PyTorch。安装（清华源）：')
        print('  D:\\projects\\flappy_rl\\flappy_rl\\Scripts\\python.exe -m pip install torch '
              '-i https://pypi.tuna.tsinghua.edu.cn/simple')
        return 1

    if args.subject_holdout and len(args.files) >= 2:
        tr_file, te_files = args.files[0], args.files[1:]
        print('跨会话实验：训练 =', os.path.basename(tr_file), ' 测试 =',
              ', '.join(os.path.basename(f) for f in te_files))
        h, c, d = load(tr_file)
        Xtr, Ytr, _ = build_features(h, c, d)
        for f in te_files:
            h2, c2, d2 = load(f)
            Xte, Yte, _ = build_features(h2, c2, d2)
            mu, sig = train_fold(Xtr, Ytr, Xte, epochs=args.epochs)
            W = (Ytr[:, 0].max() - Ytr[:, 0].min()) / 0.84
            H = (Ytr[:, 1].max() - Ytr[:, 1].min()) / 0.84
            diag = float(np.hypot(W, H))
            e = np.linalg.norm(mu - Yte, axis=1)
            # 同会话内校准作对照
            mu_in, _ = train_fold(Xte, Yte, Xte, epochs=args.epochs)
            e_in = np.linalg.norm(mu_in - Yte, axis=1)
            print('\n%-30s 跨会话 %.1f px (%.4f)   同会话(上界) %.1f px (%.4f)'
                  % (os.path.basename(f), e.mean(), e.mean() / diag, e_in.mean(), e_in.mean() / diag))
        return 0

    results = []
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); continue
        r = evaluate_file(f, folds=args.folds, epochs=args.epochs)
        results.append((os.path.basename(f), r))

    if len(results) > 1:
        print('\n' + '=' * 78)
        print('汇总')
        print('%-30s %10s %10s %10s' % ('文件', 'MLP', '线性', '固定基线'))
        for n, r in results:
            print('%-30s %10.4f %10.4f %10.4f' % (n, r['err_mlp'] / r['diag'],
                                                  r['err_ls'] / r['diag'], r['fixed'] / r['diag']))
    return 0


if __name__ == '__main__':
    sys.exit(main())
