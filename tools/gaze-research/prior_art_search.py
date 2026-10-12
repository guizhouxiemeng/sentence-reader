#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
prior_art_search.py — 候选方向的"查重"（GitHub 检索）

为什么需要这一步：上一轮我推荐了"翻页器"，结果发现它烂大街 ——
我跳过了查重直接推荐。这个脚本把查重做成可复现的步骤。

本脚本围绕"基于实测边界（低频、粗瞄准、中央区域、可确认）"筛出的
候选方向，检索 GitHub 上已有的工作，用于判断：
    · 该方向是"产品化"（有人做了 → 需求真实）还是"有新颖性"（少有人做）
    · 已有方案的做法是什么、有没有可利用的缺口

用法： python tools/prior_art_search.py
"""
import json
import sys
import time
import urllib.parse
import urllib.request

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# 候选方向 → 检索词。每个方向给多条查询，避免单词命中偏差。
QUERIES = {
    'A. 免手桌面指针（通用）': [
        'webcam hand gesture mouse pointer control',
        'hands-free pointer webcam MediaPipe',
        'fingertip mouse control webcam',
    ],
    'B. 手部受限者的输入方案': [
        'accessibility hand tracking mouse alternative',
        'assistive input gesture no hands disability',
        'head tracking mouse accessibility',
    ],
    'C. 视线分区 + 手势确认': [
        'gaze zone hand gesture confirmation interaction',
        'gaze gesture hybrid interaction webcam',
        'eye tracking dwell click confirmation',
    ],
    'D. 免手媒体/文档控制': [
        'hands-free media control webcam gesture',
        'gesture page turn webcam',
        'hands free scrolling gesture webcam',
    ],
    'E. 目标尺寸与可用性研究': [
        'target size pointing accuracy study hand tracking',
        'Fitts law hand tracking webcam',
    ],
}


def gh_search(q, sort='stars', per_page=8):
    url = ('https://api.github.com/search/repositories?q=' +
           urllib.parse.quote(q) +
           '&sort=%s&order=desc&per_page=%d' % (sort, per_page))
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/vnd.github+json',
    })
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def main():
    print('=' * 96)
    print('候选方向查重（GitHub 检索）')
    print('=' * 96)
    print('  判读标准：')
    print('    · ★ 高 + 数量多  → 需求真实，但作为项目缺新颖性；作为产品有成熟竞品')
    print('    · ★ 低 + 数量少  → 要么没人需要，要么没人做对（需结合场景判断）')
    print('    · 做法相同       → 不建议重复')
    print('    · 做法不同       → 说明存在未被采用的路径，可能有空间')
    print()

    summary = {}
    for name, queries in QUERIES.items():
        print('─' * 96)
        print(name)
        print('─' * 96)
        seen = {}
        total = 0
        for q in queries:
            try:
                d = gh_search(q)
            except Exception as e:
                print('  查询失败 %-46s %s' % (q[:44], e))
                continue
            total += d.get('total_count', 0)
            for it in d.get('items', []):
                fn = it['full_name']
                if fn not in seen:
                    seen[fn] = (it.get('stargazers_count', 0),
                                (it.get('description') or '')[:70],
                                it.get('language') or '')
            time.sleep(1.2)      # 尊重 API 速率限制
        top = sorted(seen.items(), key=lambda kv: -kv[1][0])[:6]
        print('  命中仓库总数（去重前）: %d　去重后: %d' % (total, len(seen)))
        if not top:
            print('  （无结果）')
        for fn, (stars, desc, lang) in top:
            print('    %-44s ★%-6d %-10s %s' % (fn[:44], stars, lang, desc))
        # 粗判：最高星数与结果数
        maxs = top[0][1][0] if top else 0
        summary[name] = (len(seen), maxs)
        print()

    print('=' * 96)
    print('汇总')
    print('=' * 96)
    print('  %-30s %-14s %-12s %s' % ('方向', '去重结果数', '最高星', '判读'))
    print('  ' + '-' * 90)
    for name, (n, maxs) in summary.items():
        if n == 0:
            verdict = '没找到 —— 需人工确认是否真没人做'
        elif maxs >= 1000:
            verdict = '成熟领域，竞品多；作产品可行，作项目缺新颖性'
        elif maxs >= 100:
            verdict = '有活跃工作；需比较做法差异'
        else:
            verdict = '有零星尝试但无成熟方案 —— 可能是空白，也可能没人需要'
        print('  %-30s %-14d %-12d %s' % (name, n, maxs, verdict))
    return 0


if __name__ == '__main__':
    sys.exit(main())
