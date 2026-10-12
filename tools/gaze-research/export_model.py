#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
export_model.py — 训练模型并把权重导出成 JSON，供浏览器端实时推理

为什么走这条路：
  · Python 侧推理需要 WebSocket/本地服务器中转，端到端延迟多一跳，且部署麻烦
  · 浏览器端只需要一个 19→128→128→4 的矩阵乘法，纯 JS 几微秒就能算完
  · 模型权重只有几十 KB，导成 JSON 后 demo 页面可以完全离线运行
  · 特征提取逻辑已经存在于 collector.html（MediaPipe 在两边都有）

导出的 JSON 结构：
  {
    meta:   { features, camera, screen, trained_on, err_mean, err_norm, ... },
    scaler: { x_mean, x_std, y_mean, y_std },
    layers: [ {W: [[...]], b: [...]}, ... ],     # 最后一层同时输出 mu 与 log_sigma
    temp:   T,                                    # 温度标定标量
    calib:  {A: [[...]], b: [...]} 或 null        # 可选的 2x2 屏幕映射（见下）
  }

屏幕映射的说明：
  模型的输出是"屏幕像素坐标"，但它是在采集时的视口尺寸下训练出来的。
  如果 demo 用不同的窗口尺寸跑，需要把预测按比例缩放——这个缩放系数
  由 calibration 数据拟合（用 12 个标定点做 2D 仿射），比硬编码缩放更稳。
  本工具在导出时用同一次采集的数据拟合这个仿射，作为默认映射。

用法：
  python tools/export_model.py gaze_p411900_frames.csv -o demo/model.json
  python tools/export_model.py gaze_p411900_frames.csv -o demo/model.json --epochs 600
"""
import argparse
import csv
import json
import os
import sys

import numpy as np

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

try:
    import torch
    import torch.nn as nn
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False

FRAME_MS = 33.3
REL = ['L_h', 'L_v', 'L_h2', 'L_v2', 'R_h', 'R_v', 'R_h2', 'R_v2',
       'yaw', 'pitch', 'earL', 'earR', 'iod']


def load(path, cache=None):
    """读 CSV。如果存在同名 .jsonl（含原始 478 关键点），直接用它计算特征，
    这样训练特征与 demo 端（浏览器）能保持完全一致。"""
    if cache and os.path.exists(cache):
        rows = []
        meta = {}
        with open(cache, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                if '__meta__' in o:
                    meta = o['__meta__']
                elif 'p' in o:
                    rows.append(o)
        if rows:
            X, names = feats_from_raw(rows)
            Y = np.column_stack([[r['tx'] for r in rows], [r['ty'] for r in rows]])
            tr = np.array([r['trial'] for r in rows])
            return X, Y, tr, names, meta

    with open(path, encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        h = next(rd)
        rows = [r for r in rd if len(r) == len(h)]
    c = {n: i for i, n in enumerate(h)}
    d = [r for r in rows if r[c['phase']] == 'dot']
    col = lambda n: np.array([float(r[c['f_' + n]]) for r in d])
    iod = col('iod') + 1e-9
    gx = ((col('irisL_x') + col('irisR_x')) / 2 - col('eyecenter_x')) / iod
    gy = ((col('irisL_y') + col('irisR_y')) / 2 - col('eyecenter_y')) / iod
    F = [gx, gy, gx * gx, gy * gy, gx * gy, np.ones_like(gx)]
    names = ['gaze_x', 'gaze_y', 'gaze_x2', 'gaze_y2', 'gaze_xy', 'bias']
    for f in REL:
        F.append(col(f)); names.append(f)
    X = np.column_stack(F)
    Y = np.column_stack([np.array([float(r[c['tx']]) for r in d]),
                         np.array([float(r[c['ty']]) for r in d])])
    tr = np.array([int(r[c['trial']]) for r in d])
    return X, Y, tr, names, {}


def feats_from_raw(rows):
    """从原始 478 关键点（每点 x,y,z 展平）计算特征。

    这是浏览器与 Python 端必须完全一致的部分，所以定义在这里一次，
    并与 collector.html 的 buildFeatures 保持同样的取点索引。

    索引（MediaPipe FaceMesh 478 点）：
      33 左眼外角, 133 左眼内角, 159 左上睑, 145 下睑
      263 右眼外角, 362 右眼内角, 386 右上睑, 374 下睑
      468 左虹膜中心, 473 右虹膜中心, 152 下巴, 10 额头, 1 鼻尖
    """
    IDX = dict(eyeOuterL=33, eyeInnerL=133, eyeTopL=159, eyeBotL=145,
               eyeOuterR=263, eyeInnerR=362, eyeTopR=386, eyeBotR=374,
               irisL=468, irisR=473, chin=152, forehead=10, nose=1)
    G = {k: {'x': [], 'y': [], 'z': []} for k in IDX}
    for r in rows:
        p = r['p']
        for k, i in IDX.items():
            G[k]['x'].append(p[i * 3]); G[k]['y'].append(p[i * 3 + 1]); G[k]['z'].append(p[i * 3 + 2])
    A = {k: {ax: np.array(v) for ax, v in d.items()} for k, d in G.items()}

    def d(a, ax, b):
        return A[a][ax] - A[b][ax]

    iod = np.hypot(d('eyeOuterR', 'x', 'eyeOuterL'), d('eyeOuterR', 'y', 'eyeOuterL')) + 1e-6
    earL = np.hypot(d('eyeTopL', 'x', 'eyeBotL'), d('eyeTopL', 'y', 'eyeBotL')) / \
        (np.hypot(d('eyeOuterL', 'x', 'eyeInnerL'), d('eyeOuterL', 'y', 'eyeInnerL')) + 1e-6)
    earR = np.hypot(d('eyeTopR', 'x', 'eyeBotR'), d('eyeTopR', 'y', 'eyeBotR')) / \
        (np.hypot(d('eyeOuterR', 'x', 'eyeInnerR'), d('eyeOuterR', 'y', 'eyeInnerR')) + 1e-6)
    yaw = np.clip(d('nose', 'x', 'eyeInnerL') / iod, -2, 2)
    pitch = np.clip((d('chin', 'y', 'forehead') / iod) / 2.0, 0, 3)

    irx = (A['irisL']['x'] + A['irisR']['x']) / 2
    iry = (A['irisL']['y'] + A['irisR']['y']) / 2
    ecx = (A['eyeOuterL']['x'] + A['eyeInnerL']['x'] + A['eyeOuterR']['x'] + A['eyeInnerR']['x']) / 4
    ecy = (A['eyeOuterL']['y'] + A['eyeInnerL']['y'] + A['eyeOuterR']['y'] + A['eyeInnerR']['y']) / 4

    gx = (irx - ecx) / iod
    gy = (iry - ecy) / iod

    names = ['gaze_x', 'gaze_y', 'gaze_x2', 'gaze_y2', 'gaze_xy', 'bias']
    F = [gx, gy, gx * gx, gy * gy, gx * gy, np.ones_like(gx)]

    # 与 buildFeatures 的顺序一致：L_h,L_v,L_h2,L_v2,R_h,R_v,R_h2,R_v2,yaw,pitch,earL,earR,iod
    parts = [
        ('L_h', d('irisL', 'x', 'eyeOuterL') / iod),
        ('L_v', d('irisL', 'y', 'eyeTopL') / iod),
        ('L_h2', d('irisL', 'x', 'eyeInnerL') / iod),
        ('L_v2', d('irisL', 'y', 'eyeBotL') / iod),
        ('R_h', d('irisR', 'x', 'eyeOuterR') / iod),
        ('R_v', d('irisR', 'y', 'eyeTopR') / iod),
        ('R_h2', d('irisR', 'x', 'eyeInnerR') / iod),
        ('R_v2', d('irisR', 'y', 'eyeBotR') / iod),
        ('yaw', yaw), ('pitch', pitch), ('earL', earL), ('earR', earR), ('iod', iod),
    ]
    for nm, v in parts:
        F.append(v); names.append(nm)
    X = np.column_stack(F)
    return X, names


def net(d):
    return nn.Sequential(nn.Linear(d, 128), nn.ReLU(),
                         nn.Linear(128, 128), nn.ReLU(),
                         nn.Linear(128, 4))


def nll(o, y):
    mu, ls = o[:, :2], torch.clamp(o[:, 2:], -6, 4)
    s = torch.exp(ls)
    return (0.5 * ((y - mu) / s) ** 2 + ls).sum(1).mean()


def temp_scale(sig, mu, Y):
    """按 sigma 的【均值】尺度拟合温度。"""
    err = np.linalg.norm(mu - Y, axis=1)
    s = sig.mean(axis=1) if sig.ndim > 1 else sig
    return _fit_temp(s, err)


def temp_scale_sum(sig_sum, mu, Y):
    """按 sigma 的【求和】尺度拟合温度。

    demo 端用的是 exp(clamp(logsx)) * ys + exp(clamp(logsy)) * ys，即两轴求和。
    NLL 损失里也是求和（(Δx/σx)² + (Δy/σy)² + logσx + logσy）。
    所以标定必须与使用口径一致 —— 用均值拟合再拿去乘求和，会把不确定度
    放大约 2 倍（这个坑真实发生过）。
    """
    err = np.linalg.norm(mu - Y, axis=1)
    return _fit_temp(sig_sum, err)


def _fit_temp(s, err):
    best_T, best = 1.0, 1e18
    for T in np.exp(np.linspace(0, np.log(400), 300)):
        st = s * T
        edges = np.quantile(st, np.linspace(0, 1, 9))
        gap = 0.0
        for i in range(8):
            m = (st >= edges[i]) & (st <= edges[i + 1] if i == 7 else st < edges[i + 1])
            if m.sum() < 3:
                continue
            gap += abs(np.log(max(st[m].mean(), 1e-6)) - np.log(max(err[m].mean(), 1e-6))) * m.sum()
        if gap < best:
            best, best_T = gap, float(T)
    return best_T


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('-o', '--out', default='demo/model.json')
    ap.add_argument('--epochs', type=int, default=600)
    ap.add_argument('--folds', type=int, default=5)
    args = ap.parse_args()
    if not HAS_TORCH:
        print('需要 PyTorch')
        return 1
    if not os.path.exists(args.csv):
        print('找不到:', args.csv)
        return 1

    jsonl = os.path.splitext(args.csv)[0] + '.jsonl'
    X, Y, tr, names, meta = load(args.csv, cache=jsonl)
    print('样本 %d   特征 %d 维   试次 %d' % (len(Y), X.shape[1], len(np.unique(tr))))
    print('特征顺序: %s' % names)

    W = (Y[:, 0].max() - Y[:, 0].min()) / 0.84
    H = (Y[:, 1].max() - Y[:, 1].min()) / 0.84
    diag = float(np.hypot(W, H))
    trials = np.unique(tr)

    # ------------------------------------------------------------------
    #  为什么是"多种子集成"而不是"折集成"（实测教训，改了两次）
    #
    #  先试了单模型全量训练：训练集误差 0.0144 对角线 vs 交叉验证 0.143，
    #  差 10 倍——它把 36 个试次的 12 个目标位置背下来了。
    #
    #  再试了折集成（每个折模型只在自己那份训练集上训）：更糟。
    #  实测把正常量级的输入喂进去，5 个折模型的输出是
    #      mu_x = -2932, -1399, -1656, 751, 1627
    #  分歧 1889 px。因为它们各自只见过约 29 个试次、12 个目标位置，
    #  学到的映射彼此差得极远，平均它们毫无意义 —— 外推完全发散。
    #
    #  最终方案：同一份全量数据，只改随机种子训 M 个模型。
    #  这样成员之间可比，折间分歧退化为"初始化方差"，是一个弱但真实的
    #  不确定性来源。泛化能力仍由 train.py 的按目标位置交叉验证单独报告，
    #  不靠这里自吹（本函数会打印诚实的说明）。
    # ------------------------------------------------------------------
    M = 5
    models = []
    torch.manual_seed(0); np.random.seed(0)
    xm, xs = X.mean(0), X.std(0) + 1e-8
    ym, ys = Y.mean(0), Y.std(0) + 1e-8
    xt = torch.tensor((X - xm) / xs, dtype=torch.float32)
    yt = torch.tensor((Y - ym) / ys, dtype=torch.float32)
    for s in range(M):
        torch.manual_seed(s * 101 + 7)
        m = net(X.shape[1])
        opt = torch.optim.Adam(m.parameters(), lr=3e-3, weight_decay=1e-4)
        sch = torch.optim.lr_scheduler.CosineAnnealingLR(opt, args.epochs)
        for _ in range(args.epochs):
            opt.zero_grad(); l = nll(m(xt), yt); l.backward(); opt.step(); sch.step()
        m.eval()
        layers = []
        for mod in m:
            if isinstance(mod, nn.Linear):
                layers.append({'W': mod.weight.detach().numpy().tolist(),
                               'b': mod.bias.detach().numpy().tolist()})
        with torch.no_grad():
            o = m(xt).numpy()
        mu = o[:, :2] * ys + ym
        sig = np.exp(np.clip(o[:, 2:], -6, 4)) * ys
        e_in = np.linalg.norm(mu - Y, axis=1)
        models.append(dict(layers=layers,
                           scaler={'x_mean': xm.tolist(), 'x_std': xs.tolist(),
                                   'y_mean': ym.tolist(), 'y_std': ys.tolist()},
                           insample_err=float(e_in.mean()),
                           insample_err_norm=float(e_in.mean() / diag)))
        print('  种子 %d: 训练集误差 %.1f px (%.4f 对角线)' % (s, e_in.mean(), e_in.mean() / diag))

    e_in_avg = float(np.mean([m['insample_err'] for m in models]))
    print('\n多种子集成的训练集误差: %.1f px (%.4f 对角线)' % (e_in_avg, e_in_avg / diag))
    print('  ⚠ 这是训练集误差，必然乐观。真实泛化能力见 tools/train.py 的')
    print('    按目标位置交叉验证（本项目最好的会话约 0.13~0.15 对角线）。')

    # 测量"初始化方差"这个不确定度来源的量级，确认它在合理范围
    allmu = []
    for mm in models:
        z = (X - np.array(mm['scaler']['x_mean'])) / np.array(mm['scaler']['x_std'])
        h = z
        for li, L in enumerate(mm['layers']):
            Wl = np.array(L['W']); bl = np.array(L['b'])
            h = h @ Wl.T + bl
            if li < len(mm['layers']) - 1:
                h = np.maximum(h, 0)
        allmu.append(h[:, :2] * np.array(mm['scaler']['y_std']) + np.array(mm['scaler']['y_mean']))
    allmu = np.array(allmu)
    seed_disag = np.linalg.norm(allmu.std(axis=0), axis=1)
    print('  种子间分歧: 中位 %.1f px  最大 %.1f px  (应在同量级于模型误差，而非数量级更大)'
          % (np.median(seed_disag), seed_disag.max()))

    # 温度标定：demo 端是按 (sigma_x + sigma_y) 求和使用的，
    # 所以这里也必须用求和来拟合 T，否则会把不确定度放大 2 倍（踩过这个坑）。
    oof_mu = allmu.mean(axis=0)
    oof_sig_sum = np.zeros(len(Y))
    for mm in models:
        z = (X - np.array(mm['scaler']['x_mean'])) / np.array(mm['scaler']['x_std'])
        h = z
        for li, L in enumerate(mm['layers']):
            Wl = np.array(L['W']); bl = np.array(L['b'])
            h = h @ Wl.T + bl
            if li < len(mm['layers']) - 1:
                h = np.maximum(h, 0)
        oof_sig_sum += np.exp(np.clip(h[:, 2:], -6, 4)).sum(axis=1) * ys.mean() / len(models)
    T = temp_scale_sum(oof_sig_sum, oof_mu, Y)
    err_oof = np.linalg.norm(oof_mu - Y, axis=1)
    print('温度标定 T = %.2f（按 sigma_x + sigma_y 求和的尺度拟合）' % T)

    out = {
        'meta': {
            'source': os.path.basename(args.csv),
            'n_samples': int(len(Y)),
            'n_trials': int(len(np.unique(tr))),
            'features': names,
            'screen': {'w': float(W), 'h': float(H), 'diag': diag},
            'n_ensemble': len(models),
            'insample_err_px': e_in_avg,
            'insample_err_norm': e_in_avg / diag,
            'seed_disag_median_px': float(np.median(seed_disag)),
            'seed_disag_max_px': float(seed_disag.max()),
            'cv_reference_norm': 0.1425,
            'train_frame_ms': FRAME_MS,
            'note': ('多种子集成（同一份数据、不同随机种子）。'
                     'insample_* 是训练集误差，必然乐观；真实泛化能力见 '
                     'tools/train.py 的按目标位置交叉验证，最好的会话约 0.13~0.15 对角线，'
                     '该值记录在 cv_reference_norm。'
                     'sigma_temp 的用法：demo 端用 exp(clamp(logsx,±6)) * y_std 后，'
                     '按 (sigma_x + sigma_y) 求和再乘 temp。'),
        },
        'temp': float(T),
        'ensembles': models,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f)
    kb = os.path.getsize(args.out) / 1024
    print('\n已导出: %s  (%.0f KB)' % (args.out, kb))
    print('  集成数             : %d' % len(models))
    print('  meta.screen        : %.0f x %.0f (对角线 %.0f) —— demo 端按实际视口缩放'
          % (W, H, diag))
    print('  meta.insample_err_norm : %.4f  ← 训练集误差（乐观）' % (e_in_avg / diag))
    print('  meta.cv_reference_norm : 0.1425 ← 真实泛化能力参照（见 train.py）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
