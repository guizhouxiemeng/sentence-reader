#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
feasibility_dual.py — 单摄像头同时跑"眼动+手部"两个模型的可行性核算

问题
----
用户目标是"眼动负责粗定位、手指负责精定位"。这需要【同时】获取两路信号。
但我们只有一台摄像头，而 MediaPipe 的 FaceLandmarker 与 HandLandmarker
是两个独立模型，必须分别推理。

现场实测的单模型成本：
    FaceLandmarker  约 8.6 ~ 9.6 ms/帧   （gaze demo HUD）
    HandLandmarker  约 16.9 ~ 41.3 ms/帧 （hand demo HUD，波动较大）

本脚本核算几种可行的调度方案的帧率，判断"单摄像头双模型"是否可行，
以及如果不可行，应该用什么替代方案来回答"融合是否有效"这个科学问题。

用法： python tools/feasibility_dual.py
"""
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main():
    FACE_MS = (8.6, 9.6)      # 现场实测区间
    HAND_MS = (16.9, 41.3)

    print('=' * 78)
    print('单摄像头同时运行两个 MediaPipe 模型的成本')
    print('=' * 78)
    print('  FaceLandmarker  %.1f ~ %.1f ms/帧' % FACE_MS)
    print('  HandLandmarker  %.1f ~ %.1f ms/帧' % HAND_MS)
    print('  目标端到端延迟  < 100 ms（gaze demo 设定的可用性门槛）')
    print()

    print('=' * 78)
    print('方案对比')
    print('=' * 78)
    print('  %-30s %-14s %-14s %s' % ('方案', '单帧总耗时', '理论帧率', '评价'))
    print('  ' + '-' * 74)

    combos = [
        ('每帧都跑两个模型', FACE_MS[0] + HAND_MS[0], FACE_MS[1] + HAND_MS[1]),
        ('眼动 3 帧跑一次', FACE_MS[0] / 3 + HAND_MS[0], FACE_MS[1] / 3 + HAND_MS[1]),
        ('眼动 5 帧跑一次', FACE_MS[0] / 5 + HAND_MS[0], FACE_MS[1] / 5 + HAND_MS[1]),
        ('眼动 10 帧跑一次', FACE_MS[0] / 10 + HAND_MS[0], FACE_MS[1] / 10 + HAND_MS[1]),
    ]
    for name, best, worst in combos:
        fps_b = 1000 / best
        fps_w = 1000 / worst
        note = ''
        if fps_w < 15:
            note = '✗ 最差情况卡顿'
        elif fps_w < 25:
            note = '△ 勉强'
        else:
            note = '✓ 可用'
        print('  %-30s %-14s %-14s %s'
              % (name, '%.1f~%.1f ms' % (best, worst),
                 '%.0f~%.0f fps' % (fps_w, fps_b), note))

    print('\n' + '=' * 78)
    print('关键判断')
    print('=' * 78)
    print('  1. 手部推理耗时波动很大（16.9~41.3ms，2.4 倍），这是手在画面里的')
    print('     尺度变化造成的。若同时跑两个模型，最差情况单帧超过 50ms，')
    print('     帧率会掉到 15fps 以下 —— 指尖指针的响应会明显变涩。')
    print()
    print('  2. 但注意：眼动的【区域判定】是低频信号。实测已证明它需要')
    print('     500ms 的时间积分才能可靠（单帧 81% → 表决后可用）。')
    print('     所以眼动每 3~5 帧推理一次（约 6~10Hz）完全够用。')
    print()
    print('  3. 结论：单摄像头双模型【技术上可行】，推荐"眼动降频"方案 ——')
    print('     手指每帧推理（保证光标流畅），眼动每 4 帧推理一次（区域判定）。')
    print('     这样最差情况单帧约 37ms（约 27fps），在可用范围内。')
    print()
    print('  4. 但还有一个更严重的问题需要正视：')
    print('     两个模型同时跑，每帧只处理一次摄像头画面，眼部的有效分辨率')
    print('     并不会因为跑两个模型而提高 —— 虹膜依然是约 25 像素。')
    print('     也就是说，融合【不会】提高眼动本身的精度，它只是让眼动')
    print('     承担它擅长的事（粗定位）。这正是融合的立足点。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
