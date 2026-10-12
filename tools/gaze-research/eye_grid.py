#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
eye_grid.py — 把眼部图像按目标位置排成 4x3 网格，肉眼判断 appearance 模型是否有戏

这是投入 CNN 之前的最后一次廉价验证：
  · 若同一列的各格瞳孔位置明显不同 → 图像里确实带着注视信息
  · 若看起来几乎一样 → 分辨率/清晰度不够，应该先改采集而不是训模型

用法：
  python tools/eye_grid.py data/eyes_p029379
  python tools/eye_grid.py data/eyes_p029379 --out my_grid.png --per-cell 3
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

os.environ.setdefault('MPLCONFIGDIR', os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.mplcache'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_dir', help='unzip-eyes.js 解出的目录（含 manifest.json 和 eyes/）')
    ap.add_argument('--out', default=None)
    ap.add_argument('--per-cell', type=int, default=3, help='每个目标位置叠放几张')
    ap.add_argument('--quant', type=float, default=25.0, help='目标位置离散化粒度(px)')
    args = ap.parse_args()

    mf = os.path.join(args.data_dir, 'manifest.json')
    if not os.path.exists(mf):
        print('找不到 manifest.json:', mf)
        return 1
    with open(mf, encoding='utf-8') as f:
        man = json.load(f)
    index = man.get('index', [])
    print('manifest 条目:', len(index))

    try:
        from PIL import Image
    except ImportError:
        print('需要 Pillow: python -m pip install pillow -i https://pypi.tuna.tsinghua.edu.cn/simple')
        return 1

    tx = np.array([r['tx'] for r in index])
    ty = np.array([r['ty'] for r in index])
    # 离散化成 4x3 网格索引
    q = args.quant
    kx = np.round(tx / q).astype(int)
    ky = np.round(ty / q).astype(int)
    ux = np.unique(kx)
    uy = np.unique(ky)
    print('离散后列数:', len(ux), ' 行数:', len(uy))

    # 先加载一张确定图像尺寸
    def load(rel):
        p = os.path.join(args.data_dir, rel)
        if not os.path.exists(p):
            return None
        return np.asarray(Image.open(p).convert('RGB'), dtype=np.float32) / 255.0

    valid = None
    for r in index:
        a = load(r['name'])
        if a is not None:
            valid = a
            break
    if valid is None:
        print('一张图都加载不到，检查 manifest 里的 name 与磁盘是否对应')
        return 1
    H, W, _ = valid.shape
    print('单张图像尺寸: %dx%d (左眼|右眼并排)' % (W, H))

    C = args.per_cell
    pad = 4
    cellH = C * H + (C - 1) * pad
    canvas = np.ones((len(uy) * (cellH + 26) + 26, len(ux) * (W + 10) + 10, 3), dtype=np.float32)

    rng = np.random.default_rng(0)
    counts = np.zeros((len(uy), len(ux)), dtype=int)
    for i, yy in enumerate(uy):
        for j, xx in enumerate(ux):
            m = np.where((ky == yy) & (kx == xx))[0]
            if len(m) == 0:
                continue
            # 取该格中间的若干帧（避开点刚出现/即将结束的不稳定期）
            m = m[np.argsort([index[t]['t'] for t in m])]
            sel = m[len(m) // 2 - C // 2: len(m) // 2 - C // 2 + C]
            counts[i, j] = len(m)
            for c, t in enumerate(sel):
                img = load(index[t]['name'])
                if img is None:
                    continue
                y0 = 26 + i * (cellH + 26) + c * (H + pad)
                x0 = 10 + j * (W + 10)
                canvas[y0:y0 + H, x0:x0 + W] = img

    # 网格线与行列标注
    try:
        os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib import font_manager

        # 找一个能显示中文的字体，找不到就退回英文标签
        zh = None
        for cand in ['Microsoft YaHei', 'SimHei', 'Noto Sans CJK SC', 'Source Han Sans SC']:
            try:
                font_manager.findfont(font_manager.FontProperties(family=cand), fallback_to_default=False)
                zh = cand
                break
            except Exception:
                continue
        if zh:
            plt.rcParams['font.sans-serif'] = [zh]
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(figsize=(len(ux) * 2.4, len(uy) * 2.9))
        ax.imshow(np.clip(canvas, 0, 1))
        ax.set_xticks([10 + j * (W + 10) + W / 2 for j in range(len(ux))])
        ax.set_xticklabels(['target_x≈%.0f' % (xx * q) for xx in ux], fontsize=9)
        ax.set_yticks([26 + i * (cellH + 26) + cellH / 2 for i in range(len(uy))])
        ax.set_yticklabels(['target_y≈%.0f' % (yy * q) for yy in uy], fontsize=9)
        ax.set_xlabel('每一列 = 同一个水平注视位置，上下叠放 %d 帧' % C)
        title = '眼部图像按目标位置排布 — 看瞳孔位置是否随格子移动'
        ax.set_title(title, fontsize=12)
        for j in range(1, len(ux)):
            ax.axvline(10 + j * (W + 10) - 5, color='#4c8dff', lw=1.2, alpha=.7)
        for i in range(1, len(uy)):
            ax.axhline(26 + i * (cellH + 26) - 13, color='#4c8dff', lw=1.2, alpha=.7)
        for i in range(len(uy)):
            for j in range(len(ux)):
                ax.text(10 + j * (W + 10) + W - 4, 26 + i * (cellH + 26) - 4,
                        'n=%d' % counts[i, j], fontsize=7, ha='right', color='#666')
        fig.tight_layout()
        out = args.out or os.path.join(os.path.dirname(os.path.abspath(args.data_dir)), 'eye_grid.png')
        fig.savefig(out, dpi=140)
        print('图已保存:', out)
    except Exception as e:
        print('画图失败:', e)
        # 退化方案：存原始拼图
        out = args.out or 'eye_grid_raw.png'
        Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8)).save(out)
        print('已保存无标注拼图:', out)

    print('\n观察要点：')
    print('  1. 横向：从左到右，瞳孔在眼裂里的位置是否单调移动？')
    print('  2. 纵向：从上到下，瞳孔是否下移（上排看上方 → 瞳孔偏上）？')
    print('  3. 若几乎看不出差别，说明 72x72 的分辨率不足以承载注视信息，')
    print('     应提高采集分辨率（改 CROP.w）或让脸离摄像头更近，而不是继续训模型。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
