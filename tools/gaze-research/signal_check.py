#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
signal_check.py — 量化"眼部图像里到底有没有注视信息"

肉眼看网格图容易受对比度和低分辨率误导，所以直接算：
  1. 按目标位置分组，算每组的平均图像，再看组间差分的能量
  2. 关键对比：最上一行 vs 最下一行（垂直注视差 ~800px）
              最左一列 vs 最右一列（水平注视差 ~1450px）
  3. 与"同一位置不同帧"的噪声底比较 —— 这是决定性判据：
     若组间差异 <= 帧间噪声，说明图像里没有可用的注视信号

用法： python tools/signal_check.py data/eyes_p029379
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


def load_group_means(index, data_dir, key_fn, min_n=20):
    from PIL import Image
    groups = {}
    for r in index:
        groups.setdefault(key_fn(r), []).append(r['name'])
    means, ns = {}, {}
    for k, names in groups.items():
        if len(names) < min_n:
            continue
        acc = None
        for nm in names:
            p = os.path.join(data_dir, nm)
            if not os.path.exists(p):
                continue
            a = np.asarray(Image.open(p).convert('L'), dtype=np.float32) / 255.0
            acc = a if acc is None else acc + a
        if acc is None:
            continue
        means[k] = acc / len(names)
        ns[k] = len(names)
    return means, ns, groups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('data_dir')
    ap.add_argument('--q', type=float, default=80.0, help='目标位置离散粒度(px)')
    args = ap.parse_args()

    mf = os.path.join(args.data_dir, 'manifest.json')
    with open(mf, encoding='utf-8') as f:
        man = json.load(f)
    index = man['index']
    print('条目:', len(index), ' 目录:', args.data_dir)

    import numpy as np
    tx = np.array([r['tx'] for r in index])
    ty = np.array([r['ty'] for r in index])
    kx = np.round(tx / args.q).astype(int)
    ky = np.round(ty / args.q).astype(int)

    # 用粗粒度网格做分组（每格对应一个真实目标点）
    means, ns, groups = load_group_means(index, args.data_dir, lambda r: (round(r['tx'] / args.q), round(r['ty'] / args.q)))
    keys = sorted(means.keys(), key=lambda k: (k[1], k[0]))
    print('有效目标位置数:', len(keys), ' 每格帧数中位:', int(np.median(list(ns.values()))))

    H, W = next(iter(means.values())).shape
    # 左眼 / 右眼分别看（各 72 宽）
    for tag, sl in [('左眼', slice(0, W // 2)), ('右眼', slice(W // 2, W))]:
        sub = {k: v[:, sl] for k, v in means.items()}

        # 组间差异：所有成对差分
        inter = []
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                if keys[j][1] == keys[i][1] and keys[j][0] == keys[i][0]:
                    continue
                d = sub[keys[i]] - sub[keys[j]]
                inter.append(np.sqrt((d ** 2).mean()))
        inter = np.array(inter)

        # 组内噪声底：把每格的帧随机分两半，两半均值之差
        rng = np.random.default_rng(0)
        intra = []
        for k, names in groups.items():
            kk = (round(names[0] and 0), 0)
        # 重新按 keys 组织
        intra = []
        for k in keys:
            names = groups[k]
            if len(names) < 8:
                continue
            perm = rng.permutation(len(names))
            h1 = names[: len(names) // 2]
            h2 = names[len(names) // 2:]
            from PIL import Image
            acc1 = acc2 = None
            for nm in h1:
                p = os.path.join(args.data_dir, nm)
                a = np.asarray(Image.open(p).convert('L'), dtype=np.float32) / 255.0
                acc1 = a if acc1 is None else acc1 + a
            for nm in h2:
                p = os.path.join(args.data_dir, nm)
                a = np.asarray(Image.open(p).convert('L'), dtype=np.float32) / 255.0
                acc2 = a if acc2 is None else acc2 + a
            d = acc1 / len(h1) - acc2 / len(h2)
            intra.append(np.sqrt((d ** 2).mean()))
        intra = np.array(intra)

        print('\n=== %s (%dx%d) ===' % (tag, sub[keys[0]].shape[1], H))
        print('  组间差异（不同注视位置）平均 RMS = %.5f   最大 = %.5f' % (inter.mean(), inter.max()))
        print('  组内噪声（同一位置两半之差）平均 RMS = %.5f   最大 = %.5f' % (intra.mean(), intra.max()))
        print('  信噪比 = 组间/组内 = %.2f' % (inter.mean() / max(intra.mean(), 1e-9)))

        # 极值对比：最上 vs 最下，最左 vs 最右
        ys = sorted(set(k[1] for k in keys))
        xs = sorted(set(k[0] for k in keys))
        top = [k for k in keys if k[1] == ys[0]]
        bot = [k for k in keys if k[1] == ys[-1]]
        lef = [k for k in keys if k[0] == xs[0]]
        rig = [k for k in keys if k[0] == xs[-1]]

        def pair_rms(A, B):
            if not A or not B:
                return None
            a = np.mean([sub[k] for k in A], axis=0)
            b = np.mean([sub[k] for k in B], axis=0)
            return float(np.sqrt(((a - b) ** 2).mean()))

        vt = pair_rms(top, bot)
        hz = pair_rms(lef, rig)
        print('  垂直极值对比（最上排 vs 最下排）RMS = %s' % ('%.5f' % vt if vt else 'n/a'))
        print('  水平极值对比（最左列 vs 最右列）RMS = %s' % ('%.5f' % hz if hz else 'n/a'))
        print('  判据：极值对比应明显大于组内噪声（%.5f），否则图像里没有可用信号' % intra.mean())

        # 保存差异图，供肉眼看"差异集中在哪"
        try:
            os.makedirs(os.environ['MPLCONFIGDIR'], exist_ok=True)
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            fig, axes = plt.subplots(1, 4, figsize=(13, 3.4))
            axes[0].imshow(sub[keys[0]], cmap='gray'); axes[0].set_title('sample mean')
            if vt:
                a = np.mean([sub[k] for k in top], axis=0)
                b = np.mean([sub[k] for k in bot], axis=0)
                axes[1].imshow(a - b, cmap='coolwarm'); axes[1].set_title('top - bottom (vert gaze)')
            if hz:
                a = np.mean([sub[k] for k in lef], axis=0)
                b = np.mean([sub[k] for k in rig], axis=0)
                axes[2].imshow(a - b, cmap='coolwarm'); axes[2].set_title('left - right (horiz gaze)')
            # 组内噪声图
            axes[3].imshow(np.abs(np.random.default_rng(0).normal(0, intra.mean(), sub[keys[0]].shape)), cmap='coolwarm')
            axes[3].set_title('noise floor scale')
            for a in axes:
                a.set_xticks([]); a.set_yticks([])
            out = os.path.join(os.path.dirname(os.path.abspath(args.data_dir)),
                               'signal_check_%s.png' % tag)
            fig.tight_layout(); fig.savefig(out, dpi=150)
            print('  差异图已保存:', out)
        except Exception as e:
            print('  画图失败:', e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
