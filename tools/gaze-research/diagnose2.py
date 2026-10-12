#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
diagnose2.py — 针对第一轮数据的深挖诊断

假设与验证：
  H1  跨试次崩溃是因为头部位置漂移  -> 试次内中心化后 CV 误差应显著下降
  H2  眨眼帧是噪声源                -> 剔除 ear 过低/过高帧后误差应下降
  H3  几何基线系数完全不对          -> 重新拟合斜率应远大于 1.55

用法： python tools/diagnose2.py gaze_xxx_frames.csv [--diag 2202]
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
    phase = [r[cols['phase']] for r in rows] if 'phase' in cols else ['dot'] * len(rows)
    return fnames, X, Y, trial, np.array(phase), cols


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
    return err, np.nanmean(err)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv_path')
    ap.add_argument('--diag', type=float, default=None)
    args = ap.parse_args()

    fnames, X, Y, trial, phase, cols = load(args.csv_path)
    m_dot = phase == 'dot'
    X, Y, trial = X[m_dot], Y[m_dot], trial[m_dot]
    print('dot 阶段样本:', len(Y), ' 试次数:', len(np.unique(trial)))

    # ---------- H0: 目标覆盖范围 ----------
    print('\n' + '=' * 70)
    print('【H0】目标坐标范围（判断屏幕尺寸与对角线）')
    for i, ax in enumerate('xy'):
        lo, hi = Y[:, i].min(), Y[:, i].max()
        print('   target_%s: %.0f .. %.0f   (跨度 %.0f, 推断 inset=%s)'
              % (ax, lo, hi, hi - lo, '0.08 → 全屏约 %.0f px' % ((hi - lo) / 0.84)))
    w_est = (Y[:, 0].max() - Y[:, 0].min()) / 0.84
    h_est = (Y[:, 1].max() - Y[:, 1].min()) / 0.84
    diag = args.diag or float(np.hypot(w_est, h_est))
    print('   推断全屏: %.0f x %.0f   对角线 %.0f' % (w_est, h_est, diag))

    # ---------- H1: 试次内 vs 试次间方差 ----------
    print('\n' + '=' * 70)
    print('【H1】头部漂移检查：试次内 std vs 试次间(试次均值) std')
    print('   %-14s %10s %12s %8s' % ('feature', 'within', 'between', '比值'))
    rows_out = []
    for f in ['f_eyeOL_x', 'f_eyeOL_y', 'f_eyecenter_x', 'f_eyecenter_y', 'f_nose_x', 'f_nose_y',
              'f_R_h', 'f_L_h', 'f_L_v', 'f_fore_x', 'f_fore_y']:
        if f not in fnames:
            continue
        j = fnames.index(f)
        v = X[:, j]
        within = np.mean([v[trial == t].std() for t in np.unique(trial)])
        means = np.array([v[trial == t].mean() for t in np.unique(trial)])
        between = means.std()
        ratio = between / (within + 1e-12)
        rows_out.append((ratio, f, within, between))
        print('   %-14s %10.5f %12.5f %8.2f' % (f, within, between, ratio))
    rows_out.sort(reverse=True)
    print('   -> 比值最大的特征（= 最受头部位置影响）: %s (%.2f)'
          % (rows_out[0][1], rows_out[0][0]))

    # ---------- 基线：原始特征 ----------
    print('\n' + '=' * 70)
    print('【H1/H2】不同特征处理下的按试次 4 折 CV 误差')
    e0, m0 = cv_err(X, Y, trial)
    print('   (a) 原始 39 维                : %7.1f px   %.4f 对角线' % (m0, m0 / diag))

    # 试次内中心化
    Xc = X.copy()
    for t in np.unique(trial):
        m = trial == t
        Xc[m] = Xc[m] - Xc[m].mean(axis=0)
    e1, m1 = cv_err(Xc, Y, trial)
    print('   (b) 试次内中心化 39 维        : %7.1f px   %.4f 对角线   (变化 %+.1f%%)'
          % (m1, m1 / diag, 100 * (m1 - m0) / m0))

    # 只用虹膜/眼部相对特征（去掉绝对位置，看是否等价于中心化）
    rel = [f for f in fnames if f.startswith(('f_L_h', 'f_L_v', 'f_R_h', 'f_R_v',
                                              'f_iris', 'f_eye', 'f_iod', 'f_yaw', 'f_pitch', 'f_ear'))]
    ridx = [fnames.index(f) for f in rel]
    e2, m2 = cv_err(X[:, ridx], Y, trial)
    print('   (c) 仅相对特征 (%d 维)      : %7.1f px   %.4f 对角线   (变化 %+.1f%%)'
          % (len(rel), m2, m2 / diag, 100 * (m2 - m0) / m0))

    # 试次内中心化 + 只用相对特征
    e3, m3 = cv_err(Xc[:, ridx], Y, trial)
    print('   (d) 中心化 + 仅相对特征      : %7.1f px   %.4f 对角线   (变化 %+.1f%%)'
          % (m3, m3 / diag, 100 * (m3 - m0) / m0))

    # ---------- H2: 眨眼看 ----------
    print('\n' + '=' * 70)
    print('【H2】眨眼/眯眼帧的影响')
    if 'f_earL' in fnames and 'f_earR' in fnames:
        ear = (X[:, fnames.index('f_earL')] + X[:, fnames.index('f_earR')]) / 2
        print('   ear 分布: min=%.3f  p5=%.3f  中位=%.3f  p95=%.3f  max=%.3f'
              % (ear.min(), np.percentile(ear, 5), np.median(ear), np.percentile(ear, 95), ear.max()))
        for lo, hi, tag in [(0.0, 1.0, '剔除 ear<0.15（闭眼）'),
                            (0.15, 0.45, '仅保留 0.15<ear<0.45（正常睁眼）'),
                            (0.0, 1.0, '全部')]:
            m = (ear >= lo) & (ear <= hi)
            if tag == '全部':
                m = np.ones(len(ear), bool)
            if m.sum() < 50:
                print('   %-34s : 样本不足' % tag); continue
            _, mm = cv_err(Xc[m], Y[m], trial[m])
            print('   %-34s : %7.1f px   %.4f 对角线   (保留 %d 帧)'
                  % (tag, mm, mm / diag, m.sum()))
    else:
        print('   没有 ear 特征')

    # ---------- H3: 几何基线斜率 ----------
    print('\n' + '=' * 70)
    print('【H3】几何基线系数复核（我原来写死 1.55 / 1.35）')
    if all(f in fnames for f in ['f_L_h', 'f_R_h', 'f_L_v', 'f_R_v']):
        ex = (X[:, fnames.index('f_L_h')] + X[:, fnames.index('f_R_h')]) / 2
        ey = (X[:, fnames.index('f_L_v')] + X[:, fnames.index('f_R_v')]) / 2
        for name, feat, tgt in [('x', ex, Y[:, 0]), ('y', ey, Y[:, 1])]:
            A = np.column_stack([feat, np.ones(len(feat))])
            coef, *_ = np.linalg.lstsq(A, tgt, rcond=None)
            r = np.corrcoef(feat, tgt)[0, 1]
            print('   %s: 最优斜率=%+9.1f  截距=%+9.1f  r=%+.3f   (我写死的斜率是 %s)'
                  % (name, coef[0], coef[1], r, '1.55' if name == 'x' else '1.35'))
        print('   注：斜率是对"屏幕像素"而言；写死的 1.55 是相对屏幕尺寸的归一化系数。')
    print('\n' + '=' * 70)
    print('【结论指引】')
    best_tag, best_val = min([('原始', m0), ('中心化', m1), ('仅相对特征', m2), ('中心化+相对', m3)],
                             key=lambda kv: kv[1])
    print('   最好的特征方案: %s  ->  %.1f px  (%.4f 对角线)' % (best_tag, best_val, best_val / diag))
    if m1 < m0 * 0.9:
        print('   ✓ 中心化带来 >10%% 改善 → 头部漂移确实是主因，采集器应加入中心化特征')
    else:
        print('   · 中心化改善有限 → 头部漂移不是主因，需另找原因（可能是注视点不稳定）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
