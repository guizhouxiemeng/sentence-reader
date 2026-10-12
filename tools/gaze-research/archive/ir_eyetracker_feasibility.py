#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ir_eyetracker_feasibility.py — 红外眼动仪的可行性核算（动手前先算清几何）

为什么需要这份核算
------------------
本项目已用量化数据证明：640x480 网络摄像头 + MediaPipe 关键点做【视线坐标】
不可行，根因是眼睛只有约 25 像素（虹膜转动位移与关键点噪声同量级）。

红外方案要解决两件事：
  ① 眼睛像素数从 ~25 提到 100~400（提升 1~2 个数量级）
  ② 用【瞳孔中心 − 角膜反光点】这类几何量替代"拟合后的关键点"

但这两件事都依赖几何布置，布置错了就白买。本脚本把关键几何算清楚：
  · 眼睛在画面里能占多少像素（决定信噪比）
  · 亮瞳效应需要 LED 离光轴多近
  · 角膜反光点会不会跑出眼睛区域（太远就测不到）
  · 视线转动对应多少像素位移（决定角度分辨率）

用法： python tools/ir_eyetracker_feasibility.py
"""
import math
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 生理常数
EYE_WIDTH_MM = 30.0          # 眼角到眼角（外眦到内眦）约 30mm
EYE_WIDTH_CORNER_MM = 26.0   # 常用参考值
EYEBALL_RADIUS_MM = 12.0     # 眼球半径（旋转中心到角膜顶）
DIST_CORNEA_TO_CENTRE_MM = 13.0
IRIS_DIAM_MM = 12.0          # 虹膜直径随光照变化 10~13mm
PUPIL_DIAM_MM = (2.0, 8.0)   # 瞳孔直径范围


def fov_from_sensor(sensor_w_mm, focal_mm):
    return 2 * math.degrees(math.atan(sensor_w_mm / (2 * focal_mm)))


def px_per_mm(res_px, sensor_w_mm, focal_mm, dist_mm):
    """在距离 dist 处的像素/毫米（小孔成像）。"""
    # 放大率 = f / (d - f) ≈ f/d
    mag = focal_mm / max(dist_mm - focal_mm, 1e-6)
    return res_px / sensor_w_mm * mag


def main():
    print('=' * 84)
    print('一、眼睛能占多少像素（决定一切）')
    print('=' * 84)
    print('  小孔成像：放大率 = 焦距 / (距离 − 焦距)，像素/毫米 = 分辨率/靶面宽 × 放大率')
    print()
    print('  以常见模组为例：靶面 1/4" = 3.6mm 宽，640x480；另一组 1/2.9" = 5.6mm 宽，1920x1080')
    print()
    print('  %-26s %-10s %-12s %-14s %-14s %s'
          % ('模组', '分辨率', '焦距', '眼睛距离', '眼睛像素', '对比现状'))
    print('  ' + '-' * 80)

    configs = [
        ('1/4" 640x480  焦距3.6mm', 640, 3.6, 3.6, 200),
        ('1/4" 640x480  焦距3.6mm', 640, 3.6, 3.6, 150),
        ('1/4" 640x480  焦距3.6mm', 640, 3.6, 3.6, 100),
        ('1/2.9" 1080p  焦距3.6mm', 1920, 5.6, 3.6, 200),
        ('1/2.9" 1080p  焦距3.6mm', 1920, 5.6, 3.6, 150),
        ('1/2.9" 1080p  焦距3.6mm', 1920, 5.6, 3.6, 100),
        ('1/2.9" 1080p  焦距6mm', 1920, 5.6, 6.0, 150),
        ('现状：网络摄像头 60cm 处', 640, 3.6, 3.6, 600),
    ]
    for name, res, sensor, focal, dist in configs:
        ppm = px_per_mm(res, sensor, focal, dist)
        eye_px = ppm * EYE_WIDTH_MM
        fov = fov_from_sensor(sensor, focal)
        if dist == 600:
            note = '（本项目现状：约 25px）'
        elif eye_px >= 200:
            note = '很好'
        elif eye_px >= 100:
            note = '可用'
        else:
            note = '偏小'
        print('  %-26s %-10s %-12s %-14s %-14s %s'
              % (name, '%dx%d' % (res, res * 3 // 4), '%.1fmm' % focal,
                 '%dmm' % dist, '%.0f px' % eye_px, note))
    print()
    print('  注：视场角（决定能否装下整只眼）= 2·atan(靶面/2 / 焦距)：')
    for name, res, sensor, focal, dist in configs[:1] + configs[3:4]:
        print('      %-26s %.1f 度' % (name, fov_from_sensor(sensor, focal)))
    print()
    print('  结论：把模组挪到眼前 10~20cm、并选 1080p 模组，')
    print('        眼睛像素可从约 25 提升到 150~400 —— 这正是本项目最缺的那一个数量级。')

    print()
    print('=' * 84)
    print('二、视线转动的角度分辨率（决定精度上限）')
    print('=' * 84)
    print('  眼动仪的基本几何：眼球绕中心旋转，角膜顶（及瞳孔）随之位移。')
    print('  旋转中心到角膜顶约 %.0fmm，所以每度转动对应弧长约 %.2fmm。'
          % (DIST_CORNEA_TO_CENTRE_MM, DIST_CORNEA_TO_CENTRE_MM * math.pi / 180))
    print()
    arc_per_deg = DIST_CORNEA_TO_CENTRE_MM * math.pi / 180
    print('  %-26s %-14s %-18s %s' % ('模组', '像素/mm', '每度位移(px)', '理论角度分辨率'))
    print('  ' + '-' * 74)
    for name, res, sensor, focal, dist in [
            ('1/4" 640x480 @150mm', 640, 3.6, 3.6, 150),
            ('1/2.9" 1080p @150mm', 1920, 5.6, 3.6, 150),
            ('1/2.9" 1080p @100mm', 1920, 5.6, 3.6, 100),
            ('1/2.9" 1080p @100mm 焦距6mm', 1920, 5.6, 6.0, 100)]:
        ppm = px_per_mm(res, sensor, focal, dist)
        px_per_deg = ppm * arc_per_deg
        # 亚像素定位取 0.2px（亮瞳质心定位通常可达亚像素）
        ang_res = 0.2 / px_per_deg
        print('  %-26s %-14.0f %-18.2f %.3f 度' % (name, ppm, px_per_deg, ang_res))
    print()
    print('  对照：专用眼动仪 0.5~1 度；本项目视线方案约 5~7 度。')
    print('  注：角度分辨率是理论上限，实际受标定误差、头部漂移影响，通常差 2~5 倍。')

    print()
    print('=' * 84)
    print('三、亮瞳效应需要 LED 离光轴多近')
    print('=' * 84)
    print('  亮瞳原理：LED 与镜头同轴（或极近）时，光穿过瞳孔照到视网膜后')
    print('  原路返回，瞳孔呈亮斑。偏离光轴越多，回光越少。')
    print()
    print('  %-18s %-20s %s' % ('LED 离轴距离', '离轴角（眼距150mm）', '效果'))
    print('  ' + '-' * 66)
    for d_mm in (5, 10, 20, 40, 80):
        ang = math.degrees(math.atan(d_mm / 150.0))
        if ang < 3:
            eff = '强亮瞳'
        elif ang < 6:
            eff = '亮瞳可见'
        elif ang < 12:
            eff = '亮瞳弱，多为暗瞳'
        else:
            eff = '暗瞳（看不到亮瞳）'
        print('  %-18s %-20s %s' % ('%dmm' % d_mm, '%.1f 度' % ang, eff))
    print()
    print('  结论：要稳定亮瞳，LED 离镜头应在 10mm 以内（离轴角 < 4 度）。')
    print('        这决定了 LED 必须【紧贴镜头】安装，而不是分开摆。')

    print()
    print('=' * 84)
    print('四、角膜反光点（glint）会不会跑出眼睛区域')
    print('=' * 84)
    print('  glint 是 LED 在角膜表面的镜面反射。它离瞳孔的距离决定了')
    print('  "瞳孔-反光点向量"这个核心测量量是否可用。')
    print()
    print('  %-16s %-22s %-22s %s' % ('LED 离轴', 'glint 相对瞳孔偏移mm', '占眼睛宽度', '可用性'))
    print('  ' + '-' * 74)
    for d_mm in (5, 10, 20, 40):
        # 角膜曲率半径约 7.8mm，镜面反射使 glint 偏移约为离轴距离的一半
        glint_off = d_mm * 0.5 * (DIST_CORNEA_TO_CENTRE_MM / 150.0 * 0 + 1) * 0.5
        glint_off = d_mm * 0.25      # 经验值：约为离轴距离的 1/4
        frac = glint_off / EYE_WIDTH_MM
        ok = '好（glint 与瞳孔都在眼内）' if glint_off < 8 else '风险（glint 可能出眼）'
        print('  %-16s %-22.1f %-22s %s'
              % ('%dmm' % d_mm, glint_off, '%.0f%%' % (frac * 100), ok))
    print()
    print('  结论：LED 离轴 10~20mm 时，glint 与瞳孔都在眼内，')
    print('        既能亮瞳、又能同时测到瞳孔与反光点 —— 这是最佳区间。')
    print('        与第三节的"<10mm 才强亮瞳"叠加，目标布置是 10~15mm。')

    print()
    print('=' * 84)
    print('五、推荐的硬件组合（按可行性排序）')
    print('=' * 84)
    print('  方案 1：树莓派 IR 摄像头模组（最省事）')
    print('    · 元件：树莓派 Camera Module 3 NoIR（或 OV5647 NoIR）+ USB 转接板')
    print('            + 5V 红外 LED 若干（850nm）+ 电阻 + 可调支架')
    print('    · 优点：模组自带"无红外滤片"版本，省去拆滤片这一步（拆滤片容易报废）')
    print('    · 造价：约 80~150 元')
    print('    · 关键参数：选 1080p 版本、焦距 3.6mm（视场约 60 度）')
    print()
    print('  方案 2：USB 红外摄像头（更省事但不可控）')
    print('    · 元件：成品"红外夜视 USB 摄像头"（自带 850nm LED）+ 近眼支架')
    print('    · 优点：开箱即用')
    print('    · 缺点：LED 通常离镜头较远（为了照远处），亮瞳效果可能不稳；')
    print('            分辨率与焦距不可选')
    print('    · 造价：约 50~100 元')
    print()
    print('  方案 3：手机 + 红外滤片（最低成本）')
    print('    · 元件：旧手机 + 850nm 滤片（或曝光过度的胶片）')
    print('    · 优点：手机自带高分辨率与好镜头，可能直接拿到 400+ 像素的眼睛')
    print('    · 缺点：需要小孔或支架把手机固定在眼前 10~15cm，佩戴不便；')
    print('            多数手机有强红外截止滤片，滤片叠加后曝光会非常暗')
    print('    · 造价：约 10~30 元（滤片）')
    print()
    print('  我的建议：先试【方案 3】验证"眼睛能不能占够像素"这一件事（成本最低、')
    print('  当天可做）；确认几何可行后再买方案 1 的元件做正式版。')
    print('  理由：方案 3 只需一块滤片，就能回答最关键的问题 ——')
    print('  眼睛在近距高分辨率下到底有多少可用像素。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
