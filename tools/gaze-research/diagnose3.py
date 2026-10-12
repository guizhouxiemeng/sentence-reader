#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
diagnose3.py — 逐帧头位归一化（关键修复）

核心洞察：
  · 绝对虹膜位置 (f_irisL_x ...) 的试次间方差是试次内的 10~44 倍
    → 绝对方差主要来自"头部平移"，不是眼动（眼球动 1-2mm，头动 30mm）
  · 但"试次内中心化"会连眼动信号一起减掉（因为一个试次内目标固定）
  · 正确做法：逐帧减去眼睛中心（或鼻尖），得到头部平移不变的视线向量

只依赖 CSV 里已有的绝对特征，不需要重新采集：
      gaze_x = (iris.x - eye_center.x) / iod
      gaze_y = (iris.y - eye_center.y) / iod

用法： python tools/diagnose3.py gaze_xxx_frames.csv
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


def load(path):
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [r for r in rd if len(r) == len(header)]
    cols = {n: i for i, n in enumerate(header)}
    fnames = [h for h in header if h.startswith('f_')]
    X = np.array([[float(r[cols[f]]) for f in fnames] for r in rows])
    Y = np.column_stack([[float(r[cols['tx']]) for r in rows], [float(r[cols['ty']]) for r in rows]])
    trial = np.array([int(r[cols['trial']]) for r in rows])
    phase = np.array([r[cols['phase']] for r in rows]) if 'phase' in cols else np.array(['dot'] * len(rows))
    return fnames, X, Y, trial, phase


def cv_err(X, Y, trial, folds=4, seed=0):
    rng = np.random.default_rng(seed)
    ut = np.unique(trial)
    fold = {t: i % folds for i, t in enumerate(rng.permutation(ut))}
    err = np.full(len(Y), np.nan)
    for k in range(folds):
        te = np.where([fold[t] == k for t in trial])[0]
        tr = np.where([fold[t] != k for t in trial])[0]
        if len(te) == 0 or len(tr) == 0:
            continue
        A = np.hstack([X[tr], np.ones((len(tr), 1))])
        coef, *_ = np.linalg.lstsq(A, Y[tr], rcond=None)
        P = np.hstack([X[te], np.ones((len(te), 1))]) @ coef
        err[te] = np.linalg.norm(P - Y[te], axis=1)
    return err, float(np.nanmean(err))


def col_of(X, fnames, name):
    return X[:, fnames.index(name)]


def build_headfree(X, fnames, anchor='eye'):
    """构造头部平移不变的视线特征 + 保留头部姿态等有用量"""
    iod = col_of(X, fnames, 'f_iod') + 1e-9
    irx = (col_of(X, fnames, 'f_irisL_x') + col_of(X, fnames, 'f_irisR_x')) / 2
    iry = (col_of(X, fnames, 'f_irisL_y') + col_of(X, fnames, 'f_irisR_y')) / 2
    if anchor == 'eye':
        ax = col_of(X, fnames, 'f_eyecenter_x')
        ay = col_of(X, fnames, 'f_eyecenter_y')
    else:
        ax = col_of(X, fnames, 'f_nose_x')
        ay = col_of(X, fnames, 'f_nose_y')
    gx = (irx - ax) / iod
    gy = (iry - ay) / iod
    # 相对眼角（现有特征）+ 双眼一致性 + 姿态
    keep = ['f_L_h', 'f_L_v', 'f_R_h', 'f_R_v', 'f_L_h2', 'f_L_v2', 'f_R_h2', 'f_R_v2',
            'f_yaw', 'f_pitch', 'f_earL', 'f_earR']
    keep = [k for k in keep if k in fnames]
    F = [gx, gy, (gx + col_of(X, fnames, 'f_R_h')) / 2,
         (col_of(X, fnames, 'f_L_h') - col_of(X, fnames, 'f_R_h')),
         (col_of(X, fnames, 'f_L_v') - col_of(X, fnames, 'f_R_v'))]
    names = ['gaze_x', 'gaze_y', 'gaze_x_mix', 'eye_asym_h', 'eye_asym_v']
    for k in keep:
        F.append(col_of(X, fnames, k))
        names.append(k)
    return np.column_stack(F), names


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path')
    ap.add_argument('--diag', type=float, default=None)
    args = ap.parse_args()

    fnames, X, Y, trial, phase = load(args.csv_path)
    m = phase == 'dot'
    X, Y, trial = X[m], Y[m], trial[m]
    w_est = (Y[:, 0].max() - Y[:, 0].min()) / 0.84
    h_est = (Y[:, 1].max() - Y[:, 1].min()) / 0.84
    diag = args.diag or float(np.hypot(w_est, h_est))

    print('=' * 72)
    print('数据: %d 帧 / %d 试次   推断屏幕 %.0fx%.0f  对角线 %.0f'
          % (len(Y), len(np.unique(trial)), w_est, h_est, diag))

    # ---------- 新特征与目标的相关性 ----------
    F, Fnames = build_headfree(X, fnames, 'eye')
    print('\n【1】头部平移不变特征的相关性（这才是真正的视线信号）')
    rows = []
    for j, n in enumerate(Fnames):
        v = F[:, j]
        if v.std() < 1e-12:
            continue
        rx = float(np.corrcoef(v, Y[:, 0])[0, 1])
        ry = float(np.corrcoef(v, Y[:, 1])[0, 1])
        rows.append((max(abs(rx), abs(ry)), n, rx, ry))
    rows.sort(reverse=True)
    for a, n, rx, ry in rows[:10]:
        print('   %-16s r(target_x)=%+.3f  r(target_y)=%+.3f' % (n, rx, ry))

    # ---------- 对比各方案 ----------
    print('\n【2】各方案按试次 4 折 CV 误差（越低越好）')
    e_abs, m_abs = cv_err(X, Y, trial)
    print('   (a) 原始 39 维（含绝对位置）    : %7.1f px   %.4f 对角线' % (m_abs, m_abs / diag))

    Fn, _ = build_headfree(X, fnames, 'nose')
    e_nose, m_nose = cv_err(Fn, Y, trial)
    print('   (b) 减去鼻尖（平移不变）%2d 维   : %7.1f px   %.4f 对角线   (%+.1f%%)'
          % (Fn.shape[1], m_nose, m_nose / diag, 100 * (m_nose - m_abs) / m_abs))

    e_eye, m_eye = cv_err(F, Y, trial)
    print('   (c) 减去眼睛中心 %2d 维          : %7.1f px   %.4f 对角线   (%+.1f%%)'
          % (F.shape[1], m_eye, m_eye / diag, 100 * (m_eye - m_abs) / m_abs))

    # 只用 gaze_x / gaze_y 两个量
    e_g, m_g = cv_err(F[:, :2], Y, trial)
    print('   (d) 只用 gaze_x, gaze_y 两维     : %7.1f px   %.4f 对角线   (%+.1f%%)'
          % (m_g, m_g / diag, 100 * (m_g - m_abs) / m_abs))

    best = min([('原始', m_abs), ('减鼻尖', m_nose), ('减眼中心', m_eye), ('仅gaze两维', m_g)],
               key=lambda kv: kv[1])
    print('\n   最佳: %s -> %.1f px (%.4f 对角线)   几何基线是 0.3105' % (best[0], best[1], best[1] / diag))

    # ---------- 单变量最优斜率（修正采集器里的公式）----------
    print('\n【3】给采集器用的修正系数')
    gx, gy = F[:, 0], F[:, 1]
    for name, feat, tgt, sw in [('x', gx, Y[:, 0], w_est), ('y', gy, Y[:, 1], h_est)]:
        A = np.column_stack([feat, np.ones(len(feat))])
        coef, *_ = np.linalg.lstsq(A, tgt, rcond=None)
        r = float(np.corrcoef(feat, tgt)[0, 1])
        print('   %s: 斜率=%+9.1f px/单位  归一化斜率(×1/屏宽)=%+8.2f  r=%+.3f'
              % (name, coef[0], coef[0] / sw, r))
    print('   说明：负数斜率意味着"虹膜相对眼中心向右 → 目标 x 更小"。')
    print('   这与前置摄像头成像的左右镜像一致，属于正常现象，第 5 周做交互时统一翻转即可。')

    # ---------- 每试次误差分布 ----------
    print('\n【4】误差是否集中在少数试次？')
    err = e_eye
    per_trial = np.array([err[trial == t].mean() for t in np.unique(trial)])
    print('   每试次平均误差: 最小 %.0f  中位 %.0f  最大 %.0f px'
          % (per_trial.min(), np.median(per_trial), per_trial.max()))
    worst = np.argsort(-per_trial)[:5]
    ut = np.unique(trial)
    for i in worst:
        t = ut[i]
        tm = trial == t
        print('   试次 #%d: 误差 %6.0f px   目标(%.0f, %.0f)'
              % (t, per_trial[i], Y[tm][0, 0], Y[tm][0, 1]))
    print('   （若少数试次误差极大，多半是那些点在屏幕边角 or 当时头动了）')

    # ---------- 画图 ----------
    try:
        cache = os.path.join(os.path.dirname(os.path.abspath(args.csv_path)), '.mplcache')
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault('MPLCONFIGDIR', cache)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        A = np.hstack([F, np.ones((len(F), 1))])
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        P = A @ coef
        fig, ax = plt.subplots(1, 2, figsize=(12.5, 5.4))
        ax[0].scatter(Y[:, 0], Y[:, 1], s=70, facecolors='none', edgecolors='#4c8dff', label='target')
        for t in np.unique(trial):
            tm = trial == t
            ax[0].plot(P[tm, 0].mean(), P[tm, 1].mean(), 'o', color='#ff6b6b', ms=5)
        ax[0].invert_yaxis()
        ax[0].set_title('target (blue) vs head-free LS estimate (red, per-trial mean)')
        ax[0].set_xlabel('x (px)'); ax[0].set_ylabel('y (px)'); ax[0].grid(alpha=.25)

        ax[1].scatter(gx, Y[:, 0], s=5, alpha=.3, label='gaze_x vs target_x')
        ax[1].scatter(gy, Y[:, 1], s=5, alpha=.3, label='gaze_y vs target_y')
        ax[1].set_xlabel('head-free gaze feature'); ax[1].set_ylabel('target (px)')
        ax[1].set_title('head-free gaze features vs target'); ax[1].legend(); ax[1].grid(alpha=.25)
        fig.tight_layout()
        out = os.path.splitext(args.csv_path)[0] + '_headfree.png'
        fig.savefig(out, dpi=130)
        print('\n图已保存:', out)
    except Exception as e:
        print('\n画图失败:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
