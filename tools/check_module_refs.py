# -*- coding: utf-8 -*-
"""
check_module_refs.py — 检查模块级引用是否有未定义的标识符

为什么需要这个工具
------------------
在这个项目里，"删掉一个函数但留下对它的引用"已经造成过两次严重的
静默故障：

  ① 重写测试流程时误删 exportExperimentCSV，而模块顶部有
     `$('tb-export').onclick = exportExperimentCSV;`
     → 整个模块加载失败 → 页面上所有按钮都点不动，且没有任何提示

  ② 无头测试钩子引用了已删除的 makeTrialOrder / recordTrial 等
     → 模块加载失败

这类错误的特点：语法检查（node --check）完全通过，但运行时模块
根本不执行。所以必须单独做一次"标识符定义性"检查。

做法：提取模块脚本，找出所有"被引用但既不定义也不是全局/内建"的标识符。
只做保守判断（宁可漏报不可误报），重点覆盖模块级语句。

用法： python tools/check_module_refs.py
"""
import os
import re
import sys

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

ROOT = r"D:\projects\gaze-project"
DEMO = os.path.join(ROOT, 'demo', 'demo-hand.html')

# 浏览器/JS 内建与全局，不算未定义
BUILTINS = set("""
Math JSON Object Array String Number Boolean Date RegExp Error Map Set Promise
Symbol BigInt Float64Array Int32Array Uint8Array Uint8ClampedArray ArrayBuffer
window document navigator location performance screen console setTimeout
setInterval clearTimeout clearInterval requestAnimationFrame cancelAnimationFrame
addEventListener removeEventListener alert confirm prompt fetch Blob URL
Image Audio AudioContext webkitAudioContext FileReader FormData XMLHttpRequest
HTMLElement Event KeyboardEvent MouseEvent CustomEvent devicePixelRatio
innerWidth innerHeight outerWidth outerHeight scrollX scrollY
localStorage sessionStorage indexedDB atob btoa TextEncoder TextDecoder
Uint32Array Int16Array Float32Array structuredClone queueMicrotask
AbortController Headers Request Response WebAssembly globalThis
undefined null true false this new typeof instanceof in of void delete
return function if else for while do switch case break continue var let const
class extends super try catch finally throw yield await async
Number isNaN parseInt parseFloat isFinite Infinity NaN
# CSS 函数名（出现在模板字符串里，属误报）
gradient rgba rgb hsl scaleX scaleY rotate translate matrix cubic-bezier
""".split())


def main():
    s = open(DEMO, encoding='utf-8').read()
    m = re.search(r'<script type="module">([\s\S]*?)</script>', s)
    if not m:
        print('未找到模块脚本')
        return 1
    code = m.group(1)

    # 收集所有定义：function 声明、let/const/var、class、参数
    defined = set()
    for mm in re.finditer(r'\bfunction\s+([A-Za-z_$][\w$]*)', code):
        defined.add(mm.group(1))
    for mm in re.finditer(r'\b(?:let|const|var)\s+([A-Za-z_$][\w$]*)', code):
        defined.add(mm.group(1))
    for mm in re.finditer(r'\bclass\s+([A-Za-z_$][\w$]*)', code):
        defined.add(mm.group(1))
    # 解构/多变量声明：let a = 1, b = 2;
    for mm in re.finditer(r'\b(?:let|const|var)\s+([^;=\n]+)', code):
        for name in re.findall(r'([A-Za-z_$][\w$]*)', mm.group(1)):
            defined.add(name)
    # 函数参数与箭头函数参数
    for mm in re.finditer(r'\(([^)]*)\)\s*=>', code):
        for name in re.findall(r'([A-Za-z_$][\w$]*)', mm.group(1)):
            defined.add(name)
    for mm in re.finditer(r'\bfunction\s*[\w$]*\s*\(([^)]*)\)', code):
        for name in re.findall(r'([A-Za-z_$][\w$]*)', mm.group(1)):
            defined.add(name)
    for mm in re.finditer(r'([A-Za-z_$][\w$]*)\s*=>', code):
        defined.add(mm.group(1))
    # for (const x of ...) / catch (e)
    for mm in re.finditer(r'\b(?:for|catch)\s*\(\s*(?:const|let|var)?\s*([A-Za-z_$][\w$]*)', code):
        defined.add(mm.group(1))

    # 找出所有被调用的标识符（形如 name( 或 new name(）
    called = set()
    for mm in re.finditer(r'(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(', code):
        called.add(mm.group(1))
    for mm in re.finditer(r'\bnew\s+([A-Za-z_$][\w$]*)', code):
        called.add(mm.group(1))

    unknown = sorted(n for n in called
                     if n not in defined and n not in BUILTINS)

    # 属性访问不算（obj.method 已由 (?<![\w$.]) 排除）
    print('=' * 74)
    print('模块级标识符定义性检查')
    print('=' * 74)
    print('  已定义: %d 个' % len(defined))
    print('  被调用: %d 个' % len(called))
    print()
    if unknown:
        print('  ✗ 以下 %d 个标识符被调用但没有定义：' % len(unknown))
        for n in unknown:
            # 找出调用位置的行号，便于定位
            lines = [code[:mm.start()].count('\n') + 1
                     for mm in re.finditer(r'(?<![\w$.])' + re.escape(n) + r'\s*\(', code)]
            print('      %-28s 行 %s' % (n, lines[:5]))
        print()
        print('  → 这类错误会让【整个模块加载失败】，'
              '而 node --check 语法检查无法发现。')
        print('    必须补回定义，或删除对应引用。')
        return 1
    else:
        print('  ✓ 没有未定义的调用 —— 模块应当能正常加载')
        return 0


if __name__ == '__main__':
    sys.exit(main())
