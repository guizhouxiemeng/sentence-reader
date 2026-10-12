#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_eyelid.py — 验证"特征被眼皮污染"的假设

用户观察（关键诊断）：
  · 静止盯住屏幕中心，小球仍自己乱动，死区调到 400 也无效
  · 用力睁大眼睛会让小球大幅偏移甚至飞掉
  · 眨眼时小球会向下动 —— "感觉追踪的是眼皮而不是眼球"

假设：demo 的 gaze_x / gaze_y 用了"眼睛中心"作锚点，而眼睛中心由四个眼角
坐标求平均得到。MediaPipe 的眼角检测位置会随上眼睑移动，所以眼皮一动锚点
就动，特征被污染。

验证方法：
  1. 从 jsonl（含原始 478 关键点）重建两种特征：
     A. 现有： (iris - eyeCenter)/iod      ← 怀疑被污染
     B. 候选： (iris - eyeOuter)/iod 等纯眼角锚点（眼角比眼睑稳定）
     C. 增加： 当前 EAR（眼睑开合度），用来量化"这一帧眼皮动了多少"
  2. 计算每个特征与 EAR 的相关性。相关性高 = 该特征被眼皮污染。
  3. 比较 A 与 B 的"污染程度"，并看用 B 做回归时精度是否更好。

用法： python tools/test_eyelid.py
"""
import csv
import json
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = r"D:\projects\gaze-project"
FILES = ['gaze_p411900', 'gaze_p463357', 'gaze_p496980']

LM = dict(eyeOuterL=33, eyeInnerL=133, eyeTopL=159, eyeBotL=145,
          eyeOuterR=263, eyeInnerR=362, eyeTopR=386, eyeBotR=374,
          irisL=468, irisR=473, chin=152, forehead=10, nose=1)


def load_raw(tag):
    """读 jsonl（含原始 478 关键点）。"""
    p = os.path.join(ROOT, tag + '_frames.jsonl')
    if not os.path.exists(p):
        return None
    rows = []
    with open(p, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            o = json.loads(line)
            if 'p' in o and o.get('phase') == 'dot':
                rows.append(o)
    if not rows:
        return None
    G = {k: {'x': [], 'y': []} for k in LM}
    for r in rows:
        pp = r['p']
        for k, i in LM.items():
            G[k]['x'].append(pp[i * 3])
            G[k]['y'].append(pp[i * 3 + 1])
    A = {k: {ax: np.array(v) for ax, v in d.items()} for k, d in G.items()}
    tx = np.array([r['tx'] for r in rows])
    ty = np.array([r['ty'] for r in rows])
    return A, tx, ty, len(rows)


def build(A):
    """构造对比特征集。"""
    d = lambda a, ax, b: A[a][ax] - A[b][ax]
    iod = np.hypot(d('eyeOuterR', 'x', 'eyeOuterL'), d('eyeOuterR', 'y', 'eyeOuterL')) + 1e-6
    irx = (A['irisL']['x'] + A['irisR']['x']) / 2
    iry = (A['irisL']['y'] + A['irisR']['y']) / 2
    # 现有锚点：四个眼角的平均
    ecx = (A['eyeOuterL']['x'] + A['eyeInnerL']['x'] + A['eyeOuterR']['x'] + A['eyeInnerR']['x']) / 4
    ecy = (A['eyeOuterL']['y'] + A['eyeInnerL']['y'] + A['eyeOuterR']['y'] + A['eyeInnerR']['y']) / 4
    # EAR：眼睑开合度（越大越睁）
    earL = np.hypot(d('eyeTopL', 'x', 'eyeBotL'), d('eyeTopL', 'y', 'eyeBotL')) / \
        (np.hypot(d('eyeOuterL', 'x', 'eyeInnerL'), d('eyeOuterL', 'y', 'eyeInnerL')) + 1e-6)
    earR = np.hypot(d('eyeTopR', 'x', 'eyeBotR'), d('eyeTopR', 'y', 'eyeBotR')) / \
        (np.hypot(d('eyeOuterR', 'x', 'eyeInnerR'), d('eyeOuterR', 'y', 'eyeInnerR')) + 1e-6)
    ear = (earL + earR) / 2

    feats = {
        # A. 现有（眼睛中心锚点）
        'A_gaze_x_eyeCenter': (irx - ecx) / iod,
        'A_gaze_y_eyeCenter': (iry - ecy) / iod,
        # B. 候选（纯眼角锚点：眼角比眼睑稳定）
        'B_iris_x_outer': (irx - (A['eyeOuterL']['x'] + A['eyeOuterR']['x']) / 2) / iod,
        'B_iris_y_outer': (iry - (A['eyeOuterL']['y'] + A['eyeOuterR']['y']) / 2) / iod,
        'B_L_h': d('irisL', 'x', 'eyeOuterL') / iod,
        'B_L_v': d('irisL', 'y', 'eyeOuterL') / iod,
        'B_R_h': d('irisR', 'x', 'eyeOuterR') / iod,
        'B_R_v': d('irisR', 'y', 'eyeOuterR') / iod,
        # 纯几何量：不含眼睑
        'C_iod': iod,
        'C_iris_dx': A['irisR']['x'] - A['irisL']['x'],
        'C_iris_dy': A['irisR']['y'] - A['irisL']['y'],
        # 眼睑相关（用于验证污染源）
        'EAR': ear,
        'eyelidL_y': A['eyeTopL']['y'],
        'eyelidR_y': A['eyeTopR']['y'],
    }
    return feats, ear


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else v


def main():
    allrows = []
    for tag in FILES:
        r = load_raw(tag)
        if r is None:
            print('跳过 %s（没有 jsonl）' % tag)
            continue
        A, tx, ty, n = r
        feats, ear = build(A)
        print('=' * 74)
        print('%s   %d 帧' % (tag, n))
        print('  EAR（眼睑开合）范围: %.3f .. %.3f   标准差 %.4f'
              % (ear.min(), ear.max(), ear.std()))
        print('-' * 74)
        print('  %-24s %10s %10s' % ('特征', 'r(与EAR)', 'r(与目标x或y)'))
        for name, v in feats.items():
            r_ear = corr(v, ear)
            r_tx = corr(v, tx)
            r_ty = corr(v, ty)
            rt = r_tx if abs(r_tx) > abs(r_ty) else r_ty
            flag = ''
            if abs(r_ear) > 0.5 and name[0] in 'AB':
                flag = '   ← 被眼皮污染'
            print('  %-24s %+10.3f %+10.3f%s' % (name, r_ear, rt, flag))
        allrows.append((tag, feats, ear, tx, ty))

    print('\n' + '=' * 74)
    print('汇总：被眼皮污染程度（|r(特征, EAR)| 的平均值，越小越好）')
    print('=' * 74)
    keys = list(allrows[0][1].keys())
    for k in keys:
        vals = [abs(corr(f[k], e)) for _, f, e, _, _ in allrows]
        bar = '#' * int(np.mean(vals) * 40)
        print('  %-24s %.3f  %s' % (k, np.mean(vals), bar))
    print('\n判据：|r| > 0.5 说明该特征随眼皮开合明显变化 —— 它就是"眨眼光标下移"的元凶。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
