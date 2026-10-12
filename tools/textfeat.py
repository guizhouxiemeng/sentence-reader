# -*- coding: utf-8 -*-
"""
analyze_text_features.py —— 用已有标注数据，检验「文本特征能不能预测难句」。

为什么做这个：
  行为信号（停留时长/回看次数）已经验证过两轮：
    自动模式 ratio 标准差 0.498（信号被系统配速抹平）
    手动模式 难/顺 ratio 中位 3.44 vs 1.65（活了，但分布重叠，F1 约 0.46）
  而文本特征【不需要用户任何行为】—— 句子本身的属性就有难度信息。
  实测已露苗头：长句更容易被标为难（与停留时长相关 r=0.77）。

  两者是不同类的信号，可能互补：
    行为信号捕捉「当下状态」，文本特征捕捉「句子客观难度」。

数据：两份实测 CSV 的标注句（自动 90 句 + 手动 29 句）
用法：python tools/analyze_text_features.py

注意本文件的引号风格：
  所有输出文本都用【单引号】界定，中文里的强调用「」。
  原因是之前写脚本时反复犯同一个错 —— 在双引号字符串里嵌了 ASCII 双引号，
  导致 SyntaxError。verify_all.py 现在会检查所有 Python 脚本的语法。
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
FILES = [
    os.path.join(ROOT, '.ghcache', 'reading_flow_2026-10-06.csv'),
    os.path.join(ROOT, '.ghcache', 'reading_flow_2026-10-07_manual.csv'),
]

CJK = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]')
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'\u2019\-]*")
CONN = re.compile(
    r'\b(?:which|that|who|whom|whose|where|when|while|although|'
    r'though|however|therefore|moreover|furthermore|whereas|'
    r'because|since|unless|despite|according)\b', re.I)


def load(path):
    rows = []
    mode = '?'
    with io.open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.reader(f):
            if not r:
                continue
            if r[0].startswith('#'):
                m = re.search(r'推进模式=(\w+)', r[0])
                if m:
                    mode = m.group(1)
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
                    'text': r[8],
                    'mode': mode,
                })
            except (ValueError, IndexError):
                continue
    return rows


def features(text):
    """从句子文本算特征。全部不需要外部语料，纯本地可算。"""
    t = text.strip()
    cjk = CJK.findall(t)
    rest = CJK.sub(' ', t)
    words = [w for w in WORD.findall(rest) if re.search(r'[A-Za-z]', w)]

    units = len(cjk) + len(words)
    avg_wlen = (sum(len(w) for w in words) / len(words)) if words else 0.0
    long_w = sum(1 for w in words if len(w) >= 9)
    long_w_ratio = (long_w / len(words)) if words else 0.0

    commas = t.count(',') + t.count('\uff0c')
    semis = t.count(';') + t.count('\uff1b')
    dashes = t.count('\u2014') + t.count('\u2013')
    conn = len(CONN.findall(t))
    clause = commas + semis + dashes + conn

    digits = len(re.findall(r'\d', t))
    parens = t.count('(') + t.count('\uff08')
    quotes = t.count('"') + t.count('\u201c') + t.count('\u201d')
    proper = 1 if re.search(r'(?<!^)(?<![.\s])\s[A-Z][a-z]{2,}', t) else 0

    return {
        'units': float(units),
        'avg_wlen': avg_wlen,
        'long_w_ratio': long_w_ratio,
        'clause': float(clause),
        'clause_per_unit': (clause / units * 10.0) if units else 0.0,
        'digits': float(digits),
        'parens': float(parens),
        'quotes': float(quotes),
        'proper': float(proper),
    }


def pearson(xs, ys):
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    sx = math.sqrt(sum((a - mx) ** 2 for a in xs))
    sy = math.sqrt(sum((b - my) ** 2 for b in ys))
    return cov / (sx * sy) if sx and sy else 0.0


def auc(scores, labels):
    """ROC-AUC：随机取一个难句和一个顺句，难句得分更高的概率。"""
    pos = [s for s, l in zip(scores, labels) if l == 1]
    neg = [s for s, l in zip(scores, labels) if l == 0]
    if not pos or not neg:
        return 0.5
    cnt = 0.0
    for p in pos:
        for n in neg:
            if p > n:
                cnt += 1
            elif p == n:
                cnt += 0.5
    return cnt / (len(pos) * len(neg))


def bar(v, width=22):
    """把 0.5~1.0 的 AUC 画成小条，便于一眼看出强弱。"""
    x = max(0.0, min(1.0, (v - 0.5) / 0.5))
    n = int(round(x * width))
    return '#' * n + '.' * (width - n)


def main():
    rows = []
    for f in FILES:
        if os.path.exists(f):
            rows += load(f)
    if not rows:
        print('没读到标注数据（先跑一次实测并导出 CSV）')
        return 1

    hard = [r for r in rows if r['truth'] == 1]
    easy = [r for r in rows if r['truth'] == 0]
    labels = [r['truth'] for r in rows]

    print('=' * 80)
    print('文本特征能否预测难句')
    print('=' * 80)
    print('  样本：%d 句标注（难 %d / 顺 %d）' % (len(rows), len(hard), len(easy)))

    modes = {}
    for r in rows:
        modes[r['mode']] = modes.get(r['mode'], 0) + 1
    print('  来源：' + '，'.join('%s %d 句' % (k, v) for k, v in modes.items()))
    if len(hard) < 10:
        print('  !! 「难」样本不足 10 个，结论只能当探索性观察')
    print()

    feats = list(features(rows[0]['text']).keys())
    allv = {f: [features(r['text'])[f] for r in rows] for f in feats}

    print('=' * 80)
    print('逐特征区分力')
    print('=' * 80)
    print('  %-16s %8s %9s %9s  %s' % ('特征', '相关', '难句均值', '顺句均值', 'AUC (0.5=无用)'))
    print('  ' + '-' * 74)

    res = []
    for f in feats:
        vals = allv[f]
        rc = pearson(vals, labels)
        a = auc(vals, labels)
        hv = [v for v, r in zip(vals, rows) if r['truth'] == 1]
        ev = [v for v, r in zip(vals, rows) if r['truth'] == 0]
        mh = sum(hv) / len(hv) if hv else 0.0
        me = sum(ev) / len(ev) if ev else 0.0
        res.append((abs(a - 0.5), f, rc, mh, me, a))
        print('  %-16s %8.3f %9.2f %9.2f  %.3f %s' % (f, rc, mh, me, a, bar(a)))

    res.sort(reverse=True)
    best = res[0]
    print()
    print('=' * 80)
    print('最好的单个文本特征')
    print('=' * 80)
    print('  %s   AUC %.3f   相关系数 %.3f' % (best[1], best[5], best[2]))
    print()

    top3 = [f for _, f, *_ in res[:3]]
    print('=' * 80)
    print('top3 特征简单组合（标准化后按相关方向相加）')
    print('=' * 80)
    print('  使用：' + ' + '.join(top3))
    combo = [0.0] * len(rows)
    for f in top3:
        v = allv[f]
        mu = sum(v) / len(v)
        sd = math.sqrt(sum((a - mu) ** 2 for a in v) / len(v)) or 1.0
        sign = 1.0 if next(x[2] for x in res if x[1] == f) >= 0 else -1.0
        for i in range(len(rows)):
            combo[i] += sign * (v[i] - mu) / sd
    a_combo = auc(combo, labels)
    print('  组合 AUC = %.3f  %s' % (a_combo, bar(a_combo)))

    print()
    print('=' * 80)
    print('对照：行为信号在同样本上的表现')
    print('=' * 80)
    rr = [r for r in rows if r['ratio'] is not None]
    if len(rr) >= 5:
        a1 = auc([r['ratio'] for r in rr], [r['truth'] for r in rr])
        print('  ratio（停留/预期）  AUC %.3f  %s' % (a1, bar(a1)))
    dw = [r for r in rows if r['dwell'] > 0]
    if len(dw) >= 5:
        a2 = auc([r['dwell'] for r in dw], [r['truth'] for r in dw])
        print('  dwell（停留秒数）   AUC %.3f  %s' % (a2, bar(a2)))

    print()
    print('=' * 80)
    print('结论')
    print('=' * 80)
    top = max(best[5], a_combo)
    if top >= 0.70:
        print('  文本特征有实用区分力（最高 AUC %.2f）-> 值得做成组合模型' % top)
    elif top >= 0.60:
        print('  文本特征有微弱区分力（最高 AUC %.2f）' % top)
        print('  -> 单独用不够，但可作为行为信号的补充（两者不同类）')
    else:
        print('  文本特征区分力不足（最高 AUC %.2f）' % top)
        print('  -> 注意：这说的是「这几个简单特征不行」，')
        print('     不代表用词频/句法模型也不行（那需要语料和更大样本）')
    print()
    print('  样本 %d 句、难句 %d 个 —— 这个规模下 AUC 波动约 ±0.08，' % (len(rows), len(hard)))
    print('  也就是说 0.62 和 0.70 在这个样本量上分不出差别。')
    print('=' * 80)
    return 0


if __name__ == '__main__':
    sys.exit(main())
