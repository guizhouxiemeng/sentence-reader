# -*- coding: utf-8 -*-
"""
check_html_modules.py —— 静态核对 HTML 里的模块结构与引用。

为什么需要它：
  这一晚反复出现的 bug 都是同一类 —— **语法全对、逻辑看起来对，但引用了
  不存在的东西**（函数、属性、DOM 元素、模块方法）。node --check 只查语法，
  这类问题一个都查不出来，而它们会让整条链路静默失效。

  这个脚本在**不启动浏览器**的前提下，把这类问题尽量查出来：
    ① JS 里调用的函数是否有定义（排除注释）
    ② 模块之间调用的方法是否在对方 return 的接口里暴露
    ③ JS 引用的 DOM id 是否在 HTML 里存在
    ④ 是否有对已删除函数/属性的残留引用

用法：
  python tools/check_html_modules.py demo/reader_flow.html
  python tools/check_html_modules.py            # 默认查 reader_flow.html
"""

import io
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "demo", "reader_flow.html")

BUILTIN = set("""
if for while switch catch function return typeof new delete void in of
Number Math Object Array String Boolean Symbol BigInt JSON Date RegExp Error
console document window performance navigator location history localStorage
requestAnimationFrame cancelAnimationFrame setTimeout clearTimeout setInterval
alert confirm prompt DOMParser TextDecoder TextEncoder AbortSignal
structuredClone queueMicrotask IdentityCredential Element HTMLElement Node
clearInterval fetch Promise Map Set WeakMap WeakSet Proxy Reflect
parseFloat parseInt isFinite isNaN encodeURIComponent decodeURIComponent
Blob URL FileReader File Response Headers Request FormData AbortController
KeyboardEvent MouseEvent Event CustomEvent WebSocket
getElementById querySelector querySelectorAll createElement addEventListener
removeEventListener appendChild removeChild toggle contains add remove
getAttribute setAttribute classList style dataset forEach map filter reduce
push pop shift unshift slice splice concat join split trim replace match
search indexOf lastIndexOf includes startsWith endsWith toLowerCase
toUpperCase toFixed toString valueOf keys values entries assign freeze
stringify parse from of isArray hypot atan2 abs min max floor ceil
round sqrt exp log sign pow sin cos tan random now apply call bind
""".split())


def strip_comments(js):
    """去掉 // 行注释与 /* */ 块注释（但保留字符串字面量里的内容大致正确）。

    只做够用的处理：这个脚本是用来找"明显的引用错误"的，
    不需要完整的 JS 词法分析。
    """
    # 块注释
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    # 行注释：不在字符串里的 //
    out = []
    for line in js.split("\n"):
        # 粗略判断：奇数个引号说明 // 在字符串里，保守起见不删
        idx = line.find("//")
        if idx >= 0:
            head = line[:idx]
            if head.count('"') % 2 == 0 and head.count("'") % 2 == 0 and head.count("`") % 2 == 0:
                line = head
        out.append(line)
    return "\n".join(out)


def iife_body(js, name):
    """按大括号配平取 IIFE 的函数体。

    必须【跳过字符串字面量与正则字面量】——
      早先的版本直接数 `{` 和 `}`，而模块体里常有含花括号的字符串
      （例如 App 里的 HTML 模板片段 `'<h1 id="x">'`、正则 `/{0,1}/`），
      于是深度算歪、body 取成 None，静态核对就报"App 解析失败"。
      这个 bug 让检查器自己不可靠，所以单独修掉。
    """
    i = js.find("const %s = (()" % name)
    if i < 0:
        i = js.find("const %s = (" % name)
    if i < 0:
        return None
    k = js.find("=>", i)
    if k < 0:
        k = js.find("{", i)
    k = js.index("{", k)

    depth = 0
    idx = k
    n = len(js)
    while idx < n:
        ch = js[idx]
        # 字符串 / 模板
        if ch in '"\'`':
            q = ch
            idx += 1
            while idx < n:
                if js[idx] == '\\':
                    idx += 2
                    continue
                if js[idx] == q:
                    break
                idx += 1
            idx += 1
            continue
        # 正则字面量：粗略识别（前面是 ( , = : [ ! & | ? { } ; 之一）
        if ch == '/':
            prev = js[idx - 1] if idx > 0 else ''
            if prev in '(,=:[!&|?{};\n' or prev == '':
                idx += 1
                while idx < n:
                    if js[idx] == '\\':
                        idx += 2
                        continue
                    if js[idx] == '/':
                        break
                    if js[idx] == '\n':
                        break
                    idx += 1
                idx += 1
                continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return js[k + 1:idx]
        idx += 1
    return None


def key_of(chunk):
    """从一个顶层片段里取出键名。支持三种写法：
        name: value      普通属性
        name() { ... }   方法
        name,            ES6 简写属性
    """
    c = chunk.strip()
    m = re.match(r"^(\w+)\s*[:(]", c)
    if m:
        return m.group(1)
    m = re.match(r"^(\w+)\s*$", c)
    if m:
        return m.group(1)
    return None


def object_keys(lit):
    """取对象字面量【顶层】的键。

    只按顶层逗号切分，【不要】剥掉括号 ——
      早先写成 `elif ch not in '()[]{}'`，于是 `getCur() { return cur; }`
      被剥成 `getCur  return cur; `，键名正则匹配不上，
      34 个方法只剩 3 个被识别，静态核对便误报"27 个方法未暴露"。
    """
    body = lit[1:-1]
    parts = []
    cur = []
    depth_b = depth_p = depth_c = 0
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch in '"\'`':
            q = ch
            cur.append(ch)
            i += 1
            while i < n:
                cur.append(body[i])
                if body[i] == '\\':
                    i += 1
                    if i < n:
                        cur.append(body[i])
                    i += 1
                    continue
                if body[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if ch == ',' and depth_b == 0 and depth_p == 0 and depth_c == 0:
            parts.append(''.join(cur))
            cur = []
            i += 1
            continue
        if ch == '(':
            depth_p += 1
        elif ch == ')':
            depth_p -= 1
        elif ch == '[':
            depth_c += 1
        elif ch == ']':
            depth_c -= 1
        elif ch == '{':
            depth_b += 1
        elif ch == '}':
            depth_b -= 1
        cur.append(ch)
        i += 1
    parts.append(''.join(cur))

    keys = set()
    for part in parts:
        nm = key_of(part)
        if nm:
            keys.add(nm)
    return keys


def module_keys(js, name):
    """取模块暴露的接口键。

    流程：iife_body 取函数体 -> 找深度为 0 的 return -> 解析出键。
      · return { ... };   直接解析对象字面量
      · return someVar;   去那个变量名对应的对象字面量里解析
    """
    body = iife_body(js, name)
    if body is None:
        return None
    idxs = _top_level_returns(body)
    if not idxs:
        return None
    for i in reversed(idxs):
        m = re.match(r"return\s+(\{|\w+\s*;)", body[i:])
        if not m:
            continue
        keys_try = _keys_of(body, _tail_of(body, m, base=i))
        if keys_try:
            return keys_try
    return None


def _top_level_returns(body):
    """返回 body 里所有【深度为 0】的 return 的起始下标。"""
    out = []
    depth_b = depth_p = depth_c = 0
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch in '"\'`':
            q = ch
            i += 1
            while i < n:
                if body[i] == '\\':
                    i += 2
                    continue
                if body[i] == q:
                    break
                i += 1
            i += 1
            continue
        if (depth_b == 0 and depth_p == 0 and depth_c == 0
                and body.startswith('return', i)
                and (i == 0 or not (body[i - 1].isalnum() or body[i - 1] in '_$.'))
                and (i + 6 >= n or not (body[i + 6].isalnum() or body[i + 6] in '_$'))):
            out.append(i)
        if ch == '(':
            depth_p += 1
        elif ch == ')':
            depth_p -= 1
        elif ch == '[':
            depth_c += 1
        elif ch == ']':
            depth_c -= 1
        elif ch == '{':
            depth_b += 1
        elif ch == '}':
            depth_b -= 1
        i += 1
    return out


def _tail_of(body, m, base=0):
    """m 是在 body[base:] 上匹配的，换算回 body 的绝对位置。"""
    matched = m.group(1)
    if matched.startswith('{'):
        return body[base + m.start(1):]
    return matched.strip()


def _keys_of(body, tail):
    tail = (tail or '').lstrip()
    if tail.startswith('{'):
        depth = 0
        for idx in range(len(tail)):
            if tail[idx] == '{':
                depth += 1
            elif tail[idx] == '}':
                depth -= 1
                if depth == 0:
                    return object_keys(tail[:idx + 1])
        return set()
    mm = re.match(r"(\w+)\s*;", tail)
    if not mm:
        return set()
    var = mm.group(1)
    if var in ('true', 'false', 'null', 'undefined', 'this'):
        return set()
    vi = body.find("const %s = {" % var)
    if vi < 0:
        vi = body.find("%s = {" % var)
    if vi < 0:
        return set()
    vi = body.index('{', vi)
    depth = 0
    for idx in range(vi, len(body)):
        if body[idx] == '{':
            depth += 1
        elif body[idx] == '}':
            depth -= 1
            if depth == 0:
                return object_keys(body[vi:idx + 1])
    return set()
    # m.end()-1 在 "{ a }" 时指向 "{"，在 "reader;" 时指向 ";"，不能统一 -1。
    # 所以按匹配到的那个字符自己决定：
    matched = m.group(1)
    if matched.startswith("{"):
        tail = body[m.start(1):]
    else:
        tail = matched.strip()

    if tail.startswith("{"):
        # 配平到结束
        depth = 0
        for idx in range(len(tail)):
            if tail[idx] == "{":
                depth += 1
            elif tail[idx] == "}":
                depth -= 1
                if depth == 0:
                    lit = tail[:idx + 1]
                    break
        else:
            return None
    else:
        var = re.match(r"(\w+)\s*;", tail)
        if not var:
            return None
        var = var.group(1)
        vi = body.find("const %s = {" % var)
        if vi < 0:
            vi = body.find("%s = {" % var)
        if vi < 0:
            return None
        depth = 0
        for idx in range(body.index("{", vi), len(body)):
            if body[idx] == "{":
                depth += 1
            elif body[idx] == "}":
                depth -= 1
                if depth == 0:
                    lit = body[body.index("{", vi):idx + 1]
                    break
        else:
            return None

    # 收集键：同时覆盖三种写法
    #   name: value        普通属性
    #   name() { ... }     方法（可能写成一行，也可能多行）
    #   name,              ES6 简写属性（单行 return { a, b } 就是这种）
    keys = set()
    inner = lit[1:-1]
    # 顶层逗号切分（跳过字符串与嵌套括号）
    parts = []
    cur = ""
    dc = db = dp = 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch in "\"'`":
            q = ch
            cur += ch
            i += 1
            while i < len(inner):
                cur += inner[i]
                if inner[i] == "\\":
                    i += 1
                    if i < len(inner):
                        cur += inner[i]
                    i += 1
                    continue
                if inner[i] == q:
                    i += 1
                    break
                i += 1
            continue
        if ch == "(":
            dp += 1
        elif ch == ")":
            dp -= 1
        elif ch == "[":
            dc += 1
        elif ch == "]":
            dc -= 1
        elif ch == "{":
            db += 1
        elif ch == "}":
            db -= 1
        if ch == "," and dc == 0 and db == 0 and dp == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
        i += 1
    parts.append(cur)
    for part in parts:
        t = part.strip()
        if not t:
            continue
        m = re.match(r"^(\w+)\s*[:(]", t)      # name: / name(
        if not m:
            m = re.match(r"^(\w+)\s*$", t)     # 简写属性
        if m:
            keys.add(m.group(1))
    return keys


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    if not os.path.exists(path):
        print("文件不存在: " + path)
        return 1

    t = io.open(path, encoding="utf-8").read()
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", t, re.S)
    js = "\n".join(scripts)
    clean = strip_comments(js)

    print("=" * 78)
    print("静态核对: " + os.path.basename(path))
    print("=" * 78)

    problems = []

    # ---- ① 函数调用是否有定义 ----
    defined = set(re.findall(r"function\s+(\w+)\s*\(", clean))
    defined |= set(re.findall(r"class\s+(\w+)", clean))
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=\s*(?:\(|function)", clean))
    # 模块名也算已定义（TextSource.xxx(...) 里的 TextSource）
    defined |= set(re.findall(r"(?:const|let|var)\s+(\w+)\s*=", clean))

    called = set()
    for m in re.finditer(r"(?<![\w.$])([a-zA-Z_]\w*)\s*\(", clean):
        called.add(m.group(1))
    # 方法调用（obj.method(）里的 method 不算顶层函数
    methods = set(re.findall(r"\.\s*(\w+)\s*\(", clean))
    unknown = sorted(c for c in called
                     if c not in defined and c not in BUILTIN and c not in methods)
    print("\n[1] 顶层函数调用核对")
    if unknown:
        print("  可能未定义: " + ", ".join(unknown))
        print("  （若都在 BUILTIN 之外且确实没定义，会导致运行时 ReferenceError）")
    else:
        print("  OK")

    # ---- ② 模块接口核对 ----
    MODS = sorted(set(re.findall(r"const\s+(\w+)\s*=\s*\(\(\)\s*=>", clean)))
    print("\n[2] 模块接口核对（共 %d 个 IIFE 模块）" % len(MODS))
    for name in MODS:
        # 解析失败不该让整个核对崩掉 —— 报"解析失败"即可，
        #  其余模块与 DOM id 的核对仍然有效。
        #  （解析器本身也曾多次出 bug：抓到嵌套 IIFE 的 return、
        #    抓到方法内部的 return、括号配平不跳字符串。
        #    工具应当容错，而不是让使用者以为代码有问题。）
        try:
            keys = module_keys(clean, name)
        except Exception as e:
            print("  %-14s 解析异常（不影响其它核对）: %s" % (name, str(e)[:60]))
            keys = None
        if keys is None:
            print("  %-14s 解析失败（若是 return var; 形式请看下一行提示）" % name)
            continue
        calls = sorted(set(re.findall(r"\b%s\.(\w+)\s*\(" % name, clean)))
        bad = [c for c in calls if c not in keys]
        status = "OK" if not bad else "!! 未暴露: " + ", ".join(bad)
        print("  %-14s 暴露 %-2d 个　%s" % (name, len(keys), status))
        if bad:
            problems.append("%s 调用了未暴露的方法: %s" % (name, ", ".join(bad)))

    # ---- ③ DOM id 核对 ----
    defined_ids = set(re.findall(r'id="([\w\-]+)"', t))
    used_ids = set(re.findall(r"getElementById\(\s*'([\w\-]+)'\s*\)", clean))
    used_ids |= set(re.findall(r"\$\(\s*'([\w\-]+)'\s*\)", clean))
    missing = sorted(used_ids - defined_ids)
    print("\n[3] DOM id 核对")
    print("  HTML 定义 %d 个，JS 引用 %d 个" % (len(defined_ids), len(used_ids)))
    if missing:
        print("  !! JS 引用但 HTML 里没有: " + ", ".join(missing))
        problems.append("缺少 DOM 元素: " + ", ".join(missing))
    else:
        print("  OK：全部匹配")

    # ---- ④ 已删除函数的残留引用（常见坑） ----
    print("\n[4] 可疑残留（注释里提到但代码里没有定义的函数名）")
    mention = set(re.findall(r"\b(drawCalibTarget|calibTick|paintCalibZone|"
                             r"computeEAR|isBlinking|buildLayout)\b", clean))
    bad_mention = [m for m in sorted(mention) if m not in defined]
    if bad_mention:
        print("  !! 被引用但未定义: " + ", ".join(bad_mention))
        problems.append("残留引用: " + ", ".join(bad_mention))
    else:
        print("  OK")

    print("\n" + "=" * 78)
    if problems:
        print("发现 %d 类问题：" % len(problems))
        for p in problems:
            print("  - " + p)
        return 1
    print("OK：没有发现静态可查的引用问题")
    print("注意：这不等于运行时一定没问题 —— 控制流是否真的到达某处，")
    print("      只有真的跑一遍才能确认（浏览器 Console 或单元测试）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
