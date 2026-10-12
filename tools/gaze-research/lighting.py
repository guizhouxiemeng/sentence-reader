#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
lighting.py — 从眼部图像里客观测量光照条件

为什么要测：|r| 在会话间从 0.558 波动到 0.845，而 iod 和头位漂移都被证伪，
光照是唯一剩下的、有生理依据、且完全没控制过的因素。
这份数据里其实就藏着光照信息 —— 眼部图像的像素亮度。

输出：
  · 平均亮度、暗部比例（曝光不足的证据）
  · 亮度直方图（是否集中在暗端）
  · 虹膜区域的局部对比度（决定性指标：对比度低则虹膜边界检测不准）
  · 帧间亮度方差（自动曝光在抖动也是噪声源）

用法： python tools/lighting.py samples_dir_or_zip
      python tools/lighting.py data/eyes_p029379
"""
import argparse
import json
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_dir', help='unzip-eyes.js 解出的目录')
    ap.add_argument('--sample', type=int, default=400, help='抽样帧数')
    args = ap.parse_args()

    mf = os.path.join(args.data_dir, 'manifest.json')
    if not os.path.exists(mf):
        print('找不到 manifest.json:', mf)
        return 1
    with open(mf, encoding='utf-8') as f:
        man = json.load(f)
    index = man['index']

    try:
        from PIL import Image
    except ImportError:
        print('需要 Pillow')
        return 1

    rng = np.random.default_rng(0)
    sel = rng.choice(len(index), size=min(args.sample, len(index)), replace=False)

    lums, contrasts, dark_fracs, hi_fracs = [], [], [], []
    H = W = None
    for i in sel:
        p = os.path.join(args.data_dir, index[i]['name'])
        if not os.path.exists(p):
            continue
        g = np.asarray(Image.open(p).convert('L'), dtype=np.float32) / 255.0
        H, W = g.shape
        lums.append(float(g.mean()))
        dark_fracs.append(float((g < 0.15).mean()))
        hi_fracs.append(float((g > 0.9).mean()))

        # 虹膜对比度：取图片中心区域（左眼|右眼并排的各自中心），
        # 用局部标准差衡量"瞳孔 vs 巩膜"的可分辨程度
        h, w = g.shape
        cx = [
            g[h // 4: 3 * h // 4, w // 8: 3 * w // 8],          # 左眼中心
            g[h // 4: 3 * h // 4, 5 * w // 8: 7 * w // 8],      # 右眼中心
        ]
        contrasts.append(float(np.mean([c.std() for c in cx])))

    lums = np.array(lums); contrasts = np.array(contrasts)
    dark_fracs = np.array(dark_fracs); hi_fracs = np.array(hi_fracs)

    print('=' * 76)
    print('光照条件客观测量  目录:', args.data_dir)
    print('样本帧数: %d   图像尺寸: %dx%d' % (len(lums), W, H))
    print('-' * 76)
    print('  平均亮度            : %.3f   (0=全黑 1=全白)' % lums.mean())
    print('  亮度中位/标准差     : %.3f / %.4f' % (np.median(lums), lums.std()))
    print('  极暗帧比例 (<0.15)  : %.1f%%' % (100 * dark_fracs.mean()))
    print('  过曝比例 (>0.90)    : %.2f%%' % (100 * hi_fracs.mean()))
    print('  虹膜区局部对比度    : %.4f  (越高越容易分辨瞳孔/虹膜边界)' % contrasts.mean())
    print('  帧间亮度波动(std)   : %.4f  (大说明自动曝光在抖动)' % lums.std())

    # 判定
    print('-' * 76)
    print('判定：')
    issues = []
    if lums.mean() < 0.25:
        issues.append('整体偏暗（平均亮度 %.2f < 0.25）→ 关键点检测信噪比低' % lums.mean())
    if dark_fracs.mean() > 0.25:
        issues.append('超过 25%% 的像素处于极暗区 → 眼部细节被噪声淹没')
    if contrasts.mean() < 0.10:
        issues.append('虹膜区对比度低（%.3f < 0.10）→ 瞳孔边界难以稳定定位' % contrasts.mean())
    if lums.std() > 0.04:
        issues.append('帧间亮度波动大（%.3f）→ 自动曝光在跟随画面变化，会引入与注视无关的漂移' % lums.std())
    if not issues:
        print('  ✓ 未发现明显光照问题')
    else:
        for s in issues:
            print('  ✗ ' + s)

    print('\n可操作的改善（零成本，按性价比排序）：')
    print('  1. 关掉背后的窗户/窗帘 —— 背光是虹膜检测的头号杀手，会让眼睛变成剪影')
    print('  2. 在显示器前方偏上位置放一盏台灯，照亮脸而不是照屏幕（避免屏幕反光）')
    print('  3. 把显示器亮度略微调高，屏幕本身是很有效的面光源')
    print('  4. 避免头顶直射的顶灯 —— 会在眼窝留下阴影，同时减轻眼镜反光')
    print('  5. 关掉摄像头可能开启的自动曝光（部分驱动支持），消除帧间亮度漂移')

    # 直方图
    try:
        cache = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.mplcache')
        os.makedirs(cache, exist_ok=True)
        os.environ.setdefault('MPLCONFIGDIR', cache)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        # 中文字体：找不到就退回英文标签，避免一堆 glyph missing 警告
        zh = None
        for cand in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC']:
            try:
                font_manager.findfont(font_manager.FontProperties(family=cand), fallback_to_default=False)
                zh = cand
                break
            except Exception:
                continue
        if zh:
            plt.rcParams['font.sans-serif'] = [zh]
        plt.rcParams['axes.unicode_minus'] = False
        L = (lambda z: z) if zh else (lambda z: z)
        warn_low = '过暗警戒线 0.25' if zh else 'too-dark threshold 0.25'
        warn_ct = '对比度警戒线 0.10' if zh else 'contrast threshold 0.10'
        fig, ax = plt.subplots(1, 2, figsize=(11, 3.6))
        ax[0].hist(lums, bins=40, color='#4c8dff')
        ax[0].axvline(0.25, color='#ff6b6b', ls='--', label=warn_low)
        ax[0].set_title('per-frame mean luminance')
        ax[0].set_xlabel('luminance'); ax[0].legend(); ax[0].grid(alpha=.25)
        ax[1].hist(contrasts, bins=40, color='#ff9f43')
        ax[1].axvline(0.10, color='#ff6b6b', ls='--', label=warn_ct)
        ax[1].set_title('iris-region local contrast')
        ax[1].set_xlabel('contrast'); ax[1].legend(); ax[1].grid(alpha=.25)
        out = os.path.join(os.path.dirname(os.path.abspath(args.data_dir)), 'lighting.png')
        fig.tight_layout(); fig.savefig(out, dpi=140)
        print('\n直方图已保存:', out)
    except Exception as e:
        print('\n画图失败:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
