#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
analyze.py — 第 1 周的诊断脚本

回答三个问题：
  1. 关键点到底有没有在动？        （特征方差）
  2. 它和目标位置有没有相关？      （相关系数）
  3. 一个线性模型的极限在哪？      （最小二乘 vs 几何基线）

用法：
    python tools/analyze.py gaze_p123456_frames.csv
    python tools/analyze.py gaze_p123456_frames.csv --diag 3560

只依赖 numpy + matplotlib（走 csv 模块读文件，不需要 pandas）。
"""
import argparse
import csv
import os
import sys

import numpy as np

# Windows 控制台默认 GBK，中文输出会乱码；这里主动切成 UTF-8
for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 与 collector.html 中 drawPreview / 几何基线保持一致的系数
BASE_X_SLOPE, BASE_Y_SLOPE = 1.55, 1.35


def load(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [r for r in rd if len(r) == len(header)]
    cols = {name: i for i, name in enumerate(header)}
    return header, cols, rows


def col(rows, cols, name):
    i = cols[name]
    return np.array([float(r[i]) for r in rows], dtype=np.float64)


def feat_cols(header, cols):
    return [h for h in header if h.startswith('f_')]


def fit_and_score(X, Y, train, test):
    """在 train 上最小二乘，在 test 上评估。返回逐样本像素误差。"""
    Xtr = np.hstack([X[train], np.ones((len(train), 1))])
    coef, *_ = np.linalg.lstsq(Xtr, Y[train], rcond=None)
    Xte = np.hstack([X[test], np.ones((len(test), 1))])
    pred = Xte @ coef
    return np.linalg.norm(pred - Y[test], axis=1), coef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path')
    ap.add_argument('--diag', type=float, default=None,
                    help='视口对角线(像素)。不给就用 target 的包围盒对角线估算')
    ap.add_argument('--out', default=None, help='图表输出路径')
    ap.add_argument('--hold-ms', type=float, default=800.0, help='点停留时长，用于定位尾段稳定期')
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        print('找不到文件:', args.csv_path)
        return 1

    header, cols, rows = load(args.csv_path)
    if not rows:
        print('CSV 没有数据行')
        return 1
    fnames = feat_cols(header, cols)

    print('=' * 72)
    print('文件      :', args.csv_path)
    print('总行数    :', len(rows), ' 特征列:', len(fnames))
    if 'phase' in cols:
        phases = {}
        for r in rows:
            phases[r[cols['phase']]] = phases.get(r[cols['phase']], 0) + 1
        print('阶段分布  :', phases)

    # ---- 只保留 dot 阶段（pre 阶段眼睛还在飞向目标，标签是错的）----
    if 'phase' in cols:
        idx_dot = [i for i, r in enumerate(rows) if r[cols['phase']] == 'dot']
    else:
        idx_dot = list(range(len(rows)))
    if not idx_dot:
        print('没有 dot 阶段样本，无法分析')
        return 1
    rows_d = [rows[i] for i in idx_dot]

    X = np.array([[float(r[cols[f]]) for f in fnames] for r in rows_d], dtype=np.float64)
    Y = np.column_stack([col(rows_d, cols, 'tx'), col(rows_d, cols, 'ty')])
    trial = col(rows_d, cols, 'trial').astype(int)

    # 对角线：优先用户给定，否则用目标包围盒估
    if args.diag:
        diag = args.diag
    else:
        w = Y[:, 0].max() - Y[:, 0].min()
        h = Y[:, 1].max() - Y[:, 1].min()
        diag = float(np.hypot(w, h) / 0.84)   # 目标只覆盖 (1-2*inset) 的范围
        print('注意      : 未提供 --diag，按目标包围盒估算对角线 =', round(diag, 1))

    # ---- 1) 特征是否在动 ----
    print('\n' + '=' * 72)
    print('【1】特征活跃度（标准差；若接近 0 说明关键点根本没动）')
    std = X.std(axis=0)
    order = np.argsort(-std)
    for i in order[:10]:
        print('   %-16s std=%.5f' % (fnames[i], std[i]))
    print('   ... 最小 std=%.6f (%s)' % (std.min(), fnames[int(std.argmin())]))
    dead = int((std < 1e-5).sum())
    alive = int((std > 1e-4).sum())
    print('   恒定（std<1e-5）: %d / %d    有实际变化（std>1e-4）: %d'
          % (dead, len(fnames), alive))

    # ---- 2) 与目标的单变量相关 ----
    print('\n' + '=' * 72)
    print('【2】与目标坐标相关性最高的特征（|r|>0.5 才算有信号）')
    Xc = X - X.mean(axis=0)
    xs = Xc.std(axis=0) + 1e-12
    corr = []
    for j, f in enumerate(fnames):
        r1 = float(np.corrcoef(Xc[:, j], Y[:, 0])[0, 1]) if xs[j] > 1e-9 else 0.0
        r2 = float(np.corrcoef(Xc[:, j], Y[:, 1])[0, 1]) if xs[j] > 1e-9 else 0.0
        corr.append((max(abs(r1), abs(r2)), r1, r2, f))
    corr.sort(reverse=True)
    for a, r1, r2, f in corr[:12]:
        print('   %-16s  r(target_x)=%+.3f  r(target_y)=%+.3f' % (f, r1, r2))
    best = corr[0][0] if corr else 0.0
    print('   最强单变量相关 |r| = %.3f' % best)

    # ---- 3) 几何基线 vs 最小二乘 ----
    print('\n' + '=' * 72)
    print('【3】误差对比（单位：像素 / 视口对角线）')
    if 'f_L_h' in cols and 'f_L_v' in cols and 'f_R_h' in cols and 'f_R_v' in cols:
        ex = (X[:, fnames.index('f_L_h')] + X[:, fnames.index('f_R_h')]) / 2.0
        ey = (X[:, fnames.index('f_L_v')] + X[:, fnames.index('f_R_v')]) / 2.0
        pw = Y[:, 0].max() - Y[:, 0].min()
        ph = Y[:, 1].max() - Y[:, 1].min()
        # 采集器里的换算基于屏幕尺寸；这里用同一套比例
        screen_w = pw / 0.84
        screen_h = ph / 0.84
        gx = np.clip(screen_w * (0.5 + ex * BASE_X_SLOPE), 0, screen_w)
        gy = np.clip(screen_h * (0.5 + ey * BASE_Y_SLOPE), 0, screen_h)
        gerr = np.linalg.norm(np.column_stack([gx, gy]) - Y, axis=1)
        print('   几何基线(mean)          : %.1f px   %.4f 对角线   |  中位 %.1f px'
              % (gerr.mean(), gerr.mean() / diag, np.median(gerr)))
        print('   几何基线(试次内取均值)  : ', end='')
        gt_errs = []
        for t in np.unique(trial):
            m = trial == t
            gt_errs.append(np.hypot(gx[m].mean() - Y[m][:, 0].mean(), gy[m].mean() - Y[m][:, 1].mean()))
        gt_errs = np.array(gt_errs)
        print('%.1f px   %.4f 对角线' % (gt_errs.mean(), gt_errs.mean() / diag))

    # 按试次分组的交叉验证：这才是诚实的数字
    ut = np.unique(trial)
    rng = np.random.default_rng(0)
    fold = {t: i % 4 for i, t in enumerate(rng.permutation(ut))}
    cv_err = np.full(len(Y), np.nan)
    for k in range(4):
        test = np.where([fold[t] == k for t in trial])[0]
        train = np.where([fold[t] != k for t in trial])[0]
        if len(test) == 0 or len(train) == 0:
            continue
        e, _ = fit_and_score(X, Y, train, test)
        cv_err[test] = e
    ok = ~np.isnan(cv_err)
    print('   最小二乘(按试次4折CV)   : %.1f px   %.4f 对角线   |  中位 %.1f px'
          % (cv_err[ok].mean(), cv_err[ok].mean() / diag, np.median(cv_err[ok])))

    # 帧级拟合（会虚低，只作"数据里到底有没有信号"的上界参考）
    allidx = np.arange(len(Y))
    e_in, _ = fit_and_score(X, Y, allidx, allidx)
    print('   最小二乘(帧级拟合,虚低) : %.1f px   %.4f 对角线   <- 仅作信号上界'
          % (e_in.mean(), e_in.mean() / diag))

    # ---- 结论 ----
    print('\n' + '=' * 72)
    print('【结论】')
    # 判据只看两件事：关键点有没有在动，动得跟目标有没有关系。
    # 不要用"恒定特征数"下结论——很多特征（如额头 z）本来就该近似恒定。
    if alive < 3:
        print('  ✗ 只有 %d 个特征有实际变化 —— 人脸关键点几乎没被检出。' % alive)
        print('    检查：脸是否完整在画面内、光照是否正面、是否离摄像头太远。')
    elif best < 0.3:
        print('  ✗ 关键点在动（%d 个活跃特征），但最强单变量相关只有 %.2f。' % (alive, best))
        print('    特征与目标几乎无关。常见原因：')
        print('      · 盯点时用余光扫、或实际看的是屏幕中心而非白点')
        print('      · 头代替眼睛在动（转头去"看"而不是只动眼球）')
        print('      · 头部位置移动 → 特征整体漂移，淹没了眼球信号')
    elif best < 0.6:
        print('  ~ 有中等相关（|r|max=%.2f），信号偏弱但可能可用。' % best)
        print('    先看【3】里最小二乘是否明显优于几何基线：优于就继续往下走。')
    else:
        print('  ✓ 存在明确相关信号（|r|max=%.2f）。' % best)
        print('    若最小二乘明显优于几何基线，说明数据可用，')
        print('    只是几何基线的固定系数不对 —— 这正是第 2 周要用学习解决的问题。')

    # ---- 画图 ----
    out = args.out or os.path.splitext(args.csv_path)[0] + '_diag.png'
    try:
        # 把 matplotlib 的缓存目录指到可写位置，避免它在用户目录下被沙箱拒绝
        cache = os.path.join(os.path.dirname(os.path.abspath(args.csv_path)), '.mplcache')
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault('MPLCONFIGDIR', cache)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
        ax = axes[0]
        ax.scatter(Y[:, 0], Y[:, 1], s=60, marker='o', facecolors='none',
                   edgecolors='#4c8dff', label='target')
        gt_x, gt_y = [], []
        if 'f_L_h' in cols:
            for t in ut:
                m = trial == t
                gt_x.append(gx[m].mean())
                gt_y.append(gy[m].mean())
            ax.scatter(gt_x, gt_y, s=28, c='#ff6b6b', label='geometric est')
        ax.invert_yaxis()
        ax.set_title('target vs geometric estimate (screen px)')
        ax.set_xlabel('x'); ax.set_ylabel('y'); ax.legend(); ax.grid(alpha=.25)

        ax2 = axes[1]
        if 'f_L_h' in cols:
            ax2.scatter(X[:, fnames.index('f_L_h')], Y[:, 0], s=6, alpha=.35, label='L_h vs target_x')
            ax2.scatter(X[:, fnames.index('f_R_h')], Y[:, 0], s=6, alpha=.35, label='R_h vs target_x')
            ax2.set_xlabel('iris horizontal feature'); ax2.set_ylabel('target x (px)')
            ax2.legend(); ax2.grid(alpha=.25)
            ax2.set_title('is the iris feature even correlated?')
        fig.tight_layout()
        fig.savefig(out, dpi=130)
        print('\n图已保存:', out)
    except Exception as e:
        print('\n画图失败（不影响上面的数字）:', e)

    return 0


if __name__ == '__main__':
    sys.exit(main())
