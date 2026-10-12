# -*- coding: utf-8 -*-
"""
sync_plugin.py —— 把网页版的阅读界面同步到插件目录，并做插件所需的改写。

为什么需要它：
  阅读界面（切句、高亮、侧栏讲解、统计导出）是一份完整独立的 HTML，
  网页版和插件版【共用同一份实现】。插件必须用扩展自己的源来加载它
  （否则 iframe 的来源会是本地服务器，chrome.* 扩展 API 用不了），
  所以这里把 demo/reader_flow.html 同步成 plugin/reader_flow.html。

改写的内容：
  ① 内联 <script> 抽成外部 reader_flow.js
     MV3 扩展默认 CSP 是 script-src 'self'，**禁止内联脚本**，
     不抽出来的话界面一加载就报
     "Executing inline script violates the following Content Security Policy"，
     整个界面完全不工作。抽成外部文件是最正规的做法
     （比在 manifest 里开 'unsafe-inline' 更安全，商店审核也不会卡）。
  ② 加一行文件头注释，说明这是同步生成的，避免有人直接手改副本。

用法：
  python tools/sync_plugin.py          # 同步
  python tools/sync_plugin.py --check  # 只检查是否一致（不一致返回 1）
"""

import hashlib
import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "demo", "reader_flow.html")
DST = os.path.join(ROOT, "plugin", "reader_flow.html")
DST_JS = os.path.join(ROOT, "plugin", "reader_flow.js")

BANNER = ("<!-- 本文件由 tools/sync_plugin.py 从 demo/reader_flow.html 同步生成。\n"
          "     要改动请改 demo/reader_flow.html，然后重新运行同步脚本。 -->\n")

SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)([^>]*)>(.*?)</script>", re.S | re.I)


# 匹配 IS_EXT 的整段计算：
#     const IS_EXT = <多行表达式，结尾是 })();
#  为什么不用"到第一个分号"：表达式内部（那个 IIFE）自己就带分号，
#  非贪婪匹配会提前截断，只替换掉一半 —— 那比不替换更糟。
IS_EXT_RE = re.compile(r"const IS_EXT = [\s\S]*?\}\)\(\);", re.M)


def force_extension_mode(js):
    """把 IS_EXT 强制成 true。

    为什么要在插件版里强制，而不是让它自己判定：
        独立模式（粘贴文本 / 抓取网址）是给网页版 demo 用的。
        在扩展里它毫无意义 —— 用户在侧栏里没法选页面，
        一旦出现就说明模式判定错了，整个界面等于废掉。

        换句话说，它只是给"判定出错"留了一个【能退化到、但完全没法用】的出口。
        堵死它，这一整类问题就不会再出现，无论根因是什么。

    网页版不受影响：这里只改插件版生成出来的那份 JS。
    """
    replacement = (
        "const IS_EXT = true;   // 插件版强制为扩展模式"
        "（由 tools/sync_plugin.py 注入）\n"
        "  // 这里【故意不保留】原来的判定：独立模式在扩展里没有意义，"
        "留着只是给判定出错留退化出口。"
    )
    new_js, n = IS_EXT_RE.subn(replacement, js, count=1)
    if n == 0:
        raise SystemExit(
            "同步失败：在 demo/reader_flow.html 里找不到 IS_EXT 的计算语句。\n"
            "  插件版需要把它强制成 true（见 force_extension_mode 的说明）。\n"
            "  如果那段代码被重写了，请同步更新 IS_EXT_RE。"
        )
    return new_js


def transform(src_text):
    """返回 (html, js)：把内联脚本抽出来。"""
    def repl(m):
        attrs = m.group(1) or ""
        # module 脚本单独处理：抽出去之后要用 type="module"
        return ""

    # 逐个收集内联脚本
    scripts = []
    def collect(m):
        scripts.append(m.group(2))
        attrs = m.group(1) or ""
        is_module = "module" in attrs
        return ('<script src="reader_flow.js"%s></script>'
                % (' type="module"' if is_module else ''))

    html = SCRIPT_RE.sub(collect, src_text)
    js = "\n\n".join(s.strip() for s in scripts if s.strip())
    # 插件版强制扩展模式 —— 见 force_extension_mode 的说明
    js = force_extension_mode(js)
    return html, js


def digest_text(t):
    return hashlib.sha256(t.encode("utf-8")).hexdigest()


def main():
    check_only = "--check" in sys.argv

    if not os.path.exists(SRC):
        print("源文件不存在: " + SRC)
        return 1

    src_text = io.open(SRC, encoding="utf-8").read()
    html, js = transform(src_text)
    if "sync_plugin.py 从" not in html:
        html = html.replace("<!DOCTYPE html>", "<!DOCTYPE html>\n" + BANNER, 1)

    # 结果检查：插件版必须把 IS_EXT 强制成 true。
    #  上面的 force_extension_mode 只在"找不到那段代码"时报错，
    #  管不了"替换到了别处"或"被后续处理改回去"。
    #  这里直接看生成结果，是"看结果"不是"看动作"。
    if "const IS_EXT = true;" not in js:
        print("同步结果不对：插件版里没有 `const IS_EXT = true;`")
        print("  独立模式在扩展里没有意义，必须强制扩展模式。")
        print("  请检查 tools/sync_plugin.py 里的 IS_EXT_RE 是否还匹配得上。")
        return 1

    if check_only:
        ok = True
        for path, want in ((DST, html), (DST_JS, js)):
            if not os.path.exists(path):
                print("缺少 " + os.path.relpath(path, ROOT) + "（需要同步）")
                ok = False
                continue
            cur = io.open(path, encoding="utf-8").read()
            if cur != want:
                print("不一致: " + os.path.relpath(path, ROOT))
                ok = False
        if ok:
            print("一致：plugin/reader_flow.html 与 reader_flow.js 都是最新的")
            return 0
        print("请运行： python tools/sync_plugin.py")
        return 1

    io.open(DST, "w", encoding="utf-8", newline="").write(html)
    io.open(DST_JS, "w", encoding="utf-8", newline="").write(js)

    print("已同步")
    print("  %-34s %7d 字节" % ("plugin/reader_flow.html", os.path.getsize(DST)))
    print("  %-34s %7d 字节" % ("plugin/reader_flow.js", os.path.getsize(DST_JS)))
    print()
    print("说明：内联脚本已被抽成 reader_flow.js —— MV3 扩展的 CSP 默认")
    print("      禁止内联脚本（script-src 'self'），不抽出来的话界面完全无法运行。")
    print()
    print("接下来：到扩展管理页点【重新加载】，然后打开文章页点扩展图标。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
