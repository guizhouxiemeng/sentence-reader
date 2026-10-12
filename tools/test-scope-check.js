// test-scope-check.js —— 给 scope-check.js 本身做自测。
//
// 为什么检查器也要测：
//   这个检查器我写错过三次，每次都是"看起来在工作、其实判断全错"：
//     ① 没跳过注释   -> 括号配对错位，误报 132 处
//     ② 没跳过字符串 -> 正则里的引号被当成字符串开始
//     ③ 漏了"定义在调用者自己体内也算可见" -> 误报 addTerm 等
//   一个"会误报"的检查器比没有更糟 —— 会让人不再信任它，然后忽略它。
//
//   所以既要有【阴性样本】（正确的代码必须判 OK），
//         也要有【阳性样本】（真的 bug 必须被抓到）。
//   只有阴性样本的话，一个"永远返回 OK"的废检查器也能通过。
//
// 【实现说明】直接 require 检查器，在同一进程里调用 ——
//   沙箱不允许 Node 用 child_process 的管道 stdio（会 EPERM），
//   所以不能起子进程。这也让自测跑得更快。
//
// 用法： node tools/test-scope-check.js

const fs = require('fs');
const os = require('os');
const path = require('path');
const { check } = require('./scope-check.js');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'demo', 'reader_flow.html');
const src = fs.readFileSync(SRC, 'utf8');

let pass = 0, fail = 0;
function ok(cond, label, extra) {
  if (cond) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label + (extra ? ('\n      ' + extra) : '')); }
}

const TMP = fs.mkdtempSync(path.join(os.tmpdir(), 'scopetest-'));
function write(name, text) {
  const p = path.join(TMP, name);
  fs.writeFileSync(p, text);
  return p;
}
function issues(text) {
  return check(write('t' + (issues._n = (issues._n || 0) + 1) + '.html', text));
}
function textOf(problems) {
  return problems.map(p => p.kind + ':' + p.fn + ':' + p.id).join(' ');
}

console.log('='.repeat(74));
console.log('scope-check 自测');
console.log('='.repeat(74));

// ---------------------------------------------------------------- 阴性样本
console.log('\n阴性样本：正确的代码必须判 OK');
{
  const r = check(SRC);
  ok(r.problems.length === 0, '当前代码判为 OK',
     '实得 ' + r.problems.length + ' 处：' + textOf(r.problems).slice(0, 200));
}

// ---------------------------------------------------------------- 阳性样本 ①
console.log('\n阳性样本①：模块层级的函数调用"定义在别的函数内部"的名字');
{
  // 把 checkOnboard【连同函数体】包进另一个函数 —— 这才是线上那次错误的真实形状：
  //  它缩进 4、写在 bindUI（缩进 2）里面，而 initInner（缩进 2）去调它。
  //
  //  注意必须把整块一起缩进：检查器靠缩进判断嵌套，
  //  只加一行壳、缩进不变的话，它仍会被当成模块层级（第一版样本就是这么错的）。
  const lines = src.split('\n');
  let a = -1, b = -1;
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].indexOf('async function checkOnboard()') >= 0) {
      a = i;
      for (let j = i + 1; j < lines.length; j++) {
        if (lines[j].trim() === '') continue;
        if ((lines[j].match(/^\s*/) || [''])[0].length <= 2) { b = j - 1; break; }
      }
      break;
    }
  }
  ok(a >= 0 && b > a, '定位到 checkOnboard 的范围', 'a=' + a + ' b=' + b);
  const indented = lines.slice(a, b + 1).map(function (l) {
    return l.trim() === '' ? l : ('  ' + l);
  });
  const bad = lines.slice(0, a)
    .concat(['  function someOtherFunction() {'])
    .concat(indented)
    .concat(['  }'])
    .concat(lines.slice(b + 1))
    .join('\n');
  ok(bad !== src, '构造样本成功');
  const r = issues(bad);
  ok(r.problems.some(p => p.id === 'checkOnboard'),
     '报出了 checkOnboard',
     '实得：' + textOf(r.problems).slice(0, 240));
}

// ---------------------------------------------------------------- 阳性样本 ②
console.log('\n阳性样本②：函数参数被注释掉、函数体却还在用它');
{
  const bad = src.replace('  function pickSkill(sent) {',
                          '  function pickSkill(/* sent */) {', 1);
  ok(bad !== src, '构造样本成功');
  const r = issues(bad);
  ok(r.problems.some(p => p.kind === '参数被注释' && p.id === 'sent'),
     '报出了"参数被注释掉：sent"',
     '实得：' + textOf(r.problems).slice(0, 240));
}

// ---------------------------------------------------------------- 该报 / 不该报
console.log('\n平级函数调用内层函数（该报）');
{
  const r = issues(`<script>
function outer() {
  function innerHelper() { return 2; }
  return innerHelper();
}
function sibling() { return innerHelper(); }
</script>`);
  ok(r.problems.some(p => p.id === 'innerHelper'),
     'sibling 调 innerHelper 被报出来', '实得：' + textOf(r.problems));
  ok(!r.problems.some(p => p.fn === 'outer' && p.id === 'innerHelper'),
     'outer 调自己的内层函数不算问题', '实得：' + textOf(r.problems));
}

console.log('\nvar 赋值的函数表达式（不该报）');
{
  const r = issues(`<script>
function outer() {
  var localHelper = function () { return 1; };
  return localHelper();
}
function sibling() { return localHelper(); }
</script>`);
  // localHelper 是 var，不是 function 声明 —— 本检查器不管这一类，交给别的检查
  ok(!r.problems.some(p => p.id === 'localHelper'),
     'var 赋值的函数表达式不被误报', '实得：' + textOf(r.problems));
}

// ---------------------------------------------------------------- 注释/字符串
console.log('\n注释、字符串、正则里的括号不能影响判断');
{
  const r = issues(`<script>
function hasParens(line) {
  // 注释里有括号 ( 和 ) 还有 { 和 }
  var s = "字符串里也有 ( ) { }";
  var re = /^[\\s"'（【]+/;
  return s + re + line;
}
function caller() { return hasParens('x'); }
</script>`);
  ok(r.problems.length === 0, '不会误报',
     '实得 ' + r.problems.length + ' 处：' + textOf(r.problems));
}

console.log('\n缩进 0 的顶层函数（reader_flow 里的 splitSentences 就是）');
{
  const r = issues(`<script>
function topLevel() { return 1; }
const App = (() => {
  function inside() { return topLevel(); }
  return { inside };
})();
</script>`);
  ok(!r.problems.some(p => p.id === 'topLevel'),
     '缩进 0 的顶层函数可以被内部调用', '实得：' + textOf(r.problems));
}

try { fs.rmSync(TMP, { recursive: true, force: true }); } catch (e) { void e; }

console.log('\n' + '='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
