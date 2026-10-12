// test-pdfparas.js —— 验证 PDF 的段落识别。
//
// 为什么值得单独测：
//   用户反馈"PDF 提取出来的文字不分段，看起来一大坨"。
//   原因是判断段落只用了一条依据（行距明显大于中位数），
//   而很多 PDF 行距均匀，段落靠【首行缩进】或【上一行没写满】区分。
//
//   段落识别错了不会报错，只是"读起来难受" —— 这种问题最容易拖着不修，
//   所以用合成的行数据把它锁住：三种排版习惯各测一遍。
//
// 用法： node tools/test-pdfparas.js

const fs = require('fs');
const path = require('path');

const src = fs.readFileSync(path.join(__dirname, '..', 'demo', 'reader_flow.html'), 'utf8');
const m = src.match(/function linesToParas\(lines\) \{[\s\S]*?\n    \}/);
if (!m) { console.log('  找不到 linesToParas'); process.exit(1); }

// linesToParas 依赖 isJunkLine（过滤页眉页脚水印），一起抽出来
const junkM = src.match(/function isJunkLine\(t\) \{[\s\S]*?\n    \}/);
const JUNKM = src.match(/const JUNK = \[[\s\S]*?\n    \];/);
if (!junkM || !JUNKM) { console.log('  找不到 isJunkLine / JUNK'); process.exit(1); }

// eslint-disable-next-line no-new-func
const linesToParas = new Function(
  'lines',
  'const JUNK = ' + JUNKM[0].replace(/^const JUNK = /, '').replace(/;$/, '') + ';\n' +
  junkM[0] + '\n' + m[0] + '\nreturn linesToParas(lines);'
);

let pass = 0, fail = 0;
function check(ok, label, extra) {
  if (ok) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label + (extra ? ('\n      ' + extra) : '')); }
}

// 造一批行。y 从上往下递减，x0/x1 是左右边界，charW 是估算字宽。
const CW = 6;                       // 字宽 6pt
const LEFT = 60;                    // 正文左边界
const RIGHT = 60 + 40 * CW;         // 一行写满约 40 字

function L(y, text, opt) {
  opt = opt || {};
  const x0 = LEFT + (opt.indent || 0);
  const x1 = x0 + text.length * CW;
  return { y: y, text: text, x0: x0, x1: x1, charW: CW, size: 10 };
}
// 真实排版里每行末尾都有句末标点 —— 用例也要这样，
//  否则「合并到句末」的兜底会把所有行并成一段（第一版就是这么炸的）。
const FULL = '这是一个写满整行的句子用来占位一二三四五六七八九十。';   // 24 字
function full(y, opt) { return L(y, FULL, opt); }
// 段落首行：缩进，但【仍然写满整行】—— 真实 PDF 就是这样。
//  注意：不能把它写成短行，否则它会被当成段落结尾（早期用例就错在这里）。
const HEAD = '段落首行缩进之后同样写满整行一二三四五六七八九十。';
function head(y) { return L(y, HEAD, { indent: 2 * CW }); }

console.log('='.repeat(74));
console.log('PDF 段落识别');
console.log('='.repeat(74));

// ---- ① 靠首行缩进分段的排版 ----
{
  // 行距均匀（12pt），只有首行缩进 2 字
  const ls = [
    head(500), full(488), full(476), full(464),
    head(452), full(440), full(428),
  ];
  const ps = linesToParas(ls);
  check(ps.length === 2, '首行缩进能分出两段',
        '实得 ' + ps.length + ' 段：' + JSON.stringify(ps.map(p => p.slice(0, 12))));
  check(ps[0].indexOf('段落首行缩进') === 0, '第一段以缩进那行开头');
  check(ps[1].indexOf('段落首行缩进') === 0, '第二段以缩进那行开头');
}

// ---- ② 靠"上一行没写满"分段的排版（无缩进）----
{
  const ls = [
    full(500), full(488),
    L(476, '这一段在句号处结束了。'),        // 短行 -> 段落结束
    full(464), full(452),
    L(440, '又在句号处结束。'),
  ];
  const ps = linesToParas(ls);
  // 短行是段落的【结尾】，应当并进上一段 —— 所以是 2 段不是 3 段。
  //  （最早把期望写成 3 段，是我想错了：短行不会另起一段。）
  check(ps.length === 2, '短行作为段落结尾被并进上一段',
        '实得 ' + ps.length + ' 段：' + JSON.stringify(ps.map(p => p.slice(0, 10))));
  check(ps[0].indexOf('这一段在句号') > 0, '短行留在第一段末尾');
  check(ps[1].indexOf('又在句号') > 0, '第二段结尾是那个短行');
}

// ---- ③ 靠行距突变分段的排版 ----
{
  const ls = [
    full(500), full(488), full(476),
    full(452),                            // 与上一行差 24（常规 12 的两倍）
    full(440),
  ];
  const ps = linesToParas(ls);
  check(ps.length === 2, '行距突变能分段', '实得 ' + ps.length + ' 段');
}

// ---- ④ 不该断开的情况 ----
{
  // 行距均匀、每行都写满、无缩进 -> 应该是一整段
  const ls = [full(500), full(488), full(476), full(464), full(452)];
  const ps = linesToParas(ls);
  check(ps.length === 1, '排版均匀时不该乱断', '实得 ' + ps.length + ' 段');
}

// ---- ⑤ 空输入不炸 ----
{
  check(linesToParas([]).length === 0, '空输入返回空数组');
}

// ---- ⑥ 文字要拼回可读的形式 ----
{
  const ls = [full(500), full(488)];
  const ps = linesToParas(ls);
  check(ps.length === 1 && ps[0].indexOf('这是一个') === 0, '段落文字保留');
  check(ps[0].indexOf('  ') < 0, '没有连续空格');
}

// ---- ⑦ 段落必须以句末标点结尾 ----
console.log('\n段落结尾必须是完整的句子');
{
  // 用【行距】明确制造断点（12 是常规，40 明显偏大 -> 断段）。
  //  这正是用户截图里的情况：判据在某处断开了，但断开的位置不一定是句子边界。
  const ls = [
    L(500, 'the image of the solitary Asian ascetic is spreading.'),
    L(488, 'It appears in unexpected places.'),
    L(448, 'Secretaries are doing it as daily yoga'),    // 行距 40 -> 断
    L(436, 'classes. Teenagers learn it too.'),
  ];
  const ps = linesToParas(ls);

  check(ps.length >= 1, '确实分出了段落', '实得 ' + ps.length + ' 段');

  // 除最后一段可能是"页面截断"的残句外，每一段都必须以句末标点结尾。
  //  这是用户的硬要求："至少一段的结尾是一句话吧"。
  ps.forEach((p, i) => {
    if (i === ps.length - 1) return;
    check(/[.。!！?？]$/.test(p.trim()),
          '第 ' + (i + 1) + ' 段以句末标点结尾',
          JSON.stringify(p.slice(-30)));
  });

  // 兜底再确认一次：整篇文字拼接后不应丢内容
  const joined = ps.join(' ');
  check(joined.indexOf('spreading') > 0 && joined.indexOf('Teenagers') > 0,
        '合并后内容没有丢');
}

// ---- ⑧ 安全阀：没有句末标点时不能无限合并 ----
console.log('\n没有句末标点时不能把整篇并成一段');
{
  // 造 30 行都没有句末标点的文字（模拟扫描件/公式页提取结果）
  const ls = [];
  for (let i = 0; i < 30; i++) {
    ls.push(L(900 - i * 12, '这是一行没有句末标点的文字用来测试安全阀是否生效'));
  }
  const ps = linesToParas(ls);
  check(ps.length > 1, '没有句末标点时会切开，不会并成一整段',
        '实得 ' + ps.length + ' 段');
  check(ps[0].length <= 460, '每段长度没有失控',
        '第一段 ' + ps[0].length + ' 字');
}

console.log('\n' + '='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
