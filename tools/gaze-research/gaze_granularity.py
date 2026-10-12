#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
gaze_granularity.py — 把视线精度换算成"能分辨多大的区域"

实测（tools/eyetrax_accuracy_test.py，2026-02，1280x720 摄像头）：
    EyeTrax 486 维  平均误差 720 px = 0.2384 屏幕对角线
    自建  7  维     平均误差 822 px = 0.2724 屏幕对角线

结论：EyeTrax 只比自建方案好 12%（0.88x），而它用了 69 倍的特征
（486 vs 7）。也就是说 —— 【特征不是瓶颈】，精度由硬件决定。

本脚本把这个误差换算成设计参数：能分几个区域、最小可靠单元多大。
这决定"注意力预测层"该用什么响应粒度。

用法： python tools/gaze_granularity.py
"""
import math
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 实测结果（1280x720 摄像头）
MEASURED = {
    'EyeTrax 486维': dict(mean_px=719.8,  norm_mean=0.2384, p90_px=1092.4),
    '自建 7维':      dict(mean_px=822.0,  norm_mean=0.2724, p90_px=1120.0),
}

# 被测量的屏幕（全屏 9 点测试）与使用者日常的逻辑视口
SCREEN = dict(w=2560, h=1600, note='全屏测试时的屏幕')
VIEWPORT = dict(w=1600, h=900, note='日常逻辑视口（若全屏浏览器）')


def diag(w, h):
    return math.hypot(w, h)


def main():
    sd = diag(SCREEN['w'], SCREEN['h'])
    print('=' * 82)
    print('一、实测精度')
    print('=' * 82)
    print('  条件：摄像头 1280x720（已经是 640x480 的 4 倍像素），')
    print('        屏幕 %dx%d（对角线 %.0f）' % (SCREEN['w'], SCREEN['h'], sd))
    print()
    print('  %-16s %-12s %-16s %-14s %s'
          % ('方案', '特征维度', '平均误差', '归一化', 'p90'))
    print('  ' + '-' * 78)
    print('  %-16s %-12s %-16s %-14s %s'
          % ('EyeTrax', '486', '%.0f px' % MEASURED['EyeTrax 486维']['mean_px'],
             '%.4f 对角线' % MEASURED['EyeTrax 486维']['norm_mean'],
             '%.0f px' % MEASURED['EyeTrax 486维']['p90_px']))
    print('  %-16s %-12s %-16s %-14s %s'
          % ('自建方案', '7', '%.0f px' % MEASURED['自建 7维']['mean_px'],
             '%.4f 对角线' % MEASURED['自建 7维']['norm_mean'],
             '%.0f px' % MEASURED['自建 7维']['p90_px']))
    print()
    ratio = MEASURED['EyeTrax 486维']['mean_px'] / MEASURED['自建 7维']['mean_px']
    print('  EyeTrax / 自建 = %.2f 倍，而特征数之比 = 486 / 7 = %.0f 倍'
          % (ratio, 486 / 7))
    print('  → 特征增加 %.0f 倍只换来 %.0f%% 的误差下降。' % (486 / 7, (1 - ratio) * 100))
    print('    【特征不是瓶颈】—— 这一条是本次测量的核心结论。')

    print()
    print('=' * 82)
    print('二、换算成"能分辨多大的区域"')
    print('=' * 82)
    print('  判据：两个区域要能被区分，间距必须 ≥ 2 倍定位误差')
    print('        （否则同一位置可能落在任一区域内）')
    print()
    for name, m in MEASURED.items():
        err_screen = m['norm_mean'] * sd
        # 换算到日常视口（按对角线比例缩放）
        vd = diag(VIEWPORT['w'], VIEWPORT['h'])
        err_view = m['norm_mean'] * vd
        min_region = err_view * 2
        cols = int(VIEWPORT['w'] / min_region)
        rows = int(VIEWPORT['h'] / min_region)
        print('  %s：' % name)
        print('     全屏测试时误差      %.0f px' % err_screen)
        print('     日常视口误差        %.0f px（按对角线比例换算）' % err_view)
        print('     最小可分辨区域      约 %.0f px' % min_region)
        print('     可分辨区格数        %d 列 x %d 行 = %d 个'
              % (cols, rows, cols * rows))
        print()

    print('=' * 82)
    print('三、粒度对照：这个精度能支撑什么')
    print('=' * 82)
    vd = diag(VIEWPORT['w'], VIEWPORT['h'])
    err = MEASURED['EyeTrax 486维']['norm_mean'] * vd
    print('  取 EyeTrax（较好的那个）误差 %.0f px，对比各种阅读粒度：' % err)
    print()
    print('  %-22s %-16s %-14s %s' % ('粒度', '典型尺寸', '与误差之比', '可行性'))
    print('  ' + '-' * 76)
    items = [
        ('单个英文字母', 12, '不可行'),
        ('单个汉字', 28, '不可行'),
        ('单个词（英文）', 80, '不可行'),
        ('一整行文字', 700, '勉强（行是横长条，纵向更准）'),
        ('一个段落', 900, '可行'),
        ('一个栏（左/右半屏）', 800, '可行'),
        ('一个版块（上/中/下）', 300, '勉强'),
    ]
    for label, size, note in items:
        r = size / err
        if r >= 1.5:
            mark = 'OK'
        elif r >= 0.8:
            mark = 'borderline'
        else:
            mark = 'NO'
        print('  %-22s %-16s %-14s %s (%s)'
              % (label, '%d px' % size, '%.2f' % r, mark, note))
    print()
    print('  关键判断：')
    print('    · 词级及更细 —— 不可行（误差比目标大一个数量级）')
    print('    · 段落级、栏级 —— 可行（这正是"处理受阻"检测需要的粒度）')
    print()
    print('  → 所以"注意力预测层"的空间粒度【必须】是段落/版块级，')
    print('    不能是词级。这与设计文档里"停留时长 + 回看次数"的')
    print('    时间统计量思路是【一致】的 —— 两者都不要求词级定位。')

    print()
    print('=' * 82)
    print('四、对"认知状态推断层"的三个具体约束')
    print('=' * 82)
    print('  1. 回看检测的对象是【段落】，不是词')
    print('     可分辨区格约 %d 个，所以"回看"只能定义为'
          % (int(VIEWPORT['w'] / (2 * err)) * int(VIEWPORT['h'] / (2 * err))))
    print('     "视线离开某段后又回到该段"（段级），不能是"回看某个词"。')
    print()
    print('  2. 停留时长的空间归属精度 = 段落级')
    print('     因此"某段停留异常长"是可靠信号；"某个词停留长"不是。')
    print()
    print('  3. 扫视方向仍有价值，但要在区格层面解读')
    print('     从"左栏→右栏"这类大跨度扫视可靠；')
    print('     同一段内的小幅跳读不可靠。')
    print()
    print('  这三条都是【可执行的设计约束】，而不是"精度不够所以做不了"。')
    print('  换句话说：这个项目的响应粒度应当是段落级 —— 恰好与')
    print('  "静默准备术语解释"这种响应形式匹配（它本来就不需要词级定位）。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
