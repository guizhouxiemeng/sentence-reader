#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
quality.py — 会话信号质量评分（这是预测模型精度的真正指标）

背景：我们连续证伪了两个"直觉上应该有用"的采集参数：
  · iod（脸离摄像头多近）      → 0.286 的那次(0.152)优于 0.376 的那次(0.205)
  · 头位漂移                   → 5px 的那次(0.170)差于 9px 的那次(0.152)

后来发现真正的预测因子是**特征与目标的相关系数**（直接测量信号本身）：
    r(gx,tx) 与 r(gy,ty) 的平均 |r| → 与最终 MLP 误差单调对应
    0.846 → 0.145
    0.741 → 0.152
    0.633 → 0.170
    0.559 → 0.205

用途：
  1. 采完立刻评估这份数据值不值得投入训练
  2. 多次采集之间，挑信号最好的那份做交互研究
  3. 作为"采集质量"的可量化定义，写进 README

用法：
  python tools/quality.py *.csv
  python tools/quality.py *.csv --min-r 0.65      # 只保留达标的
"""
import argparse
import csv
import glob
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def load(path):
    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot'] if 'phase' in c else rows
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    iod = col('iod') + 1e-9
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / iod
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / iod
    tx = np.array([float(r[c['tx']]) for r in d])
    ty = np.array([float(r[c['ty']]) for r in d])
    tr = np.array([int(r[c['trial']]) for r in d])
    return dict(gx=gx, gy=gy, tx=tx, ty=ty, tr=tr, iod=iod,
                ex=col('eyecenter_x'), ey=col('eyecenter_y'), n=len(d))


def score(path):
    s = load(path)
    rx = float(np.corrcoef(s['gx'], s['tx'])[0, 1])
    ry = float(np.corrcoef(s['gy'], s['ty'])[0, 1])
    # 取绝对值再平均：符号由摄像头镜像决定，无信息量
    rmean = (abs(rx) + abs(ry)) / 2.0

    W = (s['tx'].max() - s['tx'].min()) / 0.84
    H = (s['ty'].max() - s['ty'].min()) / 0.84
    diag = float(np.hypot(W, H))

    # 头位漂移（像素）
    mx = np.array([s['ex'][s['tr'] == t].mean() for t in np.unique(s['tr'])])
    my = np.array([s['ey'][s['tr'] == t].mean() for t in np.unique(s['tr'])])
    drift_x = (mx.max() - mx.min()) * 640
    drift_y = (my.max() - my.min()) * 480

    # 特征动态范围（归一化后）
    return dict(
        name=os.path.basename(path), n=s['n'], r_x=rx, r_y=ry, r=rmean,
        iod=float(np.median(s['iod'])), drift_x=drift_x, drift_y=drift_y,
        gx_range=float(s['gx'].max() - s['gx'].min()),
        gy_range=float(s['gy'].max() - s['gy'].min()),
        diag=diag,
    )


def verdict(r):
    if r >= 0.80:
        return '优秀', '实测可达 0.14~0.15 对角线'
    if r >= 0.70:
        return '良好', '实测约 0.15~0.16'
    if r >= 0.62:
        return '可用', '实测约 0.17；交互研究够用，追求最佳精度需重采'
    return '偏弱', '实测 >0.20，建议重采而非投入训练'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='+')
    ap.add_argument('--min-r', type=float, default=None, help='只列出达标文件')
    args = ap.parse_args()

    files = []
    for pat in args.files:
        files.extend(sorted(glob.glob(pat)) or ([pat] if os.path.exists(pat) else []))

    if not files:
        print('没有匹配的文件')
        return 1

    rows = [score(f) for f in files]
    rows.sort(key=lambda x: -x['r'])

    print('=' * 96)
    print('会话信号质量评分   （r = 特征与目标相关系数，取 |r(gx,tx)| 与 |r(gy,ty)| 的均值）')
    print('=' * 96)
    print('%-26s %7s %7s %7s %8s %8s %9s %8s' %
          ('文件', 'r(gx,tx)', 'r(gy,ty)', '平均|r|', 'iod', '横漂px', '纵漂px', '帧数'))
    print('-' * 96)
    for x in rows:
        print('%-26s %+7.3f %+7.3f %7.3f %8.3f %8.0f %9.0f %8d' %
              (x['name'], x['r_x'], x['r_y'], x['r'], x['iod'],
               x['drift_x'], x['drift_y'], x['n']))
    print('-' * 96)
    print('%-26s %7s %7s %7.3f' % ('评级阈值', '', '', 0.0))
    for x in rows:
        v, exp = verdict(x['r'])
        print('   %-26s %-6s %s' % (x['name'], v, exp))

    best = rows[0]
    print('\n结论：')
    print('  · 信号最好的会话是 %s（|r|=%.3f）' % (best['name'], best['r']))
    print('  · 注意 iod 与头位漂移都**不能**预测精度：')
    print('      p1 的 iod 最大(0.376)却最差；p478309 的漂移最小(5px)却不如 p463357(9px)。')
    print('      所以选数据看这一列 |r|，不要看采集参数。')
    if args.min_r is not None:
        keep = [x['name'] for x in rows if x['r'] >= args.min_r]
        print('\n  · |r| >= %.2f 的文件：%s' % (args.min_r, ', '.join(keep) if keep else '（无）'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
