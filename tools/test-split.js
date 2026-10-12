// test-split.js —— 切句规则的回归测试。
//
// 为什么必须有这个测试：
//   切句错一次，整篇文章就全乱了，而且很难一眼看出来。
//   实测就踩过：小数点的点被当成句末，
//     "r = −.03"  切成  "r = −" + "03)"
//     "准确率 0.87" 切成  "准确率 0." + "87"
//   这个 bug 影响所有含小数点的文章，不只 PDF。
//
// 还要保证两个文件的切句实现【完全一致】：
//   reader_flow.html 的 TextSource.splitSentences 决定读哪些句子
//   content.js 的 splitSentences 决定在原文里高亮哪一段
//   不一致的话高亮按文本匹配就找不到，会退化成整段高亮。
//
// 用法： node tools/test-split.js

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');

// 从源码里抽出 splitSentences + ABBR + isPeriodEnd，拼成可执行片段。
//  不直接 require 是因为这两个文件不是模块（一个是 html 内嵌脚本）。
const abbrLines = [];
function extract(file, label) {
  const src = fs.readFileSync(file, 'utf8');
  const parts = [];

  const abbr = src.match(/const ABBR = [^\n]+/);
  if (!abbr) throw new Error(label + ' 里找不到 ABBR');
  // 缩写表也必须逐字一致 —— 它直接决定切句结果。
  //  实测就发现过两份的缩写表不同（一份多了 approx|al），
  //  这会让同一段文字在两处切出不同的句子，高亮随即错位。
  abbrLines.push(abbr[0].trim());
  const abbrBody = abbr[0].replace(/^\s*const ABBR = /, '').replace(/;\s*$/, '');
  parts.push('const ABBR = ' + abbrBody + ';');

  for (const fn of ['splitSentences', 'isPeriodEnd']) {
    const re = new RegExp('function ' + fn + '\\([\\s\\S]*?\\n  \\}', 'm');
    const m = src.match(re);
    if (!m) throw new Error(label + ' 里找不到 ' + fn);
    parts.push(m[0]);
  }
  return parts.join('\n\n');
}

const codeA = extract(path.join(ROOT, 'demo', 'reader_flow.html'), 'reader_flow.html');
const codeB = extract(path.join(ROOT, 'plugin', 'content.js'), 'content.js');

function build(code) {
  // eslint-disable-next-line no-new-func
  return new Function(code + '\nreturn splitSentences;')();
}
const splitA = build(codeA);
const splitB = build(codeB);

// ---------------------------------------------------------------- 用例
// [输入, 期望切出的句子数组]
const CASES = [
  // ---- 小数点：本次修的核心问题 ----
  ['anger (k = 6, r = −.03), or reactance.',
   ['anger (k = 6, r = −.03), or reactance.']],
  ['处理一帧需要 30.5 毫秒。下一句在这里。',
   ['处理一帧需要 30.5 毫秒。', '下一句在这里。']],
  ['准确率 0.87 已经很高了。',
   ['准确率 0.87 已经很高了。']],
  ['版本 4.6.82 发布了.',
   ['版本 4.6.82 发布了.']],

  // ---- 分号不断句（用户实测：学术写作里分号分隔并列分句）----
  ['Results showed anger (k = 28, r = .21); negative cognitions (k = 6, r = -0.03), or reactance.',
   ['Results showed anger (k = 28, r = .21); negative cognitions (k = 6, r = -0.03), or reactance.']],
  ['三个条件分别是：速度、准确率和稳定性；它们同样重要。',
   ['三个条件分别是：速度、准确率和稳定性；它们同样重要。']],

  // ---- 用户截图里的原句：这是两句，必须在 samadhi). [2] 处切开 ----
  ['[1] Dhyana is the generic Sanskrit term for meditation, which in the Yoga Sutras refers to both the level of inward contemplation in the broadest sense and more technically to the intermediate state between pure attention to an object (dharana) and complete absorption in it (samadhi). [2] The earliest known reference to such practice on the Indian subcontinent occurs on one of the seals.',
   ['[1] Dhyana is the generic Sanskrit term for meditation, which in the Yoga Sutras refers to both the level of inward contemplation in the broadest sense and more technically to the intermediate state between pure attention to an object (dharana) and complete absorption in it (samadhi).',
    '[2] The earliest known reference to such practice on the Indian subcontinent occurs on one of the seals.']],

  // ---- 句末后跟引用编号 / 方括号（学术写作极常见）----
  ['Dhyana is the Sanskrit term for meditation, which refers to inward contemplation (samadhi). [2] The earliest known reference occurs on a seal.',
   ['Dhyana is the Sanskrit term for meditation, which refers to inward contemplation (samadhi).',
    '[2] The earliest known reference occurs on a seal.']],
  ['这是第一句。［1］这是第二句。',
   ['这是第一句。', '［1］这是第二句。']],
  ['He paused. \u300eThen he left.\u300f',
   ['He paused.', '\u300eThen he left.\u300f']],
  // 加了 [ 之后不能把缩写误伤
  ['Fig. 3 shows the result clearly.',
   ['Fig. 3 shows the result clearly.']],
  ['This was shown before (see et al. (2015) for details).',
   ['This was shown before (see et al. (2015) for details).']],

  // ---- 缩写 ----
  ['See Fig. 3 for details. Then continue.',
   ['See Fig. 3 for details.', 'Then continue.']],
  ['As shown by Smith et al. (2015) in that work. Next.',
   ['As shown by Smith et al. (2015) in that work.', 'Next.']],
  ['Use it, e.g. for images. Done.',
   ['Use it, e.g. for images.', 'Done.']],

  // ---- 正常句末 ----
  ['This is one. This is two. This is three.',
   ['This is one.', 'This is two.', 'This is three.']],
  ['第一句。第二句！第三句？',
   ['第一句。', '第二句！', '第三句？']],
  ['He said "stop." Then he left.',
   ['He said "stop."', 'Then he left.']],

  // ---- 不该被切开的边界 ----
  ['Visit example.com for more.',
   ['Visit example.com for more.']],
  ['The values were 1.5, 2.25 and 3.125 in total.',
   ['The values were 1.5, 2.25 and 3.125 in total.']],
  ['它下降了 12.5%。',
   ['它下降了 12.5%。']],

  // ---- 结尾没有标点 ----
  ['没有结尾标点的一段话',
   ['没有结尾标点的一段话']],

  // ---- 句末点后面是小写（英文里少见，但不该断） ----
  ['outcomes. we conducted more.',
   ['outcomes. we conducted more.']],
];

console.log('='.repeat(74));
console.log('切句规则回归测试');
console.log('='.repeat(74));
console.log('  两份实现长度：reader_flow %d，content %d', codeA.length, codeB.length);
console.log();

let pass = 0, fail = 0;

// 先确认两份实现一致
if (abbrLines[0] !== abbrLines[1]) {
  fail++;
  console.log('  ✗ 两份 ABBR 缩写表不一致！');
  console.log('     reader_flow: ' + abbrLines[0]);
  console.log('     content.js : ' + abbrLines[1]);
  console.log('     缩写表不同会导致同一段文字在两处切出不同的句子。');
} else {
  pass++;
  console.log('  ✓ 两份 ABBR 缩写表一致');
}

if (codeA.trim() !== codeB.trim()) {
  fail++;
  console.log('  ✗ 两份 splitSentences 实现不一致！');
  console.log('     高亮会按文本匹配失败，退化成整段高亮。');
  console.log('     reader_flow.html 的与 content.js 的必须逐字相同。');
} else {
  pass++;
  console.log('  ✓ 两份实现完全一致');
}
console.log();

CASES.forEach(([input, want]) => {
  const ga = splitA(input);
  const gb = splitB(input);
  const okA = JSON.stringify(ga) === JSON.stringify(want);
  const okB = JSON.stringify(gb) === JSON.stringify(want);
  const agree = JSON.stringify(ga) === JSON.stringify(gb);
  if (okA && okB && agree) {
    pass++;
    console.log('  ✓ ' + JSON.stringify(input.slice(0, 46)));
  } else {
    fail++;
    console.log('  ✗ ' + JSON.stringify(input));
    console.log('      期望: ' + JSON.stringify(want));
    console.log('      实得: ' + JSON.stringify(ga));
    if (!agree) {
      console.log('      两份不一致！ content: ' + JSON.stringify(gb));
    }
  }
});

console.log();
console.log('='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
