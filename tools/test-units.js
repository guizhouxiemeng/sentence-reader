// test-units.js —— 验证"阅读单位"计数（中文按字、英文按词，空格不计）
//
// 为什么单独测：
//   这是"这句该给多少时间"的基础。数错了，后面的自适应、推断层 ratio 全部失真。
//   现场发现的两个错误：
//     ① 把空格算进字数
//     ② 英文按字母数算（"architectures" = 13 个"字"）
//
// 用法： node tools/test-units.js

const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'demo', 'reader_flow.html');
const src = fs.readFileSync(FILE, 'utf8');

// 抽出 TextSource 模块
const a = src.indexOf('const TextSource = (() => {');
if (a < 0) { console.error('找不到 TextSource'); process.exit(1); }
const k = src.indexOf('{', src.indexOf('=>', a));
let depth = 0, end = -1;
for (let j = k; j < src.length; j++) {
  if (src[j] === '{') depth++;
  else if (src[j] === '}') { depth--; if (depth === 0) { end = j + 1; break; } }
}
const code = src.slice(a, end) + ')();\nmodule.exports = TextSource;\n';
const mod = { exports: {} };
new Function('module', 'exports', code)(mod, mod.exports);
const T = mod.exports;

console.log('='.repeat(78));
console.log('阅读单位计数验证（中文按字 / 英文按词 / 空格不计）');
console.log('='.repeat(78));
console.log();

const cases = [
  {
    name: '英文长句（截图里的真实句子）',
    text: 'For example, the panorama-stitching algorithm can find more matches in source images and synthesize an image of higher quality, given more computation time.',
    lang: 'en',
  },
  {
    name: '英文短句',
    text: 'Back to Top',
    lang: 'en',
  },
  {
    name: '英文单长词',
    text: 'architectures',
    lang: 'en',
  },
  {
    name: '中文句子',
    text: '这是用于验证自适应阅读辅助的一段说明文字，请按平时的习惯阅读。',
    lang: 'zh',
  },
  {
    name: '中英混排',
    text: '这是 OpenCV 的 GPU 模块，性能比 CPU 版本快很多。',
    lang: 'mix',
  },
  {
    name: '含多余空格',
    text: '  In   the    past,   an  easy  way  ',
    lang: 'en',
  },
];

console.log('  句子'.padEnd(30) + '字符数'.padStart(8) + '中文字'.padStart(8) +
            '英文词'.padStart(8) + '单位'.padStart(8) + '  给的时间'.padStart(12));
console.log('  ' + '-'.repeat(76));

const CPS = 5.0, MARGIN = 1.15;
cases.forEach(c => {
  const u = T.units(c.text);
  const sec = u.units / CPS * MARGIN;
  console.log('  ' + c.name.padEnd(28) +
              String(c.text.length).padStart(8) +
              String(u.cjk).padStart(8) +
              String(u.words).padStart(8) +
              String(u.units).padStart(8) +
              (sec.toFixed(1) + 's').padStart(12));
});

console.log();
console.log('='.repeat(78));
console.log('对照：用【字符数】算会错多少（旧做法）');
console.log('='.repeat(78));
console.log('  句子'.padEnd(30) + '字符数'.padStart(8) + '单位'.padStart(8) +
            '旧给时'.padStart(10) + '新给时'.padStart(10) + '  偏差'.padStart(10));
console.log('  ' + '-'.repeat(76));
cases.forEach(c => {
  const u = T.units(c.text);
  const oldSec = Math.max(0.9, Math.min(25, c.text.length / CPS * MARGIN));
  const newSec = Math.max(0.9, Math.min(25, u.units / CPS * MARGIN));
  const diff = oldSec / newSec;
  console.log('  ' + c.name.padEnd(28) +
              String(c.text.length).padStart(8) +
              String(u.units).padStart(8) +
              (oldSec.toFixed(1) + 's').padStart(10) +
              (newSec.toFixed(1) + 's').padStart(10) +
              ((diff >= 1 ? '+' : '') + ((diff - 1) * 100).toFixed(0) + '%').padStart(10));
});

console.log();
console.log('='.repeat(78));
console.log('断言');
console.log('='.repeat(78));

let fail = 0;
function check(name, got, want) {
  const ok = got === want;
  if (!ok) fail++;
  console.log('  ' + (ok ? 'OK  ' : '!!  ') + name.padEnd(46) +
              '得到 ' + got + '，期望 ' + want);
}

// 空格不应影响英文词数
const u1 = T.units('In the past');
const u2 = T.units('  In   the    past  ');
check('英文：多余空格不影响词数', u2.words, u1.words);
check('英文：3 个词', u1.words, 3);
check('英文：空格不计入单位', u1.units, 3);

// 中文按字
const z = T.units('这是测试');
check('中文：4 个字', z.cjk, 4);
check('中文：单位=4', z.units, 4);
check('中文：词数为 0', z.words, 0);

// 长单词只算 1 个单位
const w = T.units('architectures');
check('英文长词只算 1 个单位', w.units, 1);

// 中英混排不重复计数
const mix = T.units('这是 OpenCV 模块');
check('混排：中文 4 字', mix.cjk, 4);
check('混排：英文 1 词', mix.words, 1);
check('混排：共 5 单位', mix.units, 5);

// 标点不计
const p = T.units('Hello, world!');
check('英文：标点不计', p.units, 2);

console.log();
console.log('='.repeat(78));
if (fail === 0) {
  console.log('全部通过 ✓');
} else {
  console.log(fail + ' 项失败');
}
console.log('='.repeat(78));
process.exit(fail ? 1 : 0);
