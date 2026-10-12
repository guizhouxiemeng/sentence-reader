#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fov_reach.py — 可达性 vs 可见性：手伸向屏幕时的视野覆盖

起因
----
现场反馈："按理来讲手是能够到全屏的，但出画是可能的"。
这句话点出了我之前混为一谈的两件事：

    · 可达性（reach）  —— 手能不能物理上摸到屏幕的那个点
    · 可见性（visible）—— 在那个位置时，手是否还在摄像头画面里

手当然能摸到全屏。真正的问题是在边缘位置时手会离开摄像头视野。

而且这里有一个重要的几何推论：手伸向屏幕时【离摄像头更远】，
而摄像头可见范围与距离成正比 —— 所以伸展开的姿势反而能覆盖更大的区域。
"够不到边缘"很可能是姿势问题（手收在胸前），而不是能力问题。

用法： python tools/fov_reach.py
"""
import math
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

SCREEN_W = 55.0        # 屏幕宽 cm（2560x1600 约 16 寸）
FOV_H = 60.0           # 网络摄像头水平视野角
TAN_HALF = math.tan(math.radians(FOV_H / 2))


def visible_width(d):
    return 2 * d * TAN_HALF


def main():
    print('=' * 80)
    print('手的位置如何决定"可见范围"')
    print('=' * 80)
    print('  摄像头在屏幕顶部朝前看，屏幕宽约 %.0f cm，水平视野 %.0f 度' % (SCREEN_W, FOV_H))
    print('  可见宽度 = 2 × 距离 × tan(视野/2)')
    print()
    print('  %-24s %-12s %-14s %-14s %s'
          % ('手的姿势', '距摄像头', '可见宽度', '占屏幕宽', '能覆盖全屏'))
    print('  ' + '-' * 78)
    rows = [
        ('手收在胸前', 30),
        ('手在胸前偏前', 40),
        ('手伸到中间', 50),
        ('手伸向屏幕', 60),
        ('手贴屏幕', 70),
    ]
    for name, d in rows:
        w = visible_width(d)
        ok = '可以' if w >= SCREEN_W else '差 %.0f cm' % (SCREEN_W - w)
        print('  %-24s %-12s %-14s %-14s %s'
              % (name, '%.0f cm' % d, '%.1f cm' % w,
                 '%.0f%%' % (w / SCREEN_W * 100), ok))

    print()
    print('=' * 80)
    print('结论')
    print('=' * 80)
    need_d = SCREEN_W / (2 * TAN_HALF)
    print('  1. 要覆盖整块屏幕，手至少要离摄像头 %.0f cm。' % need_d)
    print('     手收在胸前时距摄像头只有 30~40 cm，可见宽度仅 %.0f~%.0f cm'
          % (visible_width(30), visible_width(40)))
    print('     —— 这就是"出画"的真正原因：不是手够不到，是手离摄像头太近。')
    print()
    print('  2. 手伸向屏幕时距离自然增大到 55~70 cm，可见宽度 %.0f~%.0f cm，'
          % (visible_width(55), visible_width(70)))
    print('     足以覆盖整块屏幕。所以【伸展开的姿势反而更容易覆盖全屏】。')
    print()
    print('  3. 实践建议（写进 demo 的校准指导语）：')
    print('     · 手伸向屏幕，不要收在胸前')
    print('     · 触到屏幕边缘时手应该仍在画面内；若出画，说明手太靠近摄像头了，')
    print('       把手往屏幕方向多伸一点即可')
    print('     · 不要靠桌面 —— 靠桌会把手指压到画面下缘之外')
    print()
    print('  4. 这与"界面适配传感器边界"并不矛盾，二者是不同层次的应对：')
    print('     · 姿势调整   → 扩大可见范围（首选，不损失任何精度）')
    print('     · 缩小界面   → 在姿势无法调整时的退让')
    print('     应该先试姿势，再考虑缩小界面。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
