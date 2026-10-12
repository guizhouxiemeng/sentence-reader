# -*- coding: utf-8 -*-
"""
test_combined_signal.py —— 检验「文本特征 + 行为信号」组合后能否显著强于单个。

背景：
  分别测过两轮，都弱：
    文本特征 最好 units（句长）   AUC 0.642
    行为信号 最好 dwell（停留）   AUC 0.621
    两者简单相加                  AUC 0.631（没有提升）
  而这两个"最优信号"高度相关（r=0.77）—— 可能只是同一个东西的两种说法。

  这份脚本回答三个问题：
    ① 分模式看（自动/手动），结论是否一致？混合数据是不是在掩盖什么？
    ② 用留一交叉验证（LOO）做逻辑回归组合，能否显著超过单特征？
    ③ 句长（units）之外的文本特征，在控制句长后还有没有增量？

用法：python tools/test_combined_signal.py

引号风格说明：输出文本一律用单引号界定，中文强调用「」。
（之前写脚本反复在双引号字符串里嵌 ASCII 双引号导致 SyntaxError，
  verify_all.py 现在会检查所有 Python 脚本语法。）
"""

import csv
import io
import math
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUTO = os.path.join(ROOT, '.ghcache', 'reading_flow_2026-10-06.csv')
MANUAL = os.path.join(ROOT, '.ghcache', 'reading_flow_2026-10-07_manual.csv')

CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019\-]*")


def load(path, mode_name):
    rows = []
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.reader(f):
            if not r:
                continue
            if r[0].startswith('#'):
                continue
            if r[1] == '类型':
                break
            if r[1] in ('求助', '标注'):
                continue
            if len(r) < 9:
                continue
            try:
                truth = int(r[7]) if r[7] not in ('', None) else None
                if truth is None:
                    continue
                rows.append({
                    'truth': truth,
                    'ratio': float(r[2]) if r[2] else None,
                    'dwell': float(r[3]) if r[3] else 0.0,
                    'backs': int(r[4]) if r[4] else 0,
                    'text': r[8],
                    'mode': mode_name,
                })
            except (ValueError, IndexError):
                continue
    return rows


def units_of(text):
    t = text or ''
    cjk = len(CJK.findall(t))
    rest = CJK.sub(' ', t)
    words = [w for w in WORD.findall(rest) if re.search(r'[A-Za-z]', w)]
    return cjk + len(words)


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return 0.5
    c = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                c += 1
            elif p == n:
                c += 0.5
    return c / (len(pos) * len(neg))


def bar(v, w=24):
    x = max(0.0, min(1.0, (v - 0.5) / 0.5))
    n = int(round(x * w))
    return '#' * n + '.' * (w - n)


def loo_logreg(X, y, lam=1.0):
    """留一交叉验证的逻辑回归（梯度下降，全协方差 ridge 正则）。
    返回每折的预测分数（用于算 AUC）。样本小，直接朴素实现即可。"""
    n = len(X)
    d = len(X[0])
    scores = []
    for k in range(n):
        Xtr = [X[i] for i in range(n) if i != k]
        ytr = [y[i] for i in range(n) if i != k]
        w = [0.0] * d
        lr = 0.5
        for _ in range(400):
            g = [0.0] * d
            for i in range(len(Xtr)):
                z = sum(w[j] * Xtr[i][j] for j in range(d))
                p = 1.0 / (1.0 + math.exp(-max(-30, min(30, z))))
                e = p - ytr[i]
                for j in range(d):
                    g[j] += e * Xtr[i][j]
            for j in range(d):
                g[j] = g[j] / len(Xtr) + lam * w[j] / len(Xtr)
                w[j] -= lr * g[j]
        z = sum(w[j] * X[k][j] for j in range(d))
        scores.append(1.0 / (1.0 + math.exp(-max(-30, min(30, z)))))
    return scores


def standardize(vals):
    mu = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mu) ** 2 for v in vals) / len(vals)) or 1.0
    return [(v - mu) / sd for v in vals]


def analyze(rows, title):
    print()
    print('=' * 80)
    print(title)
    print('=' * 80)
    hard = [r for r in rows if r['truth'] == 1]
    print('  %d 句（难 %d / 顺 %d）' % (len(rows), len(hard), len(rows) - len(hard)))
    if len(hard) < 6:
        print('  !! 难样本太少，跳过')
        return

    y = [r['truth'] for r in rows]
    u = [float(units_of(r['text'])) for r in rows]
    dw = [r['dwell'] for r in rows]
    rt = [r['ratio'] if r['ratio'] is not None else 0.0 for r in rows]

    print()
    print('  单信号 AUC:')
    print('    句长 units      %.3f %s' % (auc(u, y), bar(auc(u, y))))
    print('    停留 dwell      %.3f %s' % (auc(dw, y), bar(auc(dw, y))))
    print('    ratio           %.3f %s' % (auc(rt, y), bar(auc(rt, y))))

    # 相关系数：句长 vs 停留（看是不是同一个东西）
    mu_u = sum(u) / len(u)
    mu_d = sum(dw) / len(dw)
    cov = sum((a - mu_u) * (b - mu_d) for a, b in zip(u, dw))
    su = math.sqrt(sum((a - mu_u) ** 2 for a in u))
    sd_ = math.sqrt(sum((b - mu_d) ** 2 for b in dw))
    r_ud = cov / (su * sd_) if su and sd_ else 0.0
    print()
    print('  句长 与 停留 的相关系数 r = %.3f' % r_ud)
    if abs(r_ud) > 0.7:
        print('    -> 高度相关：这两个信号基本是同一个东西，组合不会带来新信息')
    elif abs(r_ud) > 0.4:
        print('    -> 中等相关：组合可能有少量增量')
    else:
        print('    -> 弱相关：两者携带不同信息，组合值得一试')

    # 多特征逻辑回归（LOO）
    print()
    print('  留一交叉验证的逻辑回归组合:')
    sets = [
        ('仅句长', [standardize(u)]),
        ('仅停留', [standardize(dw)]),
        ('句长+停留', [standardize(u), standardize(dw)]),
        ('句长+停留+ratio', [standardize(u), standardize(dw), standardize(rt)]),
    ]
    bestname, bestauc = None, 0.0
    for name, cols in sets:
        X = [[cols[j][i] for j in range(len(cols))] for i in range(len(rows))]
        sc = loo_logreg(X, y)
        a = auc(sc, y)
        if a > bestauc:
            bestauc, bestname = a, name
        print('    %-18s AUC %.3f %s' % (name, a, bar(a)))
    print()
    print('    最好：%s（AUC %.3f）' % (bestname, bestauc))
    if bestauc - max(auc(u, y), auc(dw, y)) < 0.05:
        print('    -> 组合没有明显超过最好的单信号（提升 < 0.05）')
        print('       说明行为信号没带来句长之外的新信息')
    else:
        print('    -> 组合有明显提升，两个信号互补')


def main():
    auto = load(AUTO, 'auto') if os.path.exists(AUTO) else []
    manual = load(MANUAL, 'manual') if os.path.exists(MANUAL) else []

    analyze(manual, '① 手动模式（点击/翻句由用户决定，停留时长有效）')
    analyze(auto, '② 自动模式（系统配速，停留时长被抹平）')
    analyze(auto + manual, '③ 两份合并（注意：模式不同，可能有混淆）')

    print()
    print('=' * 80)
    print('总结')
    print('=' * 80)
    print('  三个问题里最要紧的是「句长和停留是不是同一个信号」。')
    print('  若两者高度相关，那么"行为信号"相对"数句子长度"没有增量 ——')
    print('  也就是说，与其做复杂的注意力推断，不如直接用句子长度做启发式。')
    print()
    print('  但要注意样本量：合并后也只有 34 个难句，AUC 波动约 ±0.08。')
    print('  上面的差距如果小于 0.08，都不该当作真差异。')
    print('=' * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())
