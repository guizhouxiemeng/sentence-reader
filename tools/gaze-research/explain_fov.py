#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
explain_fov.py — 说明"手移出画面"的几何原因，以及它对本项目的影响

现场现象
--------
检出率从 91% 掉到 23%，指尖 y = 0.988（几乎贴着画面下边缘）。
使用者为了"画一个尽量大的方框"，手移出了摄像头视野。

这不是实现问题，而是【摄像头视野角】与【屏幕尺寸】之间的固定几何关系。
本脚本把这条关系算清楚，用来指导"手应该离摄像头多远"。

核心计算
--------
设：
  D  = 手到摄像头的距离
  FOV= 摄像头水平视野角
  W  = 摄像头在距离 D 处能看到的宽度 = 2·D·tan(FOV/2)

若手要在屏幕前方滑动（滑动平面距摄像头 D），则：
  · 摄像头能看到的手部活动宽度上限就是 W
  · 屏幕越宽、D 越小 → 能被看到的活动范围占屏幕的比例越小

用法： python tools/explain_fov.py
"""
import math
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main():
    # 本项目的实测环境
    SCREEN_W_CM = 55.0      # 2560x1600 16:10，约 55cm 宽
    SCREEN_H_CM = 34.0
    CAM_FOV_H = 60.0        # 普通网络摄像头水平视野角约 60°
    CAM_FOV_V = 36.0        # 16:9 传感器，垂直约 36°

    print('=' * 78)
    print('摄像头视野 vs 屏幕尺寸：为什么"手会移出画面"')
    print('=' * 78)
    print('  本项目环境：屏幕约 %.0f×%.0f cm，网络摄像头水平视野约 %.0f°'
          % (SCREEN_W_CM, SCREEN_H_CM, CAM_FOV_H))
    print()
    print('  %-14s %-14s %-14s %-14s %s'
          % ('手距摄像头', '相机可见宽度', '占屏幕宽比例', '可见高度', '说明'))
    print('  ' + '-' * 74)
    for D in (30, 40, 50, 60, 80, 100, 120):
        W = 2 * D * math.tan(math.radians(CAM_FOV_H / 2))
        H = 2 * D * math.tan(math.radians(CAM_FOV_V / 2))
        frac = W / SCREEN_W_CM
        note = ''
        if frac < 0.8:
            note = '★ 手要够到全屏就必须出画'
        elif frac < 1.1:
            note = '勉强够用'
        else:
            note = '够用'
        print('  %-14s %-14s %-14s %-14s %s'
              % ('%.0f cm' % D, '%.1f cm' % W, '%.0f%%' % (frac * 100),
                 '%.1f cm' % H, note))

    print('\n' + '=' * 78)
    print('结论与对策')
    print('=' * 78)
    print('  1. 手在屏幕前方滑动时，距摄像头约等于"观看距离"（通常 50~70cm）。')
    print('     此时摄像头可见宽度只有约 55~80cm，与屏幕宽度同量级 ——')
    print('     所以【手滑到屏幕边缘就很容易出画】。这是几何必然，不是 bug。')
    print()
    print('  2. 因此正确的做法不是"让手覆盖全屏"，而是：')
    print('     · 接受手部可达范围小于全屏（可能只有中间的 50~70%）')
    print('     · 把【界面元素也放在这个范围内】—— 标定区域与目标区域保持一致')
    print('     · 这与虹膜方案的结论是同一条：界面必须适配传感器的能力边界')
    print()
    print('  3. 若确实想扩大范围，只有两条路：')
    print('     · 把手往外移（离摄像头更远）→ 可见范围变大，但手在画面里变小，')
    print('       关键点精度下降，而且离屏幕太远难以判断位置')
    print('     · 换广角摄像头（FOV 90°~120°）→ 可见宽度提升 1.7~3.5 倍，')
    print('       这是真正有效的硬件解法')
    return 0


if __name__ == '__main__':
    sys.exit(main())
