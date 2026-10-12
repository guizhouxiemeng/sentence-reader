# -*- coding: utf-8 -*-
"""
verify_all.py —— 交付前的一键校验。**每次改完代码、交给用户测之前都要跑这个。**

为什么需要它：
  我反复出现同一个流程错误 —— 改了 demo/reader_flow.html，
  却忘了同步到 plugin/，于是用户测的扩展还是旧代码，
  报的问题"看起来像是没改"。现场就发生过一次：
  改好了"按词计数"，但插件里还是旧的"按字符计数"，
  用户看到"16 个单词却显示 115 字"。

  这类问题不是代码 bug，是**流程遗漏**，所以用一个脚本兜住。

它做四件事：
  ① 同步 demo/reader_flow.html -> plugin/（含抽出内联脚本）
  ② 检查同步结果一致
  ③ 所有 JS 语法检查
  ④ 跑全部自测（浮层解析 / 推断层 / 阅读单位）
  ⑤ 静态核对跨模块调用与 DOM id

用法：
  python tools/verify_all.py
退出码 0 表示全部通过，可以交付。
"""

import io
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable


def run(cmd, title, cwd=None):
    """跑一个子进程并返回 (ok, output)。"""
    print("\n" + "-" * 74)
    print(title)
    print("-" * 74)
    try:
        p = subprocess.run(cmd, cwd=cwd or ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        ok = p.returncode == 0
        for line in out.strip().split("\n")[-24:]:
            print("  " + line)
        if not out.strip():
            print("  (无输出)")
        return ok, out
    except Exception as e:
        print("  执行失败: %s" % e)
        return False, str(e)


def js_syntax(path):
    """node --check 一个 JS 文件。"""
    try:
        p = subprocess.run(["node", "--check", path], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=60)
        return p.returncode == 0, (p.stderr or "")
    except Exception as e:
        return False, str(e)


def main():
    print("=" * 74)
    print("交付前校验")
    print("=" * 74)

    fails = []

    # ---- ① 同步（这一步最容易被忘，所以放在最前面强制执行）----
    ok, _ = run([PY, "tools/sync_plugin.py"], "① 同步阅读界面到插件")
    if not ok:
        fails.append("同步")

    # ---- ② 一致性 ----
    ok, _ = run([PY, "tools/sync_plugin.py", "--check"], "② 同步一致性")
    if not ok:
        fails.append("一致性")

    # ---- ③ JS 语法 ----
    print("\n" + "-" * 74)
    print("③ JS 语法检查")
    print("-" * 74)
    js_files = [
        "plugin/content.js", "plugin/background.js", "plugin/panel.js",
        "plugin/reader_flow.js", "tools/test-overlay-contract.js", "tools/test-split.js", "tools/test-trust.js", "tools/test-marks.js", "tools/test-export.js", "tools/test-pdfparas.js",
        "tools/check-undeclared.js",
        "tools/test-trigger.js", "tools/test-units.js", "tools/serve.js",
    ]
    for f in js_files:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            print("  -- %s（不存在，跳过）" % f)
            continue
        good, err = js_syntax(p)
        print("  %s %s" % ("OK  " if good else "!!  ", f))
        if not good:
            fails.append("语法:" + f)
            for line in err.strip().split("\n")[:5]:
                print("       " + line)

    # ---- ④ HTML 里的内联脚本语法（网页版）----
    print("\n" + "-" * 74)
    print("④ HTML 内联脚本语法")
    print("-" * 74)
    for html in ["demo/reader_flow.html", "demo/reader.html"]:
        p = os.path.join(ROOT, html)
        if not os.path.exists(p):
            continue
        t = io.open(p, encoding="utf-8").read()
        blocks = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", t, re.S | re.I)
        blocks = [b for b in blocks if b.strip()]
        if not blocks:
            print("  OK   %s（无内联脚本）" % html)
            continue
        tmp = os.path.join(os.environ.get("TEMP", "."), "_vsyn.js")
        allok = True
        for i, b in enumerate(blocks):
            io.open(tmp, "w", encoding="utf-8", newline="").write(b)
            good, err = js_syntax(tmp)
            if not good:
                allok = False
                fails.append("内联语法:" + html)
                print("  !!   %s 第 %d 段" % (html, i + 1))
                for line in err.strip().split("\n")[:4]:
                    print("       " + line)
        if allok:
            print("  OK   %s（%d 段内联脚本）" % (html, len(blocks)))
        try:
            os.remove(tmp)
        except Exception:
            pass

    # ---- ④b Python 工具脚本语法 ----
    #  为什么必须查：我在写工具脚本时反复犯同一个错 ——
    #  Python 字符串里嵌了 ASCII 双引号（中文引号写成英文引号），
    #  导致 SyntaxError。这类错误只要跑一次语法检查就能抓到。
    print("\n" + "-" * 74)
    print("④b Python 工具脚本语法")
    print("-" * 74)
    import ast
    py_files = sorted(f for f in os.listdir(os.path.join(ROOT, "tools"))
                      if f.endswith(".py"))
    for f in py_files:
        path = os.path.join(ROOT, "tools", f)
        try:
            # 用 utf-8-sig 读：带 BOM 的文件用 utf-8 读会把 BOM 当非法字符，
            # 那是假失败（Python 解释器本身能处理 BOM）
            ast.parse(io.open(path, encoding="utf-8-sig").read())
            print("  OK   tools/%s" % f)
        except SyntaxError as e:
            print("  !!   tools/%s  第 %s 行: %s" % (f, e.lineno, e.msg))
            fails.append("py语法:" + f)

    # ---- ⑤ 自测 ----
    for script, title in [
        ("tools/test-units.js", "⑤ 阅读单位计数（中文按字/英文按词）"),
        ("tools/test-trigger.js", "⑥ 推断层判定逻辑"),
        ("tools/test-overlay-contract.js", "⑦ 浮层与消息协议一致性"),
    ("tools/test-split.js", "⑦b 切句规则（小数点/缩写/两份实现一致）"),
    ("tools/test-trust.js", "⑦c 术语来源标记（可信改造）"),
        ("tools/test-marks.js", "⑦e 句子包裹能反复进行（clearMarks 必须真拆）"),
        ("tools/test-export.js", "⑦f 讲解导出为 Markdown（分段/不带按钮文字）"),
        ("tools/test-pdfparas.js", "⑦g PDF 段落识别（缩进/短行/行距）"),
        ("tools/check-undeclared.js", "⑦d 未声明标识符（content.js 被大删过一次）"),
        ("tools/scope-check.js", "⑦d2 参数被注释掉但函数体还在用（让讲解全废过）"),
        ("tools/test-scope-check.js", "⑦d3 检查器自测（阴性+阳性样本）"),
        ("tools/prepare_privacy_site.py --check", "⑩b 隐私政策与 manifest 一致性"),
        ("tools/package.js", "⑨ 打包自检（manifest 引用的文件都在包里）"),
        ("tools/verify-package.js", "⑩c 包内文件与 plugin/ 逐字节一致"),
    ]:
        p = os.path.join(ROOT, script)
        if not os.path.exists(p):
            continue
        ok, out = run(["node", script], title)
        if not ok:
            fails.append(os.path.basename(script))

    # ---- ⑥ 静态核对 ----
    ok, _ = run([PY, "tools/check_html_modules.py", "demo/reader_flow.html"],
                "⑧ 静态核对（跨模块调用 / DOM id）")
    if not ok:
        fails.append("静态核对")

    # ---- 汇总 ----
    print("\n" + "=" * 74)
    if fails:
        print("!! 有 %d 项未通过：" % len(fails))
        for f in fails:
            print("   - " + f)
        print()
        print("修完再交付。特别注意：plugin/ 是否同步（用户测的是插件）。")
        print("=" * 74)
        return 1
    print("全部通过 ✓ 可以交付")
    print()
    print("提醒：plugin/reader_flow.js 已是最新。用户需要到")
    print("      edge://extensions 点【重新加载】才会用到新代码。")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
