#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
test_anchors.py — 寻找不被眼皮污染的垂直视线特征

已证实的污染：demo 的 gaze_y = (虹膜y - 眼睛中心y)/瞳距，
与眼皮开合 EAR 的相关性高达 -0.917。分因是"眼睛中心"由四个眼角平均得到，
而内眼角的 y 随上眼睑移动。

本脚本用已有的 39 维特征测试各种垂直锚点方案，按两个标准排序：
  1. |r(特征, EAR)| 越小越好 —— 不受眼皮影响
  2. |r(特征, 目标y)| 越大越好 —— 真的反映视线
并报告"净信号" = |r(目标)| 与 |r(眼皮)| 的相对强度。

用法： python tools/test_anchors.py
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
    m = json.load(open(MANIFEST, encoding='utf-8'))
    idx = m['index']
    F = np.array([r['f'] for r in idx], dtype=np.float64)
    tx = np.array([r['tx'] for r in idx])
    ty = np.array([r['ty'] for r in idx])
    c = {n: F[:, i] for i, n in enumerate(FEAT_NAMES) if i < F.shape[1]}

    ear = (c['earL'] + c['earR']) / 2
    iod = c['iod'] + 1e-9
    irx = (c['irisL_x'] + c['irisR_x']) / 2
    iry = (c['irisL_y'] + c['irisR_y']) / 2

    print('=' * 84)
    print('垂直锚点候选（目标是"低眼皮相关 + 高视线相关"）')
    print('=' * 84)
    print('  %-30s %11s %11s %11s %s' % ('特征', 'r(眼皮)', 'r(目标y)', 'r(目标x)', '净信号'))
    print('  ' + '-' * 80)

    cands = {
        # 现有（已被证明污染）
        'gaze_y 现有(眼角均值锚点)': (iry - c['eyecenter_y']) / iod,
        # 纯单眼角锚点
        '虹膜y - 左眼外角y': (c['irisL_y'] - c['eyeOL_y']) / iod,
        '虹膜y - 左眼内角y': (c['irisL_y'] - c['eyeIL_y']) / iod,
        '虹膜y - 右眼外角y': (c['irisR_y'] - c['eyeOR_y']) / iod,
        '虹膜y - 左右外角均值y': (iry - (c['eyeOL_y'] + c['eyeOR_y']) / 2) / iod,
        # 不含眼角的纯几何量
        '虹膜y (绝对值)': iry,
        '虹膜y / 瞳距': iry / iod,
        # 相对头部其他部位（鼻子/额头），看头部是否更稳定
        '虹膜y - 鼻尖y': (iry - c['nose_y']) / iod,
        '虹膜y - 额头y': (iry - c['fore_y']) / iod,
        '虹膜y - 下巴y': (iry - c['chin_y']) / iod,
        # 两眼虹膜自身的相对量（完全不含眼角与眼睑）
        '左右虹膜y之差': c['irisR_y'] - c['irisL_y'],
        # 水平方向的对照（已知干净）
        'gaze_x 现有': (irx - c['eyecenter_x']) / iod,
        '虹膜x - 左右外角均值x': (irx - (c['eyeOL_x'] + c['eyeOR_x']) / 2) / iod,
    }

    rows = []
    for name, v in cands.items():
        r_ear = abs(corr(v, ear))
        r_ty = abs(corr(v, ty))
        r_tx = abs(corr(v, tx))
        # 净信号：视线相关 / 眼皮相关。> 1 表示信号强于干扰
        net = r_ty / (r_ear + 1e-6)
        rows.append((name, r_ear, r_ty, r_tx, net))
    rows.sort(key=lambda r: -r[4])
    for name, r_ear, r_ty, r_tx, net in rows:
        flag = ''
        if r_ear > 0.5:
            flag = '  ✗ 污染'
        elif net > 1.0:
            flag = '  ✓ 可用'
        print('  %-30s %+11.3f %+11.3f %+11.3f %9.2f%s'
              % (name, r_ear, r_ty, r_tx, net, flag))

    print('\n' + '=' * 84)
    print('水平锚点候选（对照：水平方向本就较干净）')
    print('=' * 84)
    for name, v in list(cands.items())[-2:]:
        print('  %-30s r(眼皮)=%+.3f  r(目标x)=%+.3f  r(目标y)=%+.3f'
              % (name, corr(v, ear), corr(v, tx), corr(v, ty)))

    print('\n结论判据：')
    print('  · 净信号 = |r(目标y)| / |r(眼皮)|，> 1 才说明视线信号强于眼皮干扰')
    print('  · 右边带 ✓ 的候选可直接替换 demo 的 gaze_y')
    return 0


if __name__ == '__main__':
    sys.exit(main())
