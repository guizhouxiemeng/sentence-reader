# -*- coding: utf-8 -*-
"""
eval_trigger.py —— 用真实阅读数据评估推断层的准确率。

这是整个项目**唯一还没做过的端到端验证**：
  阈值逻辑用合成数据测过（8/8），但"在真实阅读中判得准不准"从来没测过。
  而"该不该讲解"正是这套东西的核心难点 —— 判错了要么打扰用户（误报），
  要么形同虚设（漏报）。

流程：
  ① 打开插件，正常读几篇文章
  ② 读到"确实卡住"的句子按 M 标注；读到明显顺畅的句子按 N 标注
  ③ 点【导出】得到 CSV
  ④ python tools/eval_trigger.py reading_flow_xxx.csv

输出：
  混淆矩阵 + 精确率 / 召回率 / F1 + 阈值扫描（看调哪个阈值更合适）

用法：
  python tools/eval_trigger.py <csv路径>
  python tools/eval_trigger.py <csv路径> --scan     # 额外做阈值扫描
"""

import csv
import io
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def load(path):
    """读导出 CSV。前一段是每句一行，后面接事件段。"""
    rows = []
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        rd = csv.reader(f)
        header = next(rd, None)
        for r in rd:
            if not r or len(r) < 9:
                continue
            if r[1] == '类型':          # 事件段的表头
                break
            if r[1] == '求助' or r[1] == '标注':
                continue
            try:
                rows.append({
                    'idx': int(r[0]),
                    'pred': (r[1] or '').strip(),
                    'ratio': float(r[2]) if r[2] else None,
                    'dwell': float(r[3]) if r[3] else 0.0,
                    'backs': int(r[4]) if r[4] else 0,
                    'visits': int(r[5]) if r[5] else 0,
                    'units': int(r[6]) if r[6] else 0,
                    'truth': int(r[7]) if r[7] not in ('', None) else None,
                    'text': r[8] if len(r) > 8 else '',
                })
            except (ValueError, IndexError):
                continue
    return rows


def confusion(rows, pred_fn):
    tp = fp = fn = tn = 0
    for r in rows:
        if r['truth'] is None:
            continue
        pred = pred_fn(r)
        if r['truth'] == 1 and pred:
            tp += 1
        elif r['truth'] == 0 and pred:
            fp += 1
        elif r['truth'] == 1 and not pred:
            fn += 1
        else:
            tn += 1
    return tp, fp, fn, tn


def metrics(tp, fp, fn, tn):
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    acc = (tp + tn) / (tp + fp + fn + tn) if (tp + fp + fn + tn) else 0.0
    return prec, rec, f1, acc


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    scan = '--scan' in sys.argv
    if not args:
        print("用法: python tools/eval_trigger.py <csv路径> [--scan]")
        return 1
    path = args[0]
    if not os.path.exists(path):
        print("文件不存在: " + path)
        return 1

    rows = load(path)
    if not rows:
        print("没读到句子数据 —— 确认 CSV 是插件【导出】按钮生成的")
        return 1

    labeled = [r for r in rows if r['truth'] is not None]
    hard = [r for r in labeled if r['truth'] == 1]
    easy = [r for r in labeled if r['truth'] == 0]

    print("=" * 78)
    print("推断层评估")
    print("=" * 78)
    print("  总句数        %d" % len(rows))
    print("  已标注        %d（%.0f%%）" % (len(labeled),
          100.0 * len(labeled) / len(rows) if rows else 0))
    print("    其中真值=难  %d" % len(hard))
    print("    其中真值=顺  %d" % len(easy))
    if len(labeled) < 15:
        print()
        print("  !! 标注太少（<15），结论不可靠。建议至少标注 30 句、")
        print("     并且「确实难」至少 8 句 —— 否则召回率没有统计意义。")
    print()

    if not labeled:
        print("没有标注数据，无法评估。请在阅读时按 M / N 标注。")
        return 1

    # ---- 当前系统判定 ----
    pred_blocked = lambda r: (r['pred'] == 'blocked') or (r['backs'] >= 2)
    tp, fp, fn, tn = confusion(labeled, pred_blocked)
    prec, rec, f1, acc = metrics(tp, fp, fn, tn)

    print("=" * 78)
    print("① 当前判定（pred=blocked 或 退回>=2）")
    print("=" * 78)
    print("                   预测=受阻   预测=正常")
    print("  真值=确实难        %-10d %d   (漏报 %d)" % (tp, fn, fn))
    print("  真值=顺畅          %-10d %d   (误报 %d)" % (fp, tn, fp))
    print()
    print("  精确率 %.2f   召回率 %.2f   F1 %.2f   准确率 %.2f"
          % (prec, rec, f1, acc))
    print()
    if prec and rec:
        print("  怎么读：精确率 = 系统说「受阻」时有多准；")
        print("          召回率 = 真的卡住时系统抓到了多少。")
        if prec < 0.5:
            print("  -> 精确率偏低：误报多，会把正常阅读判成受阻，打扰用户。")
        if rec < 0.5:
            print("  -> 召回率偏低：漏报多，用户真卡住时系统没反应。")

    # ---- 只用退回次数 ----
    print()
    print("=" * 78)
    print("② 只用【退回次数】判定（自动推进模式下的主信号）")
    print("=" * 78)
    for k in (1, 2, 3):
        tp2, fp2, fn2, tn2 = confusion(labeled, lambda r, k=k: r['backs'] >= k)
        p2, r2, f2, a2 = metrics(tp2, fp2, fn2, tn2)
        print("  退回 >= %d   精确 %.2f  召回 %.2f  F1 %.2f  准确 %.2f"
              % (k, p2, r2, f2, a2))

    # ---- 阈值扫描 ----
    if scan:
        print()
        print("=" * 78)
        print("③ 阈值扫描：ratio 阈值取多少最好")
        print("=" * 78)
        best = None
        for t100 in range(80, 401, 20):
            t = t100 / 100.0
            tp3, fp3, fn3, tn3 = confusion(
                labeled, lambda r, t=t: (r['ratio'] is not None and r['ratio'] > t))
            p3, r3, f3, _ = metrics(tp3, fp3, fn3, tn3)
            mark = ''
            if best is None or f3 > best[1]:
                best = (t, f3)
                mark = '  <- 目前最好'
            print("  ratio > %.2f   精确 %.2f  召回 %.2f  F1 %.2f%s"
                  % (t, p3, r3, f3, mark))
        if best:
            print()
            print("  F1 最高：ratio > %.2f（F1=%.2f）" % best)

    # ---- 看几个具体例子（便于人工判断） ----
    print()
    print("=" * 78)
    print("④ 几个判错的例子（最重要的诊断信息）")
    print("=" * 78)
    fp_list = [r for r in labeled if r['truth'] == 0 and pred_blocked(r)]
    fn_list = [r for r in labeled if r['truth'] == 1 and not pred_blocked(r)]
    if fp_list:
        print("\n  误报（系统说受阻，其实顺畅）—— 最常见的原因是句子里有生僻字/专有名词:")
        for r in fp_list[:5]:
            print("    第%d句 ratio=%s 退回%d 单位%d  %s"
                  % (r['idx'], r['ratio'], r['backs'], r['units'], r['text'][:52]))
    if fn_list:
        print("\n  漏报（真的难，系统没抓到）—— 可能是“读得慢但没有回看”:")
        for r in fn_list[:5]:
            print("    第%d句 ratio=%s 退回%d 单位%d  %s"
                  % (r['idx'], r['ratio'], r['backs'], r['units'], r['text'][:52]))
    if not fp_list and not fn_list:
        print("\n  没有判错的例子 —— 当前阈值在这份数据上完全正确。")

    print()
    print("=" * 78)
    print("注意：样本量小的时候，精确率/召回率波动很大。")
    print("      建议攒够 3 篇以上、标注 50+ 句再看结论。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
