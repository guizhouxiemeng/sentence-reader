# -*- coding: utf-8 -*-
'''
heuristic_value.py —— 核算「只用句子长度做提前准备」的实际覆盖率与代价。

背景（三轮实测的结论）：
    句长 units        AUC 0.64
    停留 dwell        AUC 0.63     （与句长相关 r=0.77）
    ratio             AUC 0.53     （无用）
    三者组合          AUC 0.63     （没有超过单信号）

  也就是说：**整套行为推断，效果与"数句子长度"这个一行代码的启发式相当。**

  那么值不值得继续维护复杂推断？取决于"够不够用"。
  这个脚本把"够不够用"算成具体数字：覆盖率 + 误报代价。

用法：python tools/heuristic_value.py

引号风格：本文件所有 Python 字符串一律用单引号或三单引号，
中文里的强调用「」。原因是之前反复在双引号字符串里嵌 ASCII 双引号
导致 SyntaxError（犯了四次），verify_all.py 现在会检查 Python 语法。
'''

import csv
import io
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

# 一次讲解调用的大致成本（元）。
# DeepSeek 一类模型：约 700 token 输出 + 300 token 输入，量级在千分之几元。
COST_PER_CALL = 0.002


def units_of(text):
    t = text or ''
    c = len(CJK.findall(t))
    rest = CJK.sub(' ', t)
    w = [x for x in WORD.findall(rest) if re.search(r'[A-Za-z]', x)]
    return c + len(w)


def load():
    rows = []
    for fn in FILES:
        p = fn if os.path.isabs(fn) else os.path.join(ROOT, fn)
        if not os.path.exists(p):
            continue
        src = os.path.basename(p)
        with io.open(p, encoding='utf-8-sig', newline='') as f:
            for r in csv.reader(f):
                if not r or r[0].startswith('#'):
                    continue
                if r[1] == '类型':
                    break
                if r[1] in ('求助', '标注'):
                    continue
                if len(r) < 9:
                    continue
                try:
                    t = int(r[7]) if r[7] not in ('', None) else None
                    if t is None:
                        continue
                    rows.append({
                        'truth': t,
                        'units': units_of(r[8]),
                        'dwell': float(r[3]) if r[3] else 0.0,
                        'src': src,
                    })
                except (ValueError, IndexError):
                    continue
    return rows


def main():
    rows = load()
    if not rows:
        print('没读到标注数据')
        return 1

    hard = [r for r in rows if r['truth'] == 1]
    srt = sorted(rows, key=lambda r: -r['units'])

    print('=' * 78)
    print('实用视角：只按句子长度提前准备讲解，覆盖率如何')
    print('=' * 78)
    print('  样本 %d 句，其中难句 %d 个' % (len(rows), len(hard)))
    print()
    print('  策略：把最长的前 X% 句子提前准备好讲解')
    print()
    print('  %-10s %9s %8s %9s %11s' % ('准备比例', '覆盖难句', '召回', '误报数', '调用次数'))
    print('  ' + '-' * 56)

    for frac in (0.10, 0.20, 0.30, 0.40, 0.50, 0.70):
        n = max(1, int(round(len(srt) * frac)))
        sel = srt[:n]
        tp = sum(1 for r in sel if r['truth'] == 1)
        fp = n - tp
        rec = (tp / len(hard) * 100) if hard else 0.0
        print('  %-10s %9d %7.0f%% %9d %11d'
              % ('%.0f%%' % (frac * 100), tp, rec, fp, n))

    print()
    print('=' * 78)
    print('代价核算 —— 这才是判断「够不够用」的关键')
    print('=' * 78)
    print('  误报的代价 = 白调用一次 LLM（约 %.3f 元/次）' % COST_PER_CALL)
    print('  漏报的代价 = 用户按空格时现算，等 1~2 秒')
    print()
    for frac in (0.20, 0.30, 0.50):
        n = max(1, int(round(len(srt) * frac)))
        sel = srt[:n]
        tp = sum(1 for r in sel if r['truth'] == 1)
        fp = n - tp
        rec = (tp / len(hard) * 100) if hard else 0.0
        print('  准备前 %2.0f%%（%3d 句）：覆盖 %2.0f%% 的难句　误报 %2d 条　白花 %.2f 元'
              % (frac * 100, n, rec, fp, fp * COST_PER_CALL))

    print()
    print('=' * 78)
    print('对照：行为推断的同样指标')
    print('=' * 78)
    print('  行为推断（停留 + 回看）：')
    print('    · AUC 与句长相当（0.63 vs 0.64），组合后无提升')
    print('    · 需要先读若干句建立基线（冷启动期判定不可用）')
    print('    · 自动推进模式下信号被系统配速抹平（ratio 恒定）')
    print('    · 用户难以理解"为什么这句被准备了"')
    print('  句长启发式：')
    print('    · 同样 AUC，零延迟，不用基线，第一句就能用')
    print('    · 用户一看就懂（"长句更容易难"）')
    print()
    print('=' * 78)
    print('结论')
    print('=' * 78)
    print('  在【静默准备】这个用法下，句子长度启发式与整套行为推断等效。')
    print('  所以：')
    print('    · 若目标是做一个能用的工具    -> 用启发式，删掉推断层')
    print('    · 若目标是研究贡献            -> "行为信号相对句长无增量"')
    print('                                     这个结论本身就是产出')
    print()
    print('  注意：这不代表"逐句判难"可行 —— AUC 0.63 仍是弱信号。')
    print('        它只说明【行为信号没有比数长度更强】。')
    print('=' * 78)
    return 0


if __name__ == '__main__':
    sys.exit(main())
