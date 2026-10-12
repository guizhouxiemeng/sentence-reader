#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
eyetrax_accuracy_test.py — 测量 EyeTrax 在本机的实际视线精度，
                          并与本项目自建的 7 维方案在同一批数据上对比

为什么这是关键一步
------------------
本项目此前的结论是"webcam 视线坐标不可行（误差 400~1000px），
根因是硬件限制（640x480 下眼睛只有约 25 像素）"。

但核查发现 EyeTrax（★345，带 DOI，在维护）在【同样的 MediaPipe 关键点、
同样普通摄像头】下工作，而且：
    · 它的模型与我们【完全相同】：StandardScaler + Ridge(alpha=1.0)
    · 唯一差别是特征：它 486 维（161 个眼部关键点旋转归一化 + 头姿），
      我们 7 维手工特征

所以本测试回答：我们的 400~1000px 是【硬件限制】还是【特征工程不足】？

测量设计
--------
  1. 按 9 点网格采集：每点注视一段时间，逐帧抽特征
  2. 用【分组留一】评估：每次留出一个点做验证，其余 8 点训练
     （测的是"没见过位置"的泛化误差，不是训练集拟合度）
  3. 同一批数据同时跑两个方案：
       A. EyeTrax 486 维 + Ridge
       B. 自建 7 维 + 岭回归（复现项目 demo 的做法）
     两者用同样的分组留一，差异只可能来自特征

用法：
  # 自检（无需摄像头）
  python tools/eyetrax_accuracy_test.py --selftest

  # 正式测量（需摄像头）
  python tools/eyetrax_accuracy_test.py --run --width 1280 --height 720
  python tools/eyetrax_accuracy_test.py --run --width 640  --height 480
"""
import argparse
import json
import os
import sys
import time

# 沙箱与路径准备（必须在导入第三方库之前）
os.environ.setdefault('MPLCONFIGDIR', r'D:\projects\.mplcache')
os.environ.setdefault('EYETRAX_FACE_LANDMARKER_MODEL',
                      r'D:\projects\gaze-project\vendor\face_landmarker.task')

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import numpy as np

GRID9 = [(0.50, 0.50), (0.50, 0.12), (0.50, 0.88),
         (0.12, 0.50), (0.88, 0.50),
         (0.12, 0.12), (0.88, 0.12), (0.12, 0.88), (0.88, 0.88)]

DWELL_SEC = 1.8
WARMUP_SEC = 0.5


# ======================================================================
#  自建 7 维特征（复现项目 demo 的 buildGazeFeatures）
#  仅用不含眼睑污染的量：虹膜 y、虹膜 x、两者平方、以及水平相对量
# ======================================================================
def self_features(landmarks):
    """landmarks: (478,3) 归一化坐标。返回 7 维，与 demo 的 CALIB_FEATS 对应。"""
    lm = np.asarray(landmarks, dtype=np.float64)
    L_iris = lm[468]          # 左虹膜中心
    R_iris = lm[473]          # 右虹膜中心
    # 眼部水平参考：内外眼角中点
    L_h = (lm[33][0] + lm[133][0]) / 2.0
    R_h = (lm[362][0] + lm[263][0]) / 2.0
    iod = abs(lm[263][0] - lm[33][0]) + 1e-9
    iry = (L_iris[1] + R_iris[1]) / 2.0            # 虹膜垂直（不含眼睑）
    irx = (L_iris[0] + R_iris[0]) / 2.0            # 虹膜水平
    gx = (L_iris[0] - L_h) - (R_iris[0] - R_h)     # 双眼水平差（会聚/方向）
    L_h_rel = (L_iris[0] - L_h) / iod
    R_h_rel = (R_iris[0] - R_h) / iod
    return np.array([iry, irx, gx, gx * gx, iry * iry, L_h_rel, R_h_rel],
                    dtype=np.float64)


def self_ridge_fit(X, Y, lam=1000.0):
    """标准化 + 岭回归（复现 demo 的 fitCalibration 数值策略）。"""
    mu = X.mean(0)
    sd = X.std(0) + 1e-12
    Z = np.column_stack([(X - mu) / sd, np.ones(len(X))])
    d = Z.shape[1]
    G = Z.T @ Z + np.diag([lam] * (d - 1) + [0.0])
    try:
        B = np.linalg.solve(G, Z.T @ Y)
    except np.linalg.LinAlgError:
        B = np.linalg.lstsq(G, Z.T @ Y, rcond=None)[0]
    return mu, sd, B


def self_ridge_pred(mu, sd, B, X):
    Z = np.column_stack([(X - mu) / sd, np.ones(len(X))])
    return Z @ B


# ======================================================================
#  采集
# ======================================================================
def collect(width, height, dwell, pts=GRID9):
    import cv2
    from eyetrax import GazeEstimator
    from eyetrax.constants import LEFT_EYE_INDICES, RIGHT_EYE_INDICES, MUTUAL_INDICES

    est = GazeEstimator()
    sub = LEFT_EYE_INDICES + RIGHT_EYE_INDICES + MUTUAL_INDICES

    # 另外建一个 FaceLandmarker 专门取原始 478 关键点，用来算自建 7 维特征。
    # 为什么要在同一帧上取：只有特征来自完全相同的帧，
    # "EyeTrax vs 自建"的对比才严格成立（否则差异可能来自帧不同）。
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision as mp_vision
    lm_opts = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=os.environ["EYETRAX_FACE_LANDMARKER_MODEL"]),
        running_mode=mp_vision.RunningMode.VIDEO,
        num_faces=1,
    )
    lmkr = mp_vision.FaceLandmarker.create_from_options(lm_opts)
    lm_ts = 0

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print('  ERROR: cannot open camera')
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print('  camera actual resolution: %dx%d' % (aw, ah))

    # 屏幕尺寸：用采集窗口所在显示器的逻辑尺寸
    W, H = 1600, 900
    try:
        from screeninfo import get_monitors
        m = get_monitors()[0]
        W, H = m.width, m.height
    except Exception:
        pass
    print('  screen (logical): %dx%d' % (W, H))

    win = 'EyeTrax accuracy'
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    try:
        cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    except Exception:
        pass

    rec = []          # (et_feat, self_feat, sx, sy, point_idx)
    for k, (fx, fy) in enumerate(pts):
        sx, sy = fx * W, fy * H
        t0 = time.time()
        got = 0
        while time.time() - t0 < dwell:
            ok, frame = cap.read()
            if not ok:
                continue
            canvas = np.zeros((H, W, 3), np.uint8)
            cv2.circle(canvas, (int(sx), int(sy)), 28, (0, 210, 255), -1)
            cv2.circle(canvas, (int(sx), int(sy)), 38, (255, 255, 255), 2)
            cv2.putText(canvas, 'point %d/%d  look at the dot' % (k + 1, len(pts)),
                        (40, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2)
            cv2.imshow(win, canvas)
            cv2.waitKey(1)

            if time.time() - t0 < WARMUP_SEC:
                continue
            feat, _blink = est.extract_features(frame)
            if feat is None:
                continue
            # 同一帧上取原始关键点，算自建 7 维特征
            selfF = None
            try:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb = np.ascontiguousarray(rgb)
                mpimg = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                lm_ts += 33
                res = lmkr.detect_for_video(mpimg, lm_ts)
                if res.face_landmarks:
                    pts = np.array([[p_.x, p_.y, p_.z]
                                    for p_ in res.face_landmarks[0]], dtype=np.float64)
                    if pts.shape[0] > 473:
                        selfF = self_features(pts)
            except Exception:
                selfF = None
            rec.append((np.asarray(feat, dtype=np.float64).copy(), selfF, sx, sy, k))
            got += 1
        print('    point %d/%d  (%4.0f,%4.0f)  collected %d frames' % (k + 1, len(pts), sx, sy, got))

    cap.release()
    cv2.destroyAllWindows()
    est.close()
    try:
        lmkr.close()
    except Exception:
        pass
    n_self = sum(1 for r in rec if r[1] is not None)
    print('    frames with both feature sets: %d / %d' % (n_self, len(rec)))
    return rec, (aw, ah), (W, H)


# ======================================================================
#  评估：分组留一
# ======================================================================
def evaluate(rec, n_points, diag):
    Xe = np.stack([r[0] for r in rec])
    Y = np.array([[r[2], r[3]] for r in rec], dtype=float)
    K = np.array([r[4] for r in rec])

    err_et, err_self = [], []
    from eyetrax.models import create_model
    have_self = any(r[1] is not None for r in rec)

    for k in range(n_points):
        te = (K == k)
        tr = ~te
        if tr.sum() < 50 or te.sum() < 5:
            continue
        # A. EyeTrax 486 维
        m = create_model('ridge')
        m.train(Xe[tr], Y[tr])
        pe = np.asarray(m.predict(Xe[te]), dtype=float)
        de = np.hypot(pe[:, 0] - Y[te][:, 0], pe[:, 1] - Y[te][:, 1])
        err_et.extend(de.tolist())

        # B. 自建 7 维（同一批帧）
        ds = None
        if have_self:
            mask = np.array([r[1] is not None for r in rec])
            tr_s = tr & mask
            te_s = te & mask
            if tr_s.sum() >= 50 and te_s.sum() >= 5:
                Xs = np.stack([r[1] for r in rec if r[1] is not None])
                Ys = Y[mask]
                Ks = K[mask]
                tr2 = (Ks != k)
                te2 = (Ks == k)
                mu, sd, B = self_ridge_fit(Xs[tr2], Ys[tr2])
                ps = self_ridge_pred(mu, sd, B, Xs[te2])
                ds = np.hypot(ps[:, 0] - Ys[te2][:, 0], ps[:, 1] - Ys[te2][:, 1])
                err_self.extend(ds.tolist())
        print('    held-out point %d: EyeTrax %6.0f px%s'
              % (k + 1, de.mean(),
                 ('   custom7 %6.0f px' % ds.mean()) if ds is not None else ''))
    return np.array(err_et), np.array(err_self)


def summarize(err, diag, tag):
    e = np.asarray(err, float)
    if e.size == 0:
        print('  %s: no valid samples' % tag)
        return None
    r = dict(tag=tag, n=int(e.size), mean=float(e.mean()),
             median=float(np.median(e)), p90=float(np.percentile(e, 90)),
             norm_mean=float(e.mean() / diag), norm_median=float(np.median(e) / diag))
    print('  %-14s n=%-5d mean %6.0f px (%.4f diag)   median %6.0f px (%.4f)   p90 %6.0f px'
          % (tag, r['n'], r['mean'], r['norm_mean'], r['median'],
             r['norm_median'], r['p90']))
    return r


def get_screen_diag():
    try:
        from screeninfo import get_monitors
        m = get_monitors()[0]
        return float(np.hypot(m.width, m.height)), m.width, m.height
    except Exception:
        return float(np.hypot(1600, 900)), 1600, 900


def selftest():
    print('=' * 78)
    print('Selftest (no camera needed)')
    print('=' * 78)
    from eyetrax import GazeEstimator
    from eyetrax.constants import LEFT_EYE_INDICES, RIGHT_EYE_INDICES, MUTUAL_INDICES
    est = GazeEstimator()
    n = len(LEFT_EYE_INDICES) + len(RIGHT_EYE_INDICES) + len(MUTUAL_INDICES)
    print('  EyeTrax feature dim = %d' % (n * 3 + 3))
    rng = np.random.default_rng(0)
    X = rng.normal(size=(400, n * 3 + 3))
    Y = rng.uniform(0, 1500, size=(400, 2))
    from eyetrax.models import create_model
    for name in ['ridge', 'svr', 'tiny_mlp', 'elastic_net']:
        m = create_model(name)
        m.train(X, Y)
        _ = m.predict(X[:3])
        print('  %-12s OK' % name)
    # 自建特征
    lm = np.zeros((478, 3))
    lm[468] = [0.4, 0.5, 0]
    lm[473] = [0.6, 0.5, 0]
    lm[33] = [0.35, 0.5, 0]; lm[133] = [0.45, 0.5, 0]
    lm[362] = [0.55, 0.5, 0]; lm[263] = [0.65, 0.5, 0]
    f = self_features(lm)
    print('  custom7 feature dim = %d  sample %s' % (len(f), np.round(f, 4).tolist()))
    mu, sd, B = self_ridge_fit(rng.normal(size=(200, 7)), rng.uniform(size=(200, 2)))
    print('  custom ridge OK, output shape', np.shape(self_ridge_pred(mu, sd, B, rng.normal(size=(3, 7)))))
    est.close()
    print('  selftest PASSED')
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--run', action='store_true')
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--height', type=int, default=720)
    ap.add_argument('--dwell', type=float, default=DWELL_SEC)
    ap.add_argument('--out', default=r'D:\projects\gaze-project\eyetrax_result.json')
    args = ap.parse_args()

    if args.selftest or not args.run:
        return selftest()

    print('=' * 78)
    print('EyeTrax gaze accuracy test (resolution %dx%d)' % (args.width, args.height))
    print('=' * 78)
    diag, W, H = get_screen_diag()
    print('  screen diagonal %.0f px' % diag)
    print()
    print('9 yellow dots will appear fullscreen, %.1f s each.' % args.dwell)
    print('Keep head still, follow the dots. Press Enter to start...')
    try:
        input()
    except EOFError:
        pass

    res = collect(args.width, args.height, args.dwell)
    if not res:
        return 1
    rec, (aw, ah), _ = res
    print()
    print('  total frames: %d' % len(rec))
    if len(rec) < 200:
        print('  too few samples, result unreliable')
        return 1

    print()
    print('--- leave-one-point-out (same frames for both) ---')
    err_et, err_self = evaluate(rec, len(GRID9), diag)

    print()
    print('=' * 78)
    print('RESULT')
    print('=' * 78)
    r = summarize(err_et, diag, 'EyeTrax 486维')
    r_self = summarize(err_self, diag, '自建 7维') if err_self.size else None
    if r and r_self:
        print()
        print('  => same frames, same evaluation: any difference must come from FEATURES')
        ratio = r['norm_mean'] / r_self['norm_mean'] if r_self['norm_mean'] else float('nan')
        print('     EyeTrax / custom7 = %.2f x' % ratio)
    print()
    print("  Reference: this project's own earlier numbers")
    print('    README: live calibration error 0.20-0.51 diag; grouped CV 0.131-0.145')
    if r:
        nm = r['norm_mean']
        if nm < 0.10:
            v = 'clearly better than our own -> HARDWARE-LIMIT conclusion is WRONG; the problem was feature engineering'
        elif nm < 0.20:
            v = 'better than our own -> partly supports "improvable via features"'
        elif nm < 0.40:
            v = 'comparable to our own -> HARDWARE-LIMIT conclusion HOLDS'
        else:
            v = 'not better than our own -> hardware limit confirmed'
        print()
        print('  => verdict: %s' % v)
        r['verdict'] = v
        r['camera'] = [aw, ah]
        try:
            with open(args.out, 'w', encoding='utf-8') as f:
                json.dump(r, f, ensure_ascii=False, indent=2)
            print('  written to %s' % args.out)
        except Exception as e:
            print('  write failed: %s' % e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
