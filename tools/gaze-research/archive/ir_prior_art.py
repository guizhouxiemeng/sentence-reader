#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ir_prior_art.py — 红外眼动方案的开源现状检索

目的：在动手买元件前，先确认"用红外摄像头 + 近眼布置做眼动追踪"
这条路上已有哪些开源工作可复用、哪些坑已经有人踩过。

检索维度：
  ① 完整的 DIY 眼动追踪项目（可直接抄的）
  ② 亮瞳 / 暗瞳检测（核心算法）
  ③ 红外模组改造（拆滤片、加 LED）
  ④ 瞳孔检测与视线估计（算法层）
  ⑤ 近眼 / 头戴式眼动装置（形态参考）

用法： python tools/ir_prior_art.py
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

GROUPS = {
    '① DIY 眼动追踪（可复用整体方案）': [
        'DIY eye tracker webcam',
        'open source eye tracking gaze estimation',
        'eye tracking head mounted camera',
    ],
    '② 亮瞳 / 暗瞳检测（核心算法）': [
        'bright pupil eye detection infrared',
        'dark pupil eye tracking',
        'pupil detection infrared camera',
    ],
    '③ 红外模组改造 / 近红外成像': [
        'infrared camera raspberry pi NoIR eye',
        'near infrared imaging face eye',
        'webcam IR filter removal eye tracking',
    ],
    '④ 瞳孔中心与角膜反光（glint）算法': [
        'pupil center corneal reflection',
        'glint detection gaze estimation',
        'PCCR eye tracking',
    ],
    '⑤ 视线估计算法与数据集': [
        'gaze estimation deep learning dataset',
        'appearance based gaze estimation',
        'model based gaze estimation 3D eye',
    ],
}


def gh_search(q, per_page=6, sort='stars'):
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
    print('红外眼动方案：开源现状检索')
    print('=' * 96)
    print('  判读重点：不是看星数高低，而是看【有没有可直接复用的实现】，')
    print('  以及【已有方案用的硬件形态】，据此决定买什么元件。')
    print()

    all_seen = {}
    for name, queries in GROUPS.items():
        print('─' * 96)
        print(name)
        print('─' * 96)
        seen = {}
        for q in queries:
            try:
                d = gh_search(q)
            except Exception as e:
                print('  查询失败 %-44s %s' % (q[:42], str(e)[:40]))
                time.sleep(20)
                continue
            for it in d.get('items', []):
                fn = it['full_name']
                if fn in seen:
                    continue
                seen[fn] = (it.get('stargazers_count', 0),
                            (it.get('description') or '')[:76],
                            it.get('language') or '')
                all_seen[fn] = seen[fn]
            time.sleep(9)          # 匿名检索限速 10 次/分钟，留足余量
        top = sorted(seen.items(), key=lambda kv: -kv[1][0])
        if not top:
            print('  （无结果）')
        for fn, (stars, desc, lang) in top[:8]:
            print('    %-44s ★%-6d %-11s %s' % (fn[:44], stars, lang, desc))
        print('  本组去重仓库数: %d' % len(seen))
        print()

    print('=' * 96)
    print('汇总：最值得看的仓库（按星数）')
    print('=' * 96)
    top_all = sorted(all_seen.items(), key=lambda kv: -kv[1][0])[:15]
    for fn, (stars, desc, lang) in top_all:
        print('  %-46s ★%-6d %-11s' % (fn[:46], stars, lang))
        print('      %s' % desc)
    print()
    print('  下一步：对上述前 3~5 个仓库用 repo_summary 逐个细看它们的')
    print('  硬件形态（相机型号、LED 布置、滤片处理），据此定元件清单。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
