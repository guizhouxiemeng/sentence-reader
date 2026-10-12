// check-undeclared.js —— 找出"用了但没声明"的标识符。
//
// 为什么需要这个：
//   我把 content.js 从 1081 行砍到 625 行（浮层改成 iframe 容器），
//   这次删除连带删掉了 `lastExtractEls` 的声明，而引用它的代码还在：
//       const el = lastExtractEls[gi];      // 当场抛 ReferenceError
//   结果 findParaEl 一走到这里就炸、buildMarks 中断、
//   整页没有 span 被包起来 —— 表现为"原文高亮突然没了"，查了很久。
//
//   之前的静态检查只核对"函数调用有没有定义"，不看变量读取，所以漏掉了。
//
// 做法：
//   ① HTML 文件只取 <script> 里的内容（否则 CSS/HTML 全是噪声）
//   ② 剥掉注释、字符串、正则、\uXXXX 转义
//   ③ 收集所有声明（含逗号分隔、解构、参数、for-of）
//   ④ 收集所有被读取的标识符
//   ⑤ 差集里排除 JS 内建与浏览器全局
//
// 用法： node tools/check-undeclared.js <文件> [更多文件...]

const fs = require('fs');
const path = require('path');

const GLOBALS = (`
  Array Object String Number Boolean Date Math JSON Promise Map Set WeakMap WeakSet
  RegExp Error TypeError RangeError SyntaxError ReferenceError parseInt parseFloat
  isNaN isFinite encodeURIComponent decodeURIComponent encodeURI decodeURI
  Infinity NaN undefined null true false this arguments typeof instanceof new delete
  void in of setTimeout clearTimeout setInterval clearInterval queueMicrotask
  console document window globalThis self top parent frames fetch Request Response
  Headers AbortController AbortSignal TextDecoder TextEncoder URL URLSearchParams
  Blob File FileReader FormData Image Event CustomEvent MutationObserver
  IntersectionObserver ResizeObserver requestAnimationFrame cancelAnimationFrame
  requestIdleCallback getComputedStyle matchMedia alert confirm prompt
  chrome browser localStorage sessionStorage location history navigator screen
  performance CSS CSSStyleSheet Element HTMLElement Node NodeFilter Document
  ShadowRoot DOMParser XMLHttpRequest WebSocket Worker MessageChannel structuredClone
  Intl Symbol Proxy Reflect BigInt WeakRef FinalizationRegistry
  innerHeight innerWidth outerHeight outerWidth scrollX scrollY pageXOffset pageYOffset
  atob btoa crypto caches indexedDB Notification CustomElementRegistry
  LanguageModel Summarizer Translator Writer Rewriter LanguageDetector ai
  https http fs path url zlib os child_process crypto stream events util
  process require module exports __dirname __filename Buffer global
` + ' async await yield return function class extends super import export default ' +
  ' if else for while do switch case break continue try catch finally throw ' +
  ' let const var ').trim().split(/\s+/);

const BUILTIN = new Set(GLOBALS.filter(Boolean));

// 单字符与占位符不参与判断
const IGNORE = new Set(['A', 'c', 'g', 'Z', 'RE', 'STR', 'e', 'k', 'v', 'i', 'j', 'n', 'x']);

function scriptsOnly(src, file) {
  if (!/\.html?$/i.test(file)) return src;
  const out = [];
  const re = /<script[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(src))) out.push(m[1]);
  return out.join('\n;\n');
}

function strip(src) {
  let out = '';
  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i], c2 = src[i + 1];
    if (c === '/' && c2 === '/') { while (i < n && src[i] !== '\n') i++; continue; }
    if (c === '/' && c2 === '*') { i += 2; while (i < n && !(src[i] === '*' && src[i + 1] === '/')) i++; i += 2; continue; }
    if (c === '\\' && (c2 === 'u' || c2 === 'x')) {
      // \u4e00 / \x41 这类转义整段丢掉，否则会被当成标识符
      i += 2;
      while (i < n && /[0-9a-fA-F]/.test(src[i])) i++;
      out += ' ';
      continue;
    }
    if (c === '/') {
      // 判断这个 / 是"除号"还是"正则开头"。
      //  只看前一个字符不够 —— `w => /re/` 的前面是 `>`，
      //  `return /re/` 的前面是 `n`，两者都是正则，但都会被漏判，
      //  于是正则内容泄漏出来变成一堆假标识符。
      const before = out.replace(/\s+$/, '');
      const prev = before.slice(-1);
      const PUNCT = '(,=:[!&|?{};>~+-*%^&';
      const KEYWORD = /\b(return|typeof|case|in|of|new|delete|void|do|else|instanceof|yield|await)$/;
      if (PUNCT.includes(prev) || prev === '' || KEYWORD.test(before)) {
        i++;
        while (i < n) {
          if (src[i] === '\\') { i += 2; continue; }
          if (src[i] === '/') break;
          if (src[i] === '\n') break;
          i++;
        }
        i++;
        out += ' ';
        continue;
      }
    }
    if (c === '"' || c === "'" || c === '`') {
      const q = c; i++;
      while (i < n) {
        if (src[i] === '\\') { i += 2; continue; }
        if (src[i] === q) break;
        i++;
      }
      i++;
      out += ' ';
      continue;
    }
    out += c;
    i++;
  }
  return out;
}

function analyze(file) {
  const raw = fs.readFileSync(file, 'utf8');
  const code = strip(scriptsOnly(raw, file));

  const declared = new Set();
  // let/const/var —— 要支持 `let a = 1, b = 2;`（之前只识别出 a）
  for (const m of code.matchAll(/\b(?:let|const|var)\s+([^;\n]+)/g)) {
    m[1].split(',').forEach(part => {
      const left = part.split('=')[0];
      for (const nm of left.matchAll(/([A-Za-z_$][\w$]*)/g)) declared.add(nm[1]);
    });
  }
  for (const m of code.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)/g)) declared.add(m[1]);
  for (const m of code.matchAll(/\bcatch\s*\(\s*([A-Za-z_$][\w$]*)/g)) declared.add(m[1]);
  for (const m of code.matchAll(/\bfunction\s*[A-Za-z_$\w]*\s*\(([^)]*)\)/g)) {
    for (const nm of m[1].matchAll(/([A-Za-z_$][\w$]*)/g)) declared.add(nm[1]);
  }
  for (const m of code.matchAll(/\(([^)]*)\)\s*=>/g)) {
    for (const nm of m[1].matchAll(/([A-Za-z_$][\w$]*)/g)) declared.add(nm[1]);
  }
  for (const m of code.matchAll(/\bfor\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g)) {
    declared.add(m[1]);
  }
  // 对象字面量的方法简写：  getCur() { ... }
  //   不补这一类，reader_flow 里三十多个接口名全会变成"未声明"误报。
  //   代价：行首的函数调用也会被算进 declared（那是"漏报"不是"误报"，
  //   方向上是安全的）。
  for (const m of code.matchAll(/[\n{;,]\s*([A-Za-z_$][\w$]*)\s*\(/g)) {
    declared.add(m[1]);
  }
  // 方法/函数简写的参数：  name(a, b) { ... }
  for (const m of code.matchAll(/[A-Za-z_$][\w$]*\s*\(([^)]*)\)\s*\{/g)) {
    for (const nm of m[1].matchAll(/([A-Za-z_$][\w$]*)/g)) declared.add(nm[1]);
  }
  // 无括号的单参箭头函数：  new Promise(resolve => ...)
  for (const m of code.matchAll(/(?<![\w$.])([A-Za-z_$][\w$]*)\s*=>/g)) {
    declared.add(m[1]);
  }

  const used = new Set();
  for (const m of code.matchAll(/(?<![\w$.])([A-Za-z_$][\w$]*)/g)) {
    const id = m[1];
    if (id.length < 2 || IGNORE.has(id)) continue;
    const after = code.slice(m.index + id.length).replace(/^\s+/, '')[0];
    if (after === ':') continue;                 // 对象字面量的键
    used.add(id);
  }

  const missing = [...used].filter(x => !declared.has(x) && !BUILTIN.has(x));
  return { declared, used, missing };
}

// 无参数时检查项目的关键文件。
//  为什么要有默认值：verify_all 的约定是 `node <script>`，不带参数。
//  要接进一键校验，就必须能无参运行。
const DEFAULT_FILES = [
  'plugin/content.js',
  'plugin/background.js',
  'demo/reader_flow.html',
];

const files = process.argv.slice(2);
const list = files.length ? files : DEFAULT_FILES;

console.log('  检查 "用了但没声明" 的标识符（这个检查抓到过 lastExtractEls，' +
            '它导致整页高亮失效）');

let bad = 0;
list.forEach(f => {
  const p = path.isAbsolute(f) ? f : path.join(__dirname, '..', f);
  const rel = path.relative(path.join(__dirname, '..'), p);
  const r = analyze(p);
  if (!r.missing.length) {
    console.log('  OK   ' + rel + '（声明 ' + r.declared.size + ' 个，无未声明引用）');
  } else {
    bad++;
    console.log('  !!   ' + rel + '  可能用了但没声明：');
    r.missing.sort().forEach(x => console.log('         ' + x));
  }
});
process.exit(bad ? 1 : 0);
