#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_eyelid2.py — 用已有的 39 维特征验证"眼皮污染"假设

用户的关键诊断：
  · 静止盯住中心，小球仍自己乱动，死区调到 400 也无效
  · 用力睁大眼会让小球大幅偏移甚至飞掉
  · 眨眼时小球向下动 —— "感觉追踪的是眼皮而不是眼球"

假设链条：
  1. demo 的 gaze_y = (虹膜_y - 眼睛中心_y) / 瞳距
  2. 眼睛中心 = 四个眼角坐标的平均
  3. 眼角（尤其外角）的检测位置随上眼睑移动
  → 所以眼皮一动，锚点动，gaze_y 变，光标跟着动

可验证的部分：如果 eyecenter_y 与 ear（眼睑开合度）显著相关，
说明"眼睛中心"确实被眼皮带动。同时看 gaze 系列特征与 ear 的相关性。

数据来源：data/eyes_p029379/manifest.json（4435 帧 / 39 维特征）

用法： python tools/test_eyelid2.py
"""
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
MANIFEST = os.path.join(ROOT, 'data', 'eyes_p029379', 'manifest.json')

FEAT_NAMES = ['L_h','L_v','L_h2','L_v2','R_h','R_v','R_h2','R_v2',
              'iod','earL','earR','yaw','pitch',
              'irisL_x','irisL_y','irisL_z','irisR_x','irisR_y','irisR_z',
              'eyeOL_x','eyeOL_y','eyeOR_x','eyeOR_y','eyeIL_x','eyeIL_y','eyeIR_x','eyeIR_y',
              'eyecenter_x','eyecenter_y','fore_z',
              'nose_x','nose_y','chin_x','chin_y','fore_x','fore_y',
              'z_irisL','z_irisR','z_nose']


def corr(a, b):
    if a.std() < 1e-12 or b.std() < 1e-12:
        return 0.0
    v = np.corrcoef(a, b)[0, 1]
    return 0.0 if not np.isfinite(v) else v


def main():
    if not os.path.exists(MANIFEST):
        print('找不到', MANIFEST)
        return 1
    m = json.load(open(MANIFEST, encoding='utf-8'))
    idx = m['index']
    print('载入 %d 帧' % len(idx))
    F = np.array([r['f'] for r in idx], dtype=np.float64)
    tx = np.array([r['tx'] for r in idx])
    ty = np.array([r['ty'] for r in idx])
    col = {n: F[:, i] for i, n in enumerate(FEAT_NAMES) if i < F.shape[1]}
    print('特征维度: %d' % F.shape[1])

    ear = (col['earL'] + col['earR']) / 2
    iod = col['iod'] + 1e-9
    print('\nEAR（眼睑开合）范围: %.3f .. %.3f   std %.4f' % (ear.min(), ear.max(), ear.std()))

    # 关键派生量：demo 用的 gaze_x / gaze_y（以眼睛中心为锚点）
    irx = (col['irisL_x'] + col['irisR_x']) / 2
    iry = (col['irisL_y'] + col['irisR_y']) / 2
    gx = (irx - col['eyecenter_x']) / iod
    gy = (iry - col['eyecenter_y']) / iod

    print('\n' + '=' * 76)
    print('【核心验证】各量与"眼皮开合 EAR"的相关性')
    print('  |r| 大 = 该量随眼皮移动 → 被眼皮污染')
    print('=' * 76)
    print('  %-26s %12s %s' % ('量', 'r(与EAR)', ''))
    rows = [
        ('瞳距 iod', col['iod']),
        ('眼睛中心 x', col['eyecenter_x']),
        ('眼睛中心 y  ←关键', col['eyecenter_y']),
        ('虹膜 x', irx),
        ('虹膜 y', iry),
        ('gaze_x (demo用)', gx),
        ('gaze_y (demo用)  ←关键', gy),
        ('L_v (虹膜-上睑)', col['L_v']),
        ('R_v (虹膜-上睑)', col['R_v']),
        ('yaw', col['yaw']),
        ('pitch', col['pitch']),
    ]
    for name, v in rows:
        r = corr(v, ear)
        n = int(abs(r) * 40)
        mark = '  ← 污染严重' if abs(r) > 0.5 else ('  ← 中等' if abs(r) > 0.3 else '')
        print('  %-26s %+12.3f  %s%s' % (name, r, '#' * n, mark))

    print('\n' + '=' * 76)
    print('【眼睛中心是否被眼皮带着走】')
    print('  用 EAR 分位把帧分成"睁大"和"眯眼"两组，看眼睛中心 y 差多少')
    print('=' * 76)
    lo = ear < np.percentile(ear, 20)      # 最眯的 20%
    hi = ear > np.percentile(ear, 80)      # 最睁的 20%
    for name, v in [('眼睛中心 y', col['eyecenter_y']),
                    ('眼睛中心 x', col['eyecenter_x']),
                    ('虹膜 y', iry),
                    ('虹膜 x', irx),
                    ('gaze_y', gy),
                    ('gaze_x', gx),
                    ('L_v', col['L_v'])]:
        d = v[hi].mean() - v[lo].mean()
        rel = d / (v.std() + 1e-12)
        print('  %-16s 睁大组 - 眯眼组 = %+.5f   相当于 %.2f 个标准差'
              % (name, d, rel))
    print('\n判据：')
    print('  · 若"眼睛中心 y"在两组间差异明显 → 眼角锚点确实被眼皮带动，gaze_y 被污染')
    print('  · 若"L_v / R_v"（虹膜到上睑）差异最大 → 这两个特征几乎就是在测眼皮')
    return 0


if __name__ == '__main__':
    sys.exit(main())
