#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
compare.py — 逐试次对比多次采集，定位"哪一次/哪一批目标点坏了"

输出按目标位置分区的误差，以及两次会话在同一目标上的差异。
用法：
  python tools/compare.py old.csv new.csv [--diag 1988]
  python tools/compare.py one.csv            # 单文件：看目标分区误差
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

KX, KY = -42956.0, 30595.0   # 用旧数据拟合的系数，作为统一参照


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot'] if 'phase' in c else rows
    return h, c, d


def per_trial(path, W=None, H=None):
    h, c, d = load(path)
    g = lambda r, n: float(r[c['f_' + n]])
    groups = {}
    for r in d:
        groups.setdefault(int(r[c['trial']]), []).append(r)

    tx = [float(rs[0][c['tx']]) for rs in groups.values()]
    ty = [float(rs[0][c['ty']]) for rs in groups.values()]
    if W is None:
        W = (max(tx) - min(tx)) / 0.84
        H = (max(ty) - min(ty)) / 0.84
    diag = float(np.hypot(W, H))

    out = []
    for t, rs in sorted(groups.items()):
        gx = np.mean([(g(r, 'irisL_x') + g(r, 'irisR_x')) / 2 - g(r, 'eyecenter_x') for r in rs]) \
             / np.mean([g(r, 'iod') for r in rs])
        gy = np.mean([(g(r, 'irisL_y') + g(r, 'irisR_y')) / 2 - g(r, 'eyecenter_y') for r in rs]) \
             / np.mean([g(r, 'iod') for r in rs])
        # 该试次内头位漂移（用眼睛中心的试次内跨度衡量）
        hx = [g(r, 'eyecenter_x') for r in rs]
        hy = [g(r, 'eyecenter_y') for r in rs]
        out.append({
            'trial': t,
            'tx': float(rs[0][c['tx']]), 'ty': float(rs[0][c['ty']]),
            'gx': float(gx), 'gy': float(gy),
            'n': len(rs),
            'head_p2p': float(np.hypot(max(hx) - min(hx), max(hy) - min(hy))),
            'head_std': float(np.hypot(np.std(hx), np.std(hy))),
            'ear_min': float(min(g(r, 'earL') for r in rs)),
        })
    return out, W, H, diag


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    args = ap.parse_args()

    results = []
    for f in args.files:
        if not os.path.exists(f):
            print('找不到:', f); return 1
        tr, W, H, diag = per_trial(f)
        results.append((os.path.basename(f), tr, W, H, diag))
        print('=' * 78)
        print('%s   试次 %d   推断屏幕 %.0fx%.0f  对角线 %.0f' % (os.path.basename(f), len(tr), W, H, diag))
        print('   头部漂移(试次内眼中心位移) 中位=%.5f  最大=%.5f  (归一化坐标)'
              % (np.median([x['head_std'] for x in tr]), max(x['head_std'] for x in tr)))

        # 按目标所在屏幕分区统计
        print('\n   按目标位置分区（用统一系数 KX=%d KY=%d 计算误差）:' % (KX, KY))
        zones = {'左(0-40%%)': [], '中(40-60%%)': [], '右(60-100%%)': []}
        zy = {'上': [], '中': [], '下': []}
        for x in tr:
            ex = min(W, max(0.0, W / 2 + x['gx'] * KX))
            ey = min(H, max(0.0, H / 2 + x['gy'] * KY))
            e = float(np.hypot(ex - x['tx'], ey - x['ty']))
            frac = x['tx'] / W
            key = '左(0-40%%)' if frac < 0.4 else ('中(40-60%%)' if frac < 0.6 else '右(60-100%%)')
            zones[key].append(e)
            fy = x['ty'] / H
            zy['上' if fy < 0.4 else ('中' if fy < 0.6 else '下')].append(e)
        for k, v in zones.items():
            if v:
                print('     %-14s n=%2d  平均误差 %6.0f px  (%.4f 对角线)' % (k, len(v), np.mean(v), np.mean(v) / diag))
        for k, v in zy.items():
            if v:
                print('     y=%-11s n=%2d  平均误差 %6.0f px  (%.4f 对角线)' % (k, len(v), np.mean(v), np.mean(v) / diag))

        # 与头部漂移的相关
        e_all = []
        for x in tr:
            ex = min(W, max(0.0, W / 2 + x['gx'] * KX))
            ey = min(H, max(0.0, H / 2 + x['gy'] * KY))
            e_all.append(np.hypot(ex - x['tx'], ey - x['ty']))
        e_all = np.array(e_all)
        hd = np.array([x['head_std'] for x in tr])
        if hd.std() > 1e-9:
            print('\n   corr(单试次误差, 该试次头部漂移) = %+.3f' % np.corrcoef(e_all, hd)[0, 1])
            hi = hd > np.median(hd)
            print('   头部漂移大的那一半试次: 平均误差 %.0f px' % e_all[hi].mean())
            print('   头部漂移小的那一半试次: 平均误差 %.0f px' % e_all[~hi].mean())

        # 最差 6 个试次
        order = np.argsort(-e_all)[:6]
        print('\n   最差 6 个试次:')
        for i in order:
            x = tr[i]
            print('     #%-3d 目标(%5.0f,%4.0f)  误差 %6.0f px   gaze=(%+.5f,%+.5f)  头漂移std=%.5f  ear_min=%.3f'
                  % (x['trial'], x['tx'], x['ty'], e_all[i], x['gx'], x['gy'], x['head_std'], x['ear_min']))

    # 两次会话对比
    if len(results) >= 2:
        print('\n' + '=' * 78)
        print('两次采集对比（按目标位置配对，容差 30px）')
        (n1, t1, W1, H1, d1), (n2, t2, _, _, d2) = results[0], results[1]
        print('   %-26s %-26s' % (n1, n2))
        pairs = []
        for a in t1:
            best = min(t2, key=lambda b: np.hypot(a['tx'] - b['tx'], a['ty'] - b['ty']))
            if np.hypot(a['tx'] - best['tx'], a['ty'] - best['ty']) < 30:
                pairs.append((a, best))
        print('   可配对的目标点: %d' % len(pairs))
        e1a, e2a = [], []
        for a, b in pairs:
            ea = np.hypot(min(W1, max(0, W1 / 2 + a['gx'] * KX)) - a['tx'],
                          min(H1, max(0, H1 / 2 + a['gy'] * KY)) - a['ty'])
            eb = np.hypot(min(W1, max(0, W1 / 2 + b['gx'] * KX)) - b['tx'],
                          min(H1, max(0, H1 / 2 + b['gy'] * KY)) - b['ty'])
            e1a.append(ea); e2a.append(eb)
        e1a, e2a = np.array(e1a), np.array(e2a)
        print('   平均误差:  %-10.0f px              %-10.0f px' % (e1a.mean(), e2a.mean()))
        print('   gx 漂移(同一目标两次之差) 中位=%.5f 最大=%.5f'
              % (np.median([abs(a['gx'] - b['gx']) for a, b in pairs]),
                 max(abs(a['gx'] - b['gx']) for a, b in pairs)))
        print('   gy 漂移 中位=%.5f 最大=%.5f'
              % (np.median([abs(a['gy'] - b['gy']) for a, b in pairs]),
                 max(abs(a['gy'] - b['gy']) for a, b in pairs)))
        worse = [p for p, ea, eb in zip(pairs, e1a, e2a) if eb > ea * 1.5]
        print('   新会话明显变差(>1.5x)的点: %d / %d' % (len(worse), len(pairs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
