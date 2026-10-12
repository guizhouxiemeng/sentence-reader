// test-trigger.js —— 用合成数据验证推断层（Trigger）的判定逻辑。
//
// 为什么单独测：
//   "该不该讲解"的判定是这套东西的**唯一难点**。
//   界面好不好看是次要的；判错了要么打扰用户（误报），要么形同虚设（漏报）。
//   而它是纯逻辑，可以在 Node 里穷举验证，不必靠人读一遍来试。
//
// 做法：从 reader_flow.html 里抽出 Trigger 模块，喂不同场景的统计量，看判定。
//
// 用法： node tools/test-trigger.js

const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'demo', 'reader_flow.html');
const src = fs.readFileSync(FILE, 'utf8');

// ---- 抽出 Trigger 模块（按大括号配平取 IIFE 全文）----
const startMark = 'const Trigger = (() => {';
const a = src.indexOf(startMark);
if (a < 0) { console.error('找不到 Trigger 模块'); process.exit(1); }
const k = src.indexOf('{', src.indexOf('=>', a));
let depth = 0, end = -1;
for (let j = k; j < src.length; j++) {
  if (src[j] === '{') depth++;
  else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
}
// 切片到箭头函数的 } 为止，还要补上 IIFE 的收尾 ")();"，
// 否则拿到的是一段不完整的代码（SyntaxError: Unexpected identifier 'module'）。
let code = src.slice(a, end) + ')();\nmodule.exports = Trigger;\n';

// 用 Function 构造，避免写临时文件
const mod = { exports: {} };
new Function('module', 'exports', code)(mod, mod.exports);
const T = mod.exports;

// Trigger 的单位计数器是注入式的（不直接依赖 TextSource），
// 这里注入一个与生产环境一致的实现，测试才能反映真实行为。
T.setUnitCounter(function (text) {
  const t = String(text || '');
  const CJK = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/g;
  const cjk = (t.match(CJK) || []).length;
  const rest = t.replace(CJK, ' ');
  const words = (rest.match(/[A-Za-z0-9][A-Za-z0-9'\u2019\-]*/g) || [])
    .filter(w => /[A-Za-z]/.test(w)).length;
  return cjk + words;
});

console.log('='.repeat(76));
console.log('推断层（Trigger）合成数据验证');
console.log('='.repeat(76));
console.log('阈值:');
const R = T.RULE;
console.log('  ratio < ' + R.T_SKIP + ' 且无回看        -> 略读');
console.log('  ' + R.T_READ_LO + ' ~ ' + R.T_READ_HI + '                    -> 正常');
console.log('  ratio > ' + R.T_PREPARE + '                    -> 静默准备');
console.log('  ratio > ' + R.T_BLOCKED + ' 且满足辅助条件      -> 处理受阻');
console.log('  辅助条件: 回看 >= ' + R.AUX_REVISIT_MIN +
            ' 次，或单次停留 > ' + R.AUX_LONG_VISIT_MULT + '× 基线');
console.log('  默认基线 ' + R.CPS_DEFAULT + ' 字/秒（会随阅读校正）');
console.log();

// 造一句 20 字的句子。cps=5 -> base = 4 秒
const sent = { text: '这是一句刚好二十个字的测试句子用来验证推断层的判定逻辑是否正确' };
console.log('测试句长度: ' + sent.text.length + ' 字 -> 预期基线 ' +
            (sent.text.length / R.CPS_DEFAULT).toFixed(1) + ' 秒');
console.log();

// 注意：基线是"字数 / 5 字每秒"。这句 31 字 -> 基线 6.2 秒。
// 所以各档的停留时长必须按 6.2 来算，不能凭感觉填 ——
// 第一版测试就是因为填了 11 秒却以为基线是 4 秒，误判成"逻辑不对"。
// 基线 = 字数 / 默认速度。这句 31 字、默认 5 单位/秒 -> 基线 6.2 秒。
// 各档的停留时长【按模块里的阈值算出来】，不写死数字 ——
// 否则一旦调阈值（比如 T_BLOCKED 从 2.0 调到 2.6），测试就会假失败。
// 之前就踩过：改了阈值，用例还按旧阈值写，测试报错但代码其实是对的。
const BASE = sent.text.length / T.RULE.CPS_DEFAULT;
const TB = T.RULE.T_BLOCKED;
const TPREP = T.RULE.T_PREPARE;
const TSKIP = T.RULE.T_SKIP;
const NORM = 1.0;                     // 正常读完：ratio ≈ 1

const cases = [
  { name: '正常读完',
    dwell: BASE * NORM, visits: 1, want: 'reading' },
  { name: '快速扫过',
    dwell: BASE * (TSKIP * 0.7), visits: 1, want: 'skipped' },
  { name: '读完但回看一次',
    dwell: BASE * NORM, visits: 2, want: 'reading' },
  { name: '偏慢但没回看',
    dwell: BASE * 1.6, visits: 1, want: 'reading' },
  { name: '卡住：久 + 回看',
    dwell: BASE * (TB * 1.05), visits: 3, want: 'blocked' },
  { name: '卡住：久 + 单次长',
    dwell: BASE * (TB * 1.08), visits: 1, longest: BASE * (TB * 1.08), want: 'blocked' },
  { name: '久但无辅助条件',
    dwell: BASE * (TB * 1.05), visits: 2, longest: BASE * 0.9, want: 'reading' },
  { name: '略读但回看过',
    dwell: BASE * (TSKIP * 0.7), visits: 2, want: 'reading' },
];

let pass = 0;
console.log('  场景'.padEnd(22) + '停留'.padStart(8) + '进入'.padStart(7) +
            'ratio'.padStart(8) + '最长'.padStart(8) + '  判定'.padEnd(10) + '期望');
console.log('  ' + '-'.repeat(72));

cases.forEach(c => {
  const st = {
    dwell: c.dwell,
    visits: c.visits,
    longest: c.longest !== undefined ? c.longest : c.dwell,
  };
  const r = T.evaluate(sent, st);
  const ok = r.state === c.want;
  if (ok) pass++;
  console.log('  ' + c.name.padEnd(20) +
              c.dwell.toFixed(1).padStart(8) +
              String(c.visits).padStart(7) +
              r.ratio.toFixed(2).padStart(8) +
              st.longest.toFixed(1).padStart(8) +
              '  ' + (r.state + (ok ? '' : ' ✗')).padEnd(12) + c.want);
});

console.log();
console.log('判定正确: ' + pass + '/' + cases.length);
console.log();

// ---- 静默准备 ----
//  注意：这一段必须在【基线校正】之前跑 ——
//  基线一但被学习过，后面的 ratio 就全变了（第一版就是被这个坑到）。
console.log();
console.log('='.repeat(76));
console.log('静默准备触发');
console.log('='.repeat(76));
[
  { dwell: BASE * 0.9,        label: '正常读完' },
  { dwell: BASE * (TPREP + 0.05), label: '偏慢' },
  { dwell: BASE * (TPREP + 0.4),  label: '明显偏慢' },
].forEach(c => {
  const st = { dwell: c.dwell, visits: 1, longest: c.dwell };
  const r = T.evaluate(sent, st);
  console.log('  ' + c.label.padEnd(12) + 'ratio ' + r.ratio.toFixed(2) +
              '  准备=' + T.shouldPrepare(sent, r));
});

// ---- 自动展开 ----
console.log();
console.log('='.repeat(76));
console.log('自动展开（30 秒内受阻 3 次）');
console.log('='.repeat(76));
const now = Date.now();
console.log('  第 1 次受阻后: ' + T.shouldAutoReveal(now));
console.log('  第 2 次受阻后: ' + T.shouldAutoReveal(now + 1000));
T.noteBlocked(now); T.noteBlocked(now + 1000); T.noteBlocked(now + 2000);
console.log('  第 3 次受阻后: ' + T.shouldAutoReveal(now + 3000) + '  <- 应该 true');
console.log('  紧接着再查:   ' + T.shouldAutoReveal(now + 3100) + '  <- 应该 false（冷却中）');

// ---- 基线校正 ----
console.log('='.repeat(76));
console.log('基线校正（用正常读完的句子学习用户速度）');
console.log('='.repeat(76));
const slow = { text: '这是一句刚好二十个字的测试句子用来验证推断层的判定逻辑是否正确' };
// 一个读得慢的人：20 字用 10 秒 -> 2 字/秒
for (let i = 0; i < 6; i++) {
  const st = { dwell: 10, visits: 1, longest: 10 };
  const r = T.evaluate(slow, st);
  T.learn(slow, r);
}
const t1 = T.stats();
console.log('  连续 6 句"20 字读 10 秒"后，基线 = ' + t1.cps.toFixed(2) +
            ' 字/秒（样本 ' + t1.samples + '）');
console.log('  -> 该用户的预期基线变为 ' + (slow.text.length / t1.cps).toFixed(1) +
            ' 秒（默认是 ' + (slow.text.length / R.CPS_DEFAULT).toFixed(1) + ' 秒）');
console.log('  这很重要：否则读得慢的人会被全部判成受阻。');

console.log();
console.log('='.repeat(76));
if (pass === cases.length) {
  console.log('全部通过 ✓');
} else {
  console.log('有 ' + (cases.length - pass) + ' 项不符合预期');
}
console.log('='.repeat(76));
process.exit(pass === cases.length ? 0 : 1);
