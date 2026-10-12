# -*- coding: utf-8 -*-
r'''
prepare_privacy_site.py —— 把隐私政策站点里的占位符换成真实联系方式。

为什么要有这一步：
    政策页面里的联系方式不能是假的。而我又不知道用户的仓库地址
    —— 所以先留占位符，发布前用一个命令填掉。

    同时它会做两件容易忘的事：
      ① 检查还有没有残留的 __占位符__（漏一个就会挂到网上）
      ② 顺手核对政策里的权限说明与 manifest.json 是否一致
         —— 商店要求"政策内容与实际行为一致"，这一条被拒过不少人
      ③ 打印发布地址，省得自己拼

用法：
    python tools/prepare_privacy_site.py --repo https://github.com/你/仓库
    python tools/prepare_privacy_site.py --email you@example.com
    python tools/prepare_privacy_site.py --check        # 只检查，不改
'''

import io
import json
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "store", "privacy-site", "index.html")
# 已发布的地址（发布后填在这里，方便工具提示"线上是不是这一版"）
PUBLISHED_URL = "https://guizhouxiemeng.github.io/sentence-reader-privacy/"
MANIFEST = os.path.join(ROOT, "plugin", "manifest.json")

# 政策里声明的权限 -> 用来和 manifest 对照
CLAIMED_PERMISSIONS = ["scripting", "tabs", "activeTab", "sidePanel"]
# 明确声明"没有申请"的权限
CLAIMED_ABSENT = ["storage", "history", "bookmarks", "cookies", "webRequest", "downloads"]


def fail(msg):
    print("  ✗ " + msg)
    return 1


def main():
    args = sys.argv[1:]
    check_only = "--check" in args

    repo = None
    email = None
    for i, a in enumerate(args):
        if a == "--repo" and i + 1 < len(args):
            repo = args[i + 1]
        if a == "--email" and i + 1 < len(args):
            email = args[i + 1]

    if not os.path.exists(SITE):
        return fail("找不到 " + os.path.relpath(SITE, ROOT))

    html = io.open(SITE, encoding="utf-8").read()

    # ---------------------------------------------------------------- 权限一致性
    print("=" * 70)
    print("隐私政策站点检查")
    print("=" * 70)
    print()

    rc = 0
    if os.path.exists(MANIFEST):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        perms = set(m.get("permissions") or [])
        print("  manifest 声明的权限：")
        for p in sorted(perms):
            mark = "  " if p in CLAIMED_PERMISSIONS else "！"
            print("    %s %s%s" % (mark, p, "" if p in CLAIMED_PERMISSIONS else "   <- 政策里没写"))
            if p not in CLAIMED_PERMISSIONS:
                rc = 1
        print()
        # 政策说"没有申请"的，manifest 里确实不能有
        extra = perms & set(CLAIMED_ABSENT)
        if extra:
            print("  ✗ 政策里说「没有申请」，但 manifest 里有：%s" % ", ".join(sorted(extra)))
            print("    （商店要求政策内容与实际行为一致，这一条会直接被拒）")
            rc = 1
        else:
            print("  ✓ 政策里声明「没有申请」的权限，manifest 里确实没有")
        print()
    else:
        print("  ！ 找不到 manifest.json，跳过权限一致性检查")
        print()

    # ---------------------------------------------------------------- 占位符
    placeholders = sorted(set(re.findall(r"__[A-Z_]+__", html)))
    if placeholders:
        print("  还有占位符没替换：%s" % ", ".join(placeholders))
    else:
        print("  ✓ 没有残留的占位符")

    if check_only:
        print()
        return rc

    # ---------------------------------------------------------------- 替换
    if repo or email:
        if email and not repo:
            url = "mailto:" + email
            text = email
        else:
            url = repo.rstrip("/") + "/issues"
            text = "该项目的 issue 页面"
        html = html.replace("__CONTACT_URL__", url).replace("__CONTACT_TEXT__", text)
        io.open(SITE, "w", encoding="utf-8", newline="").write(html)
        print()
        print("  已填入联系方式：")
        print("    链接  " + url)
        print("    文字  " + text)
        left = sorted(set(re.findall(r"__[A-Z_]+__", html)))
        if left:
            print("  ！ 还有占位符：%s" % ", ".join(left))
            rc = 1
        else:
            print("  ✓ 占位符已全部替换")
    else:
        print()
        print("  没有给 --repo 或 --email，占位符保持原样。")
        print("  发布前请跑一次：")
        print("    python tools/prepare_privacy_site.py --repo https://github.com/你/仓库")

    # ---------------------------------------------------------------- 发布地址
    print()
    print("  发布方式（详见 store/privacy-site/README.md）：")
    print("    ① 建一个公开仓库，把 store/privacy-site/ 里的内容传到根目录")
    print("       （index.html 和 .nojekyll 都要传，且不能套一层文件夹）")
    print("    ② Settings -> Pages -> Source 选 Deploy from a branch")
    print("       Branch 选 main，目录选 / (root)")
    if repo:
        name = repo.rstrip("/").split("/")[-1]
        user = repo.rstrip("/").split("/")[-2] if "/" in repo.rstrip("/") else "你的用户名"
        print("    ③ 地址形如 https://%s.github.io/<隐私仓库名>/" % user)
        print("       （建议单独建仓库，不要和扩展代码仓库 %s 混在一起）" % name)
    else:
        print("    ③ 地址形如 https://<用户名>.github.io/<隐私仓库名>/")
    print()
    if PUBLISHED_URL:
        print("  隐私政策已发布：" + PUBLISHED_URL)
        print("  内容有改动的话，记得重新上传 index.html。")
    else:
        print("  填进商店表单的「隐私政策网址」即可。")
    print()

    return rc


if __name__ == "__main__":
    sys.exit(main())
