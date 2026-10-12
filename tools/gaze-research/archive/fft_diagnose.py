#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
fft_diagnose.py — 视线抖动的 FFT 频谱诊断

回答的问题：
  1. 抖动的频谱长什么样？是宽带噪声还是有离散尖峰？
  2. 有没有特定频率的周期性干扰（电源 50/60Hz、屏幕刷新、风扇振动等）？
  3. 各频段能量分布如何？生理性 vs 电子噪声 vs 漂移各占多少？

用法：
    python tools/fft_diagnose.py gaze_p411900_frames.csv
    python tools/fft_diagnose.py gaze_p411900_frames.csv --out fft_result.png
    python tools/fft_diagnose.py gaze_p411900_frames.csv --channel iris_x --min-dot-ms 500

分析方法：
  - 只取每个 trial 的 dot 阶段（固定注视期间）
  - 对每个 trial 做线性去趋势（去掉缓慢漂移）
  - 做 FFT，然后把所有 trial 的频谱做平均（提高信噪比）
  - 同时输出"去趋势前"的频谱，用来观察漂移分量
"""

import argparse
import csv
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import rcParams

# Windows 控制台默认 GBK，中文输出会乱码；这里主动切成 UTF-8
for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 中文字体设置
rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'PingFang SC', 'DejaVu Sans']
rcParams['axes.unicode_minus'] = False


def load_csv(path):
    """读取 CSV，返回 header 映射和数据行。"""
    with open(path, 'r', encoding='utf-8-sig', newline='') as f:
        rd = csv.reader(f)
        header = next(rd)
        rows = [r for r in rd if len(r) == len(header)]
    cols = {name: i for i, name in enumerate(header)}
    return header, cols, rows


def extract_dot_segments(header, cols, rows, channel, min_dot_ms=300):
    """
    从数据中提取每个 trial 的 dot 阶段。
    返回 list of (time_array, value_array)，单位分别为秒、归一化特征值。
    """
    # 按 trial 分组
    trials = {}
    for r in rows:
        if r[cols['phase']] != 'dot':
            continue
        tr = int(r[cols['trial']])
        t = float(r[cols['t']]) / 1000.0  # ms -> s
        val = float(r[cols[channel]])
        trials.setdefault(tr, []).append((t, val))

    segments = []
    for tr, pts in sorted(trials.items()):
        pts.sort(key=lambda x: x[0])
        t_arr = np.array([p[0] for p in pts])
        v_arr = np.array([p[1] for p in pts])
        duration = t_arr[-1] - t_arr[0]
        if duration >= min_dot_ms / 1000.0 and len(t_arr) >= 16:
            segments.append((t_arr, v_arr, tr))
    return segments


def detrend_linear(t, v):
    """线性去趋势，返回残差。"""
    if len(t) < 2:
        return v.copy()
    coeffs = np.polyfit(t - t[0], v, 1)
    trend = np.polyval(coeffs, t - t[0])
    return v - trend


def compute_fft(t, v_detrend, v_raw):
    """
    计算单边振幅谱。
    返回 (freqs, amp_detrend, amp_raw)。
    """
    n = len(t)
    if n < 4:
        return None, None, None

    # 估算采样率
    dt = np.median(np.diff(t))
    fs = 1.0 / dt
    if fs <= 0:
        return None, None, None

    # 加窗（Hann 窗减少频谱泄漏）
    window = np.hanning(n)
    win_norm = np.sum(window) / 2.0  # 单边谱归一化因子

    # FFT
    fft_d = np.fft.rfft(v_detrend * window)
    fft_r = np.fft.rfft(v_raw * window)

    amp_d = np.abs(fft_d) / win_norm
    amp_r = np.abs(fft_r) / win_norm
    freqs = np.fft.rfftfreq(n, d=dt)

    return freqs, amp_d, amp_r, fs


def find_peaks(freqs, amps, min_ratio=0.15, min_freq=0.5):
    """
    找显著尖峰。
    返回 list of (freq, amp, prominence_ratio)。
    min_ratio: 峰值/局部基线 的最小比值
    min_freq: 忽略低于此频率的峰（避免漂移段的大峰干扰）
    """
    peaks = []
    idx = np.where(freqs >= min_freq)[0]
    if len(idx) < 3:
        return peaks

    f_sub = freqs[idx]
    a_sub = amps[idx]

    # 简单的局部最大值检测
    for i in range(2, len(a_sub) - 2):
        if a_sub[i] > a_sub[i-1] and a_sub[i] > a_sub[i+1] \
           and a_sub[i] > a_sub[i-2] and a_sub[i] > a_sub[i+2]:
            # 计算局部基线（左右各 10 个 bin 的中位数）
            left = max(0, i - 10)
            right = min(len(a_sub), i + 11)
            baseline = np.median(np.concatenate([a_sub[left:i], a_sub[i+1:right]]))
            if baseline > 0:
                ratio = a_sub[i] / baseline
                if ratio >= min_ratio:
                    peaks.append((f_sub[i], a_sub[i], ratio))

    # 按 prominence 降序
    peaks.sort(key=lambda x: -x[2])
    return peaks


def band_energy(freqs, amps, bands):
    """计算各频段的能量占比。"""
    # 用振幅的平方近似能量
    energy = amps ** 2
    total = np.trapz(energy, freqs)
    if total <= 0:
        return {}
    result = {}
    for name, (f_lo, f_hi) in bands.items():
        mask = (freqs >= f_lo) & (freqs <= f_hi)
        if np.any(mask):
            e = np.trapz(energy[mask], freqs[mask])
            result[name] = (e, e / total * 100, f_lo, f_hi)
    return result


def main():
    ap = argparse.ArgumentParser(description='视线抖动 FFT 频谱诊断')
    ap.add_argument('csv_path', help='gaze frames CSV 文件路径')
    ap.add_argument('--channel', default='f_irisL_x',
                    help='要分析的特征列名 (默认: f_irisL_x)')
    ap.add_argument('--out', default=None, help='图表输出路径 (默认: 同目录下 fft_<channel>.png)')
    ap.add_argument('--min-dot-ms', type=float, default=300,
                    help='dot 阶段最短时长(ms)，短于此值的试次跳过 (默认: 300)')
    ap.add_argument('--max-freq', type=float, default=None,
                    help='图表 X 轴最大频率 (默认: 奈奎斯特频率的 0.9)')
    args = ap.parse_args()

    if not os.path.exists(args.csv_path):
        print('找不到文件:', args.csv_path)
        return 1

    # ---- 加载数据 ----
    header, cols, rows = load_csv(args.csv_path)
    print('文件: %s  总行数: %d' % (args.csv_path, len(rows)))

    # 找 channel 列
    ch = args.channel
    if ch not in cols:
        # 尝试加 f_ 前缀
        if 'f_' + ch in cols:
            ch = 'f_' + ch
        else:
            print('找不到列:', args.channel)
            print('可用的特征列:')
            for h in header:
                if h.startswith('f_'):
                    print('  ', h)
            return 1
    print('分析通道:', ch)

    # ---- 提取 dot 阶段 ----
    segs = extract_dot_segments(header, cols, rows, ch, args.min_dot_ms)
    print('有效 dot 段数: %d (>= %.0f ms)' % (len(segs), args.min_dot_ms))
    if not segs:
        print('没有足够的数据')
        return 1

    # ---- 估算采样率 ----
    fs_list = []
    for t, v, tr in segs:
        dt = np.median(np.diff(t))
        if dt > 0:
            fs_list.append(1.0 / dt)
    fs_avg = np.mean(fs_list)
    print('平均采样率: %.1f Hz' % fs_avg)

    nyquist = fs_avg / 2.0
    if args.max_freq:
        f_max = min(args.max_freq, nyquist)
    else:
        f_max = nyquist * 0.9

    # ---- 方法一：Welch 平均周期图（高频率分辨率，用于精细分析）----
    # 把所有去趋势后的信号重采样到统一采样率，然后拼接
    # 由于各段采样率接近，直接用统一时间步长插值
    dt_target = 1.0 / fs_avg

    all_detrend = []
    all_raw = []

    for t, v, tr in segs:
        # 重采样到均匀时间网格
        t_uniform = np.arange(t[0], t[-1], dt_target)
        if len(t_uniform) < 8:
            continue
        v_uniform = np.interp(t_uniform, t, v)
        v_d = detrend_linear(t_uniform, v_uniform)
        all_detrend.append(v_d)
        all_raw.append(v_uniform)

    if not all_detrend:
        print('没有可用于 FFT 的数据段')
        return 1

    # Welch 方法：用较长的窗口 + 50% 重叠
    # 选择窗口长度：目标频率分辨率约 0.5 Hz → 窗长 = fs / 0.5
    nperseg = int(fs_avg / 0.5)  # ~200 个采样点，约 2 秒
    nperseg = max(32, min(nperseg, 256))  # 限制在合理范围

    # 把所有段拼接成一个长信号（中间留少量间隙，用零填充）
    gap = nperseg // 4  # 间隙防止段间突变
    long_detrend = []
    long_raw = []
    for i, (vd, vr) in enumerate(zip(all_detrend, all_raw)):
        if i > 0:
            long_detrend.extend(np.zeros(gap))
            long_raw.extend(np.zeros(gap))
        long_detrend.extend(vd)
        long_raw.extend(vr)

    long_detrend = np.array(long_detrend)
    long_raw = np.array(long_raw)

    # 手动实现 Welch（避免依赖 scipy）
    def welch_fft(signal, fs, nperseg, noverlap=None):
        """简化版 Welch 周期图。返回 (freqs, psd)。"""
        if noverlap is None:
            noverlap = nperseg // 2
        n = len(signal)
        window = np.hanning(nperseg)
        win_power = np.sum(window ** 2) / nperseg

        psd_sum = np.zeros(nperseg // 2 + 1)
        count = 0

        start = 0
        while start + nperseg <= n:
            seg = signal[start:start + nperseg] * window
            fft_vals = np.fft.rfft(seg)
            psd = (np.abs(fft_vals) ** 2) / (fs * win_power)
            psd_sum += psd
            count += 1
            start += (nperseg - noverlap)

        if count == 0:
            return None, None
        psd_avg = psd_sum / count
        freqs = np.fft.rfftfreq(nperseg, d=1.0 / fs)
        return freqs, psd_avg

    freqs_welch_d, psd_d = welch_fft(long_detrend, fs_avg, nperseg)
    freqs_welch_r, psd_r = welch_fft(long_raw, fs_avg, nperseg)

    # 振幅谱 = sqrt(PSD) （近似）
    mean_amp_d = np.sqrt(psd_d)
    mean_amp_r = np.sqrt(psd_r)
    freqs_common = freqs_welch_d

    valid_count = len(all_detrend)
    print('Welch 窗长: %d 样点 (%.1f Hz 分辨率)' % (nperseg, fs_avg / nperseg))
    print('有效段数: %d' % valid_count)

    # ---- 找尖峰 ----
    peaks = find_peaks(freqs_common, mean_amp_d, min_ratio=1.4, min_freq=0.5)

    # ---- 频段能量分布 ----
    bands = {
        '漂移/极低频':  (0, 0.5),
        '慢眼动/微扫视': (0.5, 3.0),
        '注视震颤/中抖':  (3.0, 10.0),
        '高频噪声':      (10.0, f_max),
    }
    energy_d = band_energy(freqs_common, mean_amp_d, bands)
    energy_r = band_energy(freqs_common, mean_amp_r, bands)

    # ---- 打印诊断报告 ----
    print()
    print('=' * 72)
    print('  FFT 频谱诊断报告 —— 通道: %s' % ch)
    print('=' * 72)

    print()
    print('【频谱形态】')
    # 计算频谱斜率（log-log 线性拟合）
    mask_slope = (freqs_common >= 0.5) & (freqs_common <= f_max * 0.8) & (mean_amp_d > 0)
    if np.sum(mask_slope) > 10:
        log_f = np.log10(freqs_common[mask_slope])
        log_a = np.log10(mean_amp_d[mask_slope])
        slope, intercept = np.polyfit(log_f, log_a, 1)
        print('  频谱斜率 (log-log): %.2f dB/oct  (约 %.2f dB/decade)'
              % (slope * 6.0, slope * 20.0))
        if slope < -1.5:
            print('  → 典型的 1/f^α 型噪声 (α > 1.5)，以低频为主')
        elif slope < -0.8:
            print('  → 偏粉红噪声 (1/f)，低频能量稍高')
        else:
            print('  → 接近白噪声（频谱平坦），高频能量也很高')

    print()
    print('【频段能量分布 —— 去趋势后】')
    print('  %-18s %-12s %-10s' % ('频段', '能量占比', '频率范围'))
    print('  ' + '-' * 44)
    for name, (e, pct, flo, fhi) in sorted(energy_d.items(), key=lambda x: -x[1][1]):
        print('  %-18s %8.1f %%    %.1f–%.1f Hz' % (name, pct, flo, fhi))

    print()
    print('【频段能量分布 —— 原始（含漂移）】')
    print('  %-18s %-12s %-10s' % ('频段', '能量占比', '频率范围'))
    print('  ' + '-' * 44)
    for name, (e, pct, flo, fhi) in sorted(energy_r.items(), key=lambda x: -x[1][1]):
        print('  %-18s %8.1f %%    %.1f–%.1f Hz' % (name, pct, flo, fhi))

    print()
    print('【显著尖峰（去趋势后，按 prominence 排序）】')
    if peaks:
        print('  %-10s %-14s %-12s %s' % ('频率', '振幅', '突出比', '可能来源'))
        print('  ' + '-' * 56)
        for freq, amp, ratio in peaks[:10]:
            # 猜测来源
            guess = ''
            if 49 <= freq <= 51:
                guess = '电源干扰 (50 Hz)'
            elif 59 <= freq <= 61:
                guess = '电源干扰 (60 Hz)'
            elif 29 <= freq <= 31:
                guess = '可能是屏幕刷新的 1/2 次谐波'
            elif 58 <= freq <= 62 or 118 <= freq <= 122:
                guess = '可能与屏幕刷新率相关'
            elif 9 <= freq <= 11:
                guess = '可能与生理性微扫视节律相关'
            elif freq < 1.0:
                guess = '缓慢头动/漂移残留'
            print('  %8.2f Hz   %12.6f   %7.2fx    %s' % (freq, amp, ratio, guess))
    else:
        print('  未发现显著尖峰 → 抖动以宽带噪声为主')

    # 检查电源干扰候选
    print()
    print('【电源/屏幕干扰快速检查】')
    for f_target, name in [(50, '50 Hz 电源'), (60, '60 Hz 电源'),
                            (25, '25 Hz'), (30, '30 Hz'),
                            (60, '60 Hz 屏幕'), (120, '120 Hz 屏幕'),
                            (144, '144 Hz 屏幕')]:
        if f_target > f_max:
            continue
        idx = np.argmin(np.abs(freqs_common - f_target))
        # 计算该点与周围基线的比值
        left = max(0, idx - 5)
        right = min(len(freqs_common), idx + 6)
        baseline = np.median(np.concatenate(
            [mean_amp_d[left:idx], mean_amp_d[idx+1:right]]))
        if baseline > 0:
            ratio = mean_amp_d[idx] / baseline
            flag = '★ 可疑' if ratio >= 1.4 else ''
            print('  %s: 振幅 %.6f  基线比 %.2fx  %s' % (name, mean_amp_d[idx], ratio, flag))

    # ---- 画图 ----
    out_path = args.out
    if out_path is None:
        base = os.path.splitext(os.path.basename(args.csv_path))[0]
        ch_short = ch.replace('f_', '')
        out_path = os.path.join(os.path.dirname(args.csv_path) or '.',
                                'fft_%s_%s.png' % (base, ch_short))

    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    fig.suptitle('FFT 频谱诊断 — %s (%s)' % (os.path.basename(args.csv_path), ch),
                 fontsize=14, fontweight='bold')

    # 上图：原始信号频谱（含漂移）
    ax = axes[0]
    ax.semilogy(freqs_common, mean_amp_r, color='#12B886', linewidth=1.2, label='原始信号（含漂移）')
    ax.set_ylabel('振幅 (log scale)')
    ax.set_xlabel('频率 (Hz)')
    ax.set_title('原始信号频谱 — 含低频漂移')
    ax.grid(True, alpha=0.3)
    ax.legend()

    # 标注 50/60 Hz
    for f_t, color, label in [(50, '#FF4D4F', '50 Hz'), (60, '#FAAD14', '60 Hz')]:
        if f_t < f_max:
            ax.axvline(x=f_t, color=color, linestyle='--', alpha=0.6, label=label)
            ax.legend()

    # 下图：去趋势后的频谱
    ax = axes[1]
    ax.plot(freqs_common, mean_amp_d, color='#228BE6', linewidth=1.2, label='去趋势后')
    ax.fill_between(freqs_common, 0, mean_amp_d, alpha=0.15, color='#228BE6')
    ax.set_ylabel('振幅')
    ax.set_xlabel('频率 (Hz)')
    ax.set_title('去趋势后频谱 — 反映"纯抖动"的频率构成')
    ax.grid(True, alpha=0.3)
    ax.legend()

    # 标注频段
    ylim = ax.get_ylim()
    band_colors = {
        '漂移': '#94A39C',
        '慢眼动': '#12B886',
        '注视震颤': '#7950F2',
        '高频噪声': '#E64980',
    }
    for name, (flo, fhi, color) in [
        ('漂移', (0, 0.5, band_colors['漂移'])),
        ('慢眼动/微扫视', (0.5, 3.0, band_colors['慢眼动'])),
        ('注视震颤', (3.0, 10.0, band_colors['注视震颤'])),
        ('高频噪声', (10.0, f_max, band_colors['高频噪声'])),
    ]:
        if fhi > f_max:
            fhi = f_max
        ax.axvspan(flo, fhi, alpha=0.08, color=color)
        # 在顶部标注
        ax.text((flo + fhi) / 2, ylim[1] * 0.95, name,
                ha='center', va='top', fontsize=9, color=color, fontweight='bold')

    # 标注显著尖峰
    for freq, amp, ratio in peaks[:5]:
        ax.annotate('%.1f Hz\n(%.1fx)' % (freq, ratio),
                    xy=(freq, amp),
                    xytext=(freq + f_max * 0.02, amp * 1.3),
                    fontsize=8,
                    arrowprops=dict(arrowstyle='->', color='#FF4D4F', lw=1),
                    color='#FF4D4F')

    # 标注 50/60 Hz
    for f_t, color, label in [(50, '#FF4D4F', '50 Hz'), (60, '#FAAD14', '60 Hz')]:
        if f_t < f_max:
            ax.axvline(x=f_t, color=color, linestyle='--', alpha=0.5)
            idx = np.argmin(np.abs(freqs_common - f_t))
            ax.plot(f_t, mean_amp_d[idx], 'o', color=color, markersize=6)

    # 底部添加诊断摘要文本
    diag_lines = []
    if energy_d:
        top_band = max(energy_d.items(), key=lambda x: x[1][1])
        diag_lines.append('主要能量频段: %s (%.1f%%)' % (top_band[0], top_band[1][1]))
    if peaks:
        diag_lines.append('发现 %d 个显著尖峰，最强: %.1f Hz (%.1fx)'
                          % (len(peaks), peaks[0][0], peaks[0][2]))
    else:
        diag_lines.append('无显著尖峰，为宽带噪声')
    diag_lines.append('平均采样率: %.1f Hz | 有效试次: %d' % (fs_avg, valid_count))

    fig.text(0.5, 0.02, '  |  '.join(diag_lines),
             ha='center', fontsize=10, color='#3C4A45',
             bbox=dict(boxstyle='round', facecolor='#F6FAF8', edgecolor='#D6E3DC'))

    plt.tight_layout(rect=[0, 0.04, 1, 0.96])
    plt.savefig(out_path, dpi=150, bbox_inches='tight')
    print()
    print('图表已保存:', out_path)

    # ---- 最终结论 ----
    print()
    print('=' * 72)
    print('  诊断结论')
    print('=' * 72)

    conclusions = []

    # 结论1：频谱形态
    if 'slope' in dir():
        if slope < -1.5:
            conclusions.append(
                '频谱呈 1/f^α 型(α≈%.1f)，低频主导。'
                '这是生理性注视不稳的典型特征，滤波能降绝对值但降不了信噪比。' % (-slope))
        elif slope < -0.8:
            conclusions.append(
                '频谱偏粉红噪声(1/f)，低频稍高。有一定滤波空间，但有限。')
        else:
            conclusions.append(
                '频谱较平坦（接近白噪声），高频能量高。'
                '这可能说明传感器噪声/量化噪声占比较大，低通滤波会有明显效果。')

    # 结论2：尖峰
    if peaks:
        strong_peaks = [p for p in peaks if p[2] >= 2.0]
        if strong_peaks:
            conclusions.append(
                '发现 %d 个强尖峰(突出比≥2x)，最强在 %.1f Hz。'
                '这些是周期性干扰，可以用陷波滤波器精准去除，代价极小。'
                % (len(strong_peaks), strong_peaks[0][0]))
        else:
            conclusions.append(
                '有一些弱尖峰但都不突出(最高 %.1fx)。'
                '陷波滤波帮助有限，不建议优先做。' % peaks[0][2])
    else:
        conclusions.append(
            '未发现显著尖峰。抖动以宽带噪声为主，陷波滤波帮不上忙。')

    # 结论3：漂移占比
    if energy_r:
        drift_pct = energy_r.get('漂移/极低频', (0, 0))[1]
        if drift_pct > 40:
            conclusions.append(
                '极低频漂移占原始信号能量的 %.1f%%，占比很高。'
                '自适应标定/漂移修正能吃掉这部分，建议优先做。' % drift_pct)
        elif drift_pct > 20:
            conclusions.append(
                '极低频漂移占 %.1f%%，有一定贡献。'
                '自适应标定会有帮助但不是决定性的。' % drift_pct)

    for i, c in enumerate(conclusions, 1):
        print('  %d. %s' % (i, c))

    print()
    print('=' * 72)

    return 0


if __name__ == '__main__':
    sys.exit(main())
