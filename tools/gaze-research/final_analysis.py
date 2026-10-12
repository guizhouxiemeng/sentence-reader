#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
final_analysis.py — 指尖交互的"目标尺寸 → 可用性"曲线与容量推算

实测数据（使用者报告 + 测试界面记录）
------------------------------------
    半径110px → 8/8 (100%)   576ms
    半径 68px → 8/8 (100%)   692ms
    半径 44px → 8/8 (100%)   650ms
    半径 34px → 8/8 (100%)   710ms
    半径 27px → 8/8 (100%)  1113ms   ← 耗时台阶
    半径 22px → 8/8 (100%)   604ms   ← 使用者报告"从这里开始吃力"
    半径 17px → 8/8 (100%)  1135ms
    半径 12px → 8/8 (100%)  1436ms

两个关键事实：
  ① 命中率全程 100% —— 连 12px 都能全部选中，精度远超预期
  ② 限制来自【耗时/稳定性】而不是【命中率】—— 从某一档开始要明显更小心

本脚本把这条曲线变成可用的设计结论：
  · 命中率阈值与耗时阈值分别给出
  · 换算成"单屏容量"与"桌面图标场景是否需要分级"
  · 对照设计文档的假设，指出需要修正之处

用法： python tools/final_analysis.py
"""
import math
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 实测数据：(半径px, 命中数, 总数, 中位耗时ms)
DATA = [
    (110, 8, 8, 576),
    (68, 8, 8, 692),
    (44, 8, 8, 650),
    (34, 8, 8, 710),
    (27, 8, 8, 1113),
    (22, 8, 8, 604),
    (17, 8, 8, 1135),
    (12, 8, 8, 1436),
]

# 使用者主观报告的"开始吃力"位置
REPORTED_LIMIT = 22

W_CSS, H_CSS = 1353, 810          # 实测视口（CSS px）
DIAG_CSS = math.hypot(W_CSS, H_CSS)


def main():
    print('=' * 84)
    print('一、实测曲线')
    print('=' * 84)
    print('  视口 %dx%d CSS px（对角线 %.0f）' % (W_CSS, H_CSS, DIAG_CSS))
    print()
    base = DATA[0][3]
    print('  %-10s %-8s %-12s %-12s %-12s %s'
          % ('半径px', '直径px', '命中率', '中位耗时', '相对基线', '判读'))
    print('  ' + '-' * 78)
    for r, hit, tot, ms in DATA:
        ratio = ms / base
        if ratio < 1.4:
            verdict = '轻松'
        elif ratio < 1.9:
            verdict = '开始要小心'
        else:
            verdict = '明显吃力'
        mark = '  ← 使用者报告"从这里开始吃力"' if r == REPORTED_LIMIT else ''
        print('  %-10d %-8d %-12s %-12s %-12s %s%s'
              % (r, r * 2, '%d/%d (%.0f%%)' % (hit, tot, 100 * hit / tot),
                 '%dms' % ms, '%.2fx' % ratio, verdict, mark))

    print()
    print('=' * 84)
    print('二、两个判据分别给出的下限')
    print('=' * 84)
    hit_ok = [r for r, h, t, _ in DATA if h / t >= 0.75]
    eff_ok = [r for r, h, t, ms in DATA if h / t >= 0.75 and ms <= base * 1.8]
    print('  ① 命中率判据（≥75%%）：最小半径 %dpx' % min(hit_ok))
    print('     含义：能点中。实测连 12px 都满足 —— 精度不是限制。')
    print()
    print('  ② 耗时判据（≤基线1.8倍 = %dms）：最小半径 %dpx'
          % (int(base * 1.8), min(eff_ok)))
    print('     含义：不需要刻意放慢、屏住呼吸。这才是实际限制。')
    print()
    print('  ③ 使用者主观报告："%dpx 开始吃力"' % REPORTED_LIMIT)
    print()
    print('  → 三者中 ① 最宽松、② 与 ③ 一致落在 20~27px 区间。')
    print('    说明【限制来自稳定性/体力负荷，不是定位精度】。')

    print()
    print('=' * 84)
    print('三、容量推算：桌面图标场景需不需要"定框→放大→重排"')
    print('=' * 84)
    DESIGN_R = 27          # 取耗时判据与主观报告的共同下限，留一点余量
    d = DESIGN_R * 2
    cols = int(W_CSS / d)
    rows = int(H_CSS / d)
    cap = cols * rows
    print('  取设计半径 %dpx（直径 %dpx = %.3f 屏幕对角线）'
          % (DESIGN_R, d, d / DIAG_CSS))
    print('  单屏容量 = %d 列 × %d 行 = %d 个目标' % (cols, rows, cap))
    print()
    for n, name in [(20, '桌面快捷方式（较少）'), (30, '桌面快捷方式（较多）'),
                    (48, '设计文档的 48 阈值'), (100, '设计文档的 100 阈值')]:
        print('  %-22s %3d 个 → 占容量 %5.1f%%　%s'
              % (name, n, 100 * n / cap,
                 '一级足够' if n <= cap else '需要分级'))
    print()
    print('  对照设计文档的假设：')
    print('    文档：半径 205px → 单屏约 18~24 个 → 桌面图标"正好卡在边界"→ 需要一级+重排')
    print('    实测：半径 %dpx  → 单屏 %d 个     → 桌面图标只占 %.0f%%  → 一级足够'
          % (DESIGN_R, cap, 100 * 30 / cap))
    print('    文档假设的半径是实测下限的 %.1f 倍' % (205 / DESIGN_R))

    print()
    print('=' * 84)
    print('四、结论（可直接写进 README）')
    print('=' * 84)
    print('  1. 指尖绝对定位精度远好于预期：半径 12px（直径 24px）仍能 100% 选中。')
    print('     精度【不是】限制因素。')
    print()
    print('  2. 真正的限制是【稳定性 / 体力负荷】：半径小于约 %dpx 后，' % DESIGN_R)
    print('     命中率不变但耗时翻倍（%.2fx~%.2fx），表现为"要很小心、手会抖"。'
          % (1135 / base, 1436 / base))
    print('     这是可用性判据，不是精度判据 —— 两者的解法完全不同。')
    print()
    print('  3. 桌面图标场景（20~30 个）在半径 %dpx 下只需单屏的 %.0f%%，'
          % (DESIGN_R, 100 * 30 / cap))
    print('     【不需要】"定框 → 放大 → 重排"的多级机制。')
    print()
    print('  4. 但"定框 + 放大"仍有价值，只是价值点不同：')
    print('     它不解决"点不准"，而是解决"要很小心" —— 目标放大后')
    print('     同样的手部稳定性就能满足停留要求，体力负荷下降。')
    print('     所以该机制应定位为【降低精细控制要求】，而不是【提高精度】。')
    print()
    print('  5. 能力边界（必须如实标注）：')
    print('     · 单被试、每档仅 8 次，样本小（22px 那档 604ms 是可能的异常值）')
    print('     · 耗时含"从提示出现到选中"的全过程，未扣除反应时间')
    print('     · 结论适用于本硬件与 1.54x 灵敏度设置')
    return 0


if __name__ == '__main__':
    sys.exit(main())
