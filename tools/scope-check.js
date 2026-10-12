// scope-check.js —— 抓"名字在当前作用域里看不到"的问题。
//
// 为什么需要（踩过两次，代价都很大）：
//   ① function pickSkill(/* sent */) { ... termExampleFor(sent) }
//      参数名被注释掉了，函数体却还在用它 -> ReferenceError
//      -> 每一句都"讲解失败：sent is not defined"，讲解功能全废
//
//   ② checkOnboard 定义在 bindUI() 里面，却从 initInner() 里调用
//      -> ReferenceError: checkOnboard is not defined
//      -> initInner 一进来就抛异常，后面全部不执行
//      -> 界面停在"粘贴文本"那一屏，看起来像"功能坏了"
//
//   两次 check-undeclared.js 都报 OK —— 它是【全局扁平】的：
//   把所有函数名收进一个大集合，于是"定义在别的函数里"也算"已声明"。
//
// ---------------------------------------------------------------------------
// 【为什么用缩进判断嵌套，而不是括号配对】
//
//   我先写了括号配对版，错了三次，每次都是一类新坑：
//     ① 没跳过注释  —— 注释里写着 "Cannot read properties of null (reading 'value')"，
//        里面的括号让配对错位
//     ② 跳过字符串  —— 正则字面量 /^[\s「『"'（]+/ 里的引号被当成字符串开始，
//        从那里一路吞下去
//     ③ 还有正则里的 { } 没处理
//   结果是 linesToParas 被判成跨 1000 多行，模块层级的函数全被算成嵌套的，
//   一次误报 132 处。
//
//   而这个代码库的缩进是严格一致的（一级 2 空格）。
//   用缩进判断"谁在谁里面"不需要解析任何语法，上面三类坑都不存在。
//   代价：如果有人写出缩进不一致的代码，判断会偏。
//   对这个项目来说，这个代价比"解析器永远修不完"小得多。
// ---------------------------------------------------------------------------
//
// 判据保守，宁可漏报不误报。
//
// 用法： node tools/scope-check.js [文件...]

const fs = require('fs');
const path = require('path');

function scriptsOnly(raw, file) {
  if (!/\.html?$/i.test(file)) return raw;
  return [...raw.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)]
    .map(m => m[1]).join('\n');
}

function indentOf(line) {
  const m = /^(\s*)/.exec(line);
  return m ? m[1].length : 0;
}

const FUNC_RE = /^\s*(?:async\s+)?function\s+([A-Za-z_$][\w$]*)?\s*\(/;

// ---------------------------------------------------------------------------
//  作用域检查的辅助工具（必须放在模块层级）
//
//  我第一版是通过替换 `const KEYWORD = ...` 插入的，
//  而 KEYWORD 恰好在 check() 内部 —— 于是这几个函数都成了 check 的局部函数，
//  module.exports 引用不到，直接 ReferenceError。
//  把它放在这里，check() 同样看得到（模块层级对函数内是可见的）。
// ---------------------------------------------------------------------------

const KEYWORD = /^(if|for|while|switch|catch|return|typeof|function|new|await|else|do|in|of|case|delete|void|yield|throw|super|this|null|true|false|undefined)$/;

// ---------------------------------------------------------------------------
//  跨模块裸引用
//
//  这个文件由多个平级的 IIFE 组成：
//      const TextSource = (() => { ... })();
//      const Reader     = (() => { ... })();
//      const App        = (() => { ... })();
//  每个 IIFE 内部的 function / let / const 都是私有的，
//  别的模块只能通过 `Xxx.name` 用【导出过的】那些。
//
//  实测踩过三次：cfg / providerOf / builtinInfo 都是 Explainer 内部的，
//  却在 App 里裸用了 —— 全是运行时才暴露的 ReferenceError。
//  而 check-undeclared 和前两项检查都是"全局扁平"的，看不见 IIFE 边界。
// ---------------------------------------------------------------------------
const MODULE_RE = /^const ([A-Za-z_$][\w$]*) = \(\(\) => \{/;

function findModules(lines) {
const mods = [];
lines.forEach((l, i) => {
  const m = MODULE_RE.exec(l);
  if (m) mods.push({ name: m[1], start: i, end: lines.length });
});
for (let k = 0; k < mods.length - 1; k++) mods[k].end = mods[k + 1].start;
return mods;
}

// 模块内部声明（缩进 2 的 function / let / const / var）
function moduleDecls(lines, mod) {
const out = new Set();
for (let i = mod.start; i < mod.end; i++) {
  const l = lines[i];
  if (l.length - l.trimStart().length !== 2) continue;
  let m = /^  (?:async\s+)?function\s+([A-Za-z_$][\w$]*)/.exec(l);
  if (m) { out.add(m[1]); continue; }
  m = /^  (?:let|const|var)\s+([A-Za-z_$][\w$]*)/.exec(l);
  if (m) out.add(m[1]);
}
return out;
}

// 模块导出的名字（return { ... } 里列的）
function moduleExports(lines, mod) {
const out = new Set();
for (let i = mod.start; i < mod.end; i++) {
  if (!/^  return \{/.test(lines[i])) continue;
  for (let j = i; j < mod.end; j++) {
    if (/^  \};/.test(lines[j])) break;
    for (const w of lines[j].matchAll(/[A-Za-z_$][\w$]*/g)) out.add(w[0]);
  }
  break;
}
return out;
}

function checkCrossModule(lines) {
const problems = [];
const mods = findModules(lines);
if (mods.length < 2) return problems;

const info = mods.map(m => ({
  name: m.name, start: m.start, end: m.end,
  decls: moduleDecls(lines, m),
  exports: moduleExports(lines, m),
}));

info.forEach(host => {
  // 自己声明的名字（包括嵌套的），用来跳过"本地同名"
  const ownAll = new Set();
  for (let i = host.start; i < host.end; i++) {
    for (const m of lines[i].matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)/g)) ownAll.add(m[1]);
    for (const m of lines[i].matchAll(/\b(?:let|const|var)\s+([A-Za-z_$][\w$]*)/g)) ownAll.add(m[1]);
  }

  for (let i = host.start; i < host.end; i++) {
    const raw = lines[i];
    const t = raw.trim();
    if (!t || t.startsWith('//') || t.startsWith('*') || t.startsWith('/*')) continue;
    // 去掉行尾注释与字符串，避免误判
    let clean = raw.replace(/\/\/.*$/, '');
    clean = clean.replace(/'(?:[^'\\]|\\.)*'/g, "''");
    clean = clean.replace(/"(?:[^"\\]|\\.)*"/g, '""');

    info.forEach(src => {
      if (src.name === host.name) return;
      src.decls.forEach(name => {
        if (src.exports.has(name)) return;   // 导出过的，通过 Xxx.name 用
        if (ownAll.has(name)) return;        // 本模块也有同名 -> 可能是它自己的
        // 裸用：前面不是 字母/数字/./$，后面不是 字母/数字/$，且不是对象键
        const re = new RegExp('(?<![\\w$.])' + name + '(?![\\w$])\\s*(?!:)');
        if (!re.test(clean)) return;
        // 排除 "src.name" 这种正确写法（clean 里会出现 src.name）
        const okRe = new RegExp('(?<![\\w$.])' + src.name + '\\.' + name + '(?![\\w$])');
        const stripped = clean.replace(new RegExp('(?<![\\w$.])' + src.name + '\\.' + name + '(?![\\w$])', 'g'), ' ');
        if (new RegExp('(?<![\\w$.])' + name + '(?![\\w$])\\s*(?!:)').test(stripped)) {
          problems.push({ kind: '跨模块', fn: host.name, id: name, src: src.name, line: i + 1 });
        }
      });
    });
  }
});

const uniq = new Map();
problems.forEach(p => uniq.set(p.kind + '|' + p.fn + '|' + p.id, p));
return [...uniq.values()];
}

function check(file) {
  const raw = fs.readFileSync(file, 'utf8');
  const code = scriptsOnly(raw, file);
  const lines = code.split('\n');
  const problems = [];

  // ---------------- 收集函数声明：名字 -> 出现的缩进 ----------------
  const declIndents = new Map();      // name -> Set(indent)
  lines.forEach(l => {
    const m = FUNC_RE.exec(l);
    if (!m || !m[1]) return;
    const ind = indentOf(l);
    if (!declIndents.has(m[1])) declIndents.set(m[1], new Set());
    declIndents.get(m[1]).add(ind);
  });

  // 模块层级 = 出现次数最多的那个缩进（这个项目里是 2）
  const freq = new Map();
  declIndents.forEach(set => set.forEach(ind => freq.set(ind, (freq.get(ind) || 0) + 1)));
  let baseIndent = 2, best = -1;
  freq.forEach((c, ind) => { if (c > best) { best = c; baseIndent = ind; } });

  // 在模块层级声明过的名字（可以被任何地方调用）。
  //  用 <= 而不是 == ：reader_flow.html 里 splitSentences 定义在缩进 0
  //  （在 App 那个 IIFE 外面），它也属于"大家都能看到"。
  const moduleFns = new Set();
  declIndents.forEach((set, name) => {
    for (const ind of set) { if (ind <= baseIndent) { moduleFns.add(name); break; } }
  });

  // 每个函数声明的"函数体范围"（用缩进回落判断，不用括号配对）
  //  行号从 0 开始；end 是最后一行正文的下标（含）。
  const fnRanges = [];
  lines.forEach((l, i) => {
    const m = FUNC_RE.exec(l);
    if (!m) return;
    const ind = indentOf(l);
    let end = i;
    for (let j = i + 1; j < lines.length; j++) {
      if (lines[j].trim() === '') continue;
      if (indentOf(lines[j]) <= ind) break;
      end = j;
    }
    fnRanges.push({ line: i, end: end, indent: ind, name: m[1] || '(匿名)' });
  });
  // 判断一个函数声明是不是【真的嵌套在另一个 function 里面】。
  //
  //  PdfSource 的内部函数（缩进 4）和 checkOnboard（缩进 4）缩进一样，
  //  区别只在于外层是 IIFE 还是 function 声明 —— 光看缩进分不出来。
  //  所以往上看：最近的一个缩进更小的非空行如果是 function 声明，
  //  才算真嵌套。（保守：IIFE / 箭头 / 别的块都按"可见"处理，宁可漏报。）
  function nestedInFunction(declLine, declIndent) {
    for (let j = declLine - 1; j >= 0; j--) {
      const l = lines[j];
      if (l.trim() === '') continue;
      const ind = indentOf(l);
      if (ind >= declIndent) continue;         // 同一层或更深，继续往上看
      return FUNC_RE.test(l);                  // 更小缩进的最近一行是不是 function
    }
    return false;
  }

  // name -> 它所有声明所在的行号（只收"真嵌套"的那些）
  const declLines = new Map();
  fnRanges.forEach(r => {
    if (!nestedInFunction(r.line, r.indent)) return;
    if (!declLines.has(r.name)) declLines.set(r.name, []);
    declLines.get(r.name).push(r.line);
  });

  // ---------------- 检查一：参数被注释掉，体内还在用 ----------------
  //  这一段不需要嵌套信息 —— 只看参数表和紧随其后的函数体，
  //  用"缩进回落"来找函数体结尾（同样不需要括号配对）。
  lines.forEach((l, i) => {
    const m = FUNC_RE.exec(l);
    if (!m || !m[1]) return;
    const pStart = l.indexOf('(', m.index + m[0].indexOf('('));
    // 参数表可能跨行；这里只处理单行参数的常见情况，跨行时跳过（宁可漏报）
    if (pStart < 0) return;
    let depth = 0, pEnd = -1;
    for (let k = pStart; k < l.length; k++) {
      if (l[k] === '(') depth++;
      else if (l[k] === ')') { depth--; if (depth === 0) { pEnd = k; break; } }
    }
    if (pEnd < 0) return;
    const params = l.slice(pStart + 1, pEnd);
    if (params.indexOf('/*') < 0) return;

    const commented = new Set();
    for (const c of params.matchAll(/\/\*([\s\S]*?)\*\//g)) {
      for (const w of c[1].matchAll(/[A-Za-z_$][\w$]*/g)) commented.add(w[0]);
    }
    if (!commented.size) return;
    const realParams = new Set();
    for (const w of params.replace(/\/\*[\s\S]*?\*\//g, ' ').matchAll(/[A-Za-z_$][\w$]*/g)) {
      realParams.add(w[0]);
    }

    // 函数体：从下一行开始，直到缩进回落到不超过声明行的缩进
    const fnIndent = indentOf(l);
    const body = [];
    for (let j = i + 1; j < lines.length; j++) {
      if (lines[j].trim() === '') { body.push(lines[j]); continue; }
      if (indentOf(lines[j]) <= fnIndent) break;
      body.push(lines[j]);
    }
    const bodyText = body.join('\n');
    commented.forEach(id => {
      if (realParams.has(id)) return;
      if (new RegExp('(?<![\\w$.])' + id + '(?![\\w$])\\s*(?!:)').test(bodyText)) {
        problems.push({ kind: '参数被注释', fn: m[1], id: id, line: i + 1 });
      }
    });
  });

  // ---------------- 检查二：调用了从调用点看不到的名字 ----------------
  //  找每个"调用点"所在的函数：往上扫第一行缩进【小于】本行缩进的函数声明。
  //  在缩进一致的代码里，这就是它的外层函数。

  lines.forEach((l, i) => {
    const trimmed = l.trim();
    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('*') ||
        trimmed.startsWith('/*')) return;
    const ind = indentOf(l);

    // 往上找外层函数
    let owner = null;
    for (let j = i - 1; j >= 0; j--) {
      const m = FUNC_RE.exec(lines[j]);
      if (!m) continue;
      const fi = indentOf(lines[j]);
      if (fi < ind) { owner = { name: m[1] || '(匿名)', indent: fi, line: j }; break; }
    }
    // 找不到外层函数 = 这行在"顶层作用域"里。
    //
    //  【这是一个必须处理的正常情况，不是异常】
    //  reader_flow.html 里所有模块层级函数都缩进 2，
    //  而它们的上面【没有缩进更小的 function 声明】
    //  （外层是 const App = (() => { ... })()，是箭头函数，不是 function 声明）。
    //  所以按"往上找外层 function"的写法，这些函数的 owner 永远是 null ——
    //  第一版在这里直接 return，等于【模块层级的函数从来没被检查过】。
    //  自测的阳性样本就是因此没抓到（检查器自测第一次起作用）。
    const ownerRange = owner ? fnRanges.find(r => r.line === owner.line)
                             : { line: -1, end: lines.length - 1, indent: -1, name: '(顶层)' };

    // 只在【顶层 / 模块层级】检查：
    //  更深层的函数看不到很多东西是正常的（它可能就是某个内层回调），
    //  报出来误报太多。真正致命的是模块层级看不到 ——
    //  它一定在启动路径上，一抛异常整个界面就停住。
    if (owner && owner.indent > baseIndent) return;

    // 这一行里调用了哪些名字
    for (const m of l.matchAll(/(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(/g)) {
      const id = m[1];
      if (id.length < 3 || KEYWORD.test(id)) continue;
      if (moduleFns.has(id)) continue;         // 模块层级有定义 -> 看得到
      const dls = declLines.get(id);
      if (!dls) continue;                      // 文件里压根没定义 -> 交给 check-undeclared
      // 定义在【调用者自己体内】也算看得到
      //  （比如 addTerm 就定义在 renderBody 里面，从 renderBody 调它是对的）
      //
      //  注意这条只在 owner 存在时才有意义。
      //  owner 为 null 表示"在顶层作用域"，此时范围是整个文件 ——
      //  拿它去判断的话，什么都会被算成"在自己体内"，检查就永远不报了。
      //  （自测的阳性样本就是这么暴露出来的。）
      if (owner && ownerRange &&
          dls.some(dl => dl > ownerRange.line && dl <= ownerRange.end)) continue;
      problems.push({ kind: '看不到',
                      fn: owner ? owner.name : '(顶层)',
                      id: id, line: i + 1 });
    }
  });

  // ---------------- 检查三：跨模块裸引用（仅供参考，不计入失败）----------------
  //  它误报较多（脚本顶层声明的名字、本模块自己的方法等等都被算进来），
  //  所以单独返回，不混进 problems。
  //
  //  这么决定的依据：这几天反复验证了一条 ——
  //  **会误报的检查比没有更糟**：报一堆假的，真的那条就淹在里面，
  //  然后人会开始忽略整个检查。所以让它只提供线索，不阻止交付。
  const crossFindings = checkCrossModule(lines);

  // 去重
  const uniq = new Map();
  problems.forEach(p => uniq.set(p.kind + '|' + p.fn + '|' + p.id, p));
  return { problems: [...uniq.values()], baseIndent: baseIndent,
           cross: crossFindings };
}

// ---------------------------------------------------------------------------
//  导出：既能当命令行用，也能被 require 进来直接调 check()
//  （自测就是这么用的 —— 沙箱不允许 Node 用管道起子进程）
// ---------------------------------------------------------------------------
module.exports = { check: check, checkCrossModule: checkCrossModule,
                   findModules: findModules };

if (require.main !== module) return;

const DEFAULT_FILES = ['plugin/content.js', 'plugin/background.js', 'demo/reader_flow.html'];
const args = process.argv.slice(2);
const list = args.length ? args : DEFAULT_FILES;
const root = path.resolve(__dirname, '..');

console.log('作用域检查：名字在当前位置看不到');
console.log('  ① 函数参数被注释掉、函数体却还在用它          【会影响交付】');
console.log('  ② 模块层级的函数里，调用了只存在于别的函数内部的名字【会影响交付】');
console.log('  ③ 模块里裸用了别的模块的内部名字（仅供参考，见下）');
console.log('  （用缩进判断嵌套 —— 见文件头的说明，为什么不解析语法）');
console.log('');

let total = 0;
const advisory = [];
list.forEach(f => {
  const p = path.isAbsolute(f) ? f : path.join(root, f);
  if (!fs.existsSync(p)) { console.log('  跳过（不存在）' + f); return; }
  const r = check(p);
  if (!r.problems.length) {
    console.log('  OK   ' + f + '   （模块层级缩进 = ' + r.baseIndent +
                (r.cross && r.cross.length ? '，另有 ' + r.cross.length + ' 条待人工确认' : '') + '）');
  } else {
    total += r.problems.length;
    console.log('  !!   ' + f + '  ' + r.problems.length + ' 处');
    r.problems.forEach(x => {
      if (x.kind === '参数被注释') {
        console.log('        第 ' + x.line + ' 行  函数 ' + x.fn +
                    '() 的参数表里注释掉了 `' + x.id + '`，但函数体里用到了它');
      } else {
        console.log('        第 ' + x.line + ' 行  函数 ' + x.fn +
                    '() 里调用了 `' + x.id + '`，但 `' + x.id +
                    '` 只定义在别的函数内部，这里看不到');
      }
    });
  }
  if (r.cross && r.cross.length) {
    r.cross.forEach(x => advisory.push({ file: f, x: x }));
  }
});

console.log('');
if (total === 0) {
  console.log('影响交付的检查：全部通过 ✓');
} else {
  console.log('发现 ' + total + ' 处，请检查');
}

// 跨模块的发现单独列出来 —— 它误报较多，只提供线索，不阻止交付。
if (advisory.length) {
  console.log('');
  console.log('以下 ' + advisory.length + ' 条【需要人工确认】（误报较多，不计入失败）：');
  console.log('  判据是"某个模块内部的名字，在另一个模块里被裸用"。');
  console.log('  但下面这些情况会被误判，所以只能人工看：');
  console.log('    · 该名字在脚本顶层也声明过（那其实是全局可见的）');
  console.log('    · 该名字在本模块里也有（只是声明方式我没识别到）');
  advisory.slice(0, 20).forEach(a => {
    console.log('    ' + a.file + ' 第 ' + a.x.line + ' 行  ' + a.x.fn +
                ' 模块里用了 `' + a.x.id + '`（声明在 ' + a.x.src + ' 模块）');
  });
  if (advisory.length > 20) console.log('    …（还有 ' + (advisory.length - 20) + ' 条）');
}

console.log('');
process.exit(total === 0 ? 0 : 1);
