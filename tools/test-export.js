// test-export.js —— 验证讲解导出成 Markdown 的结构化序列化。
//
// 为什么单独测：
//   第一版导出直接用 `card.querySelector('.body').textContent`，
//   结果两个问题：
//     ① .body 里是一堆块级 div，textContent 把它们【不加换行地连起来】
//        -> 导出结果整段挤成一行
//     ② 术语行里的「订正」按钮和「✓ 你的术语表」标记也在 .body 里
//        -> 按钮文字被一起导出去了
//   这两个问题都是"看得见但不会报错"，最适合用测试盯着。
//
// 用法： node tools/test-export.js

const fs = require('fs');
const path = require('path');

// ---- 最小 DOM 桩 ----
class El {
  constructor(tag, cls) {
    this.tagName = tag.toUpperCase();
    this.className = cls || '';
    this.children = [];
    this._text = '';
  }
  append(...kids) { kids.forEach(k => { this.children.push(k); k.parent = this; }); return this; }
  text(str) { this._text = str; return this; }
  get textContent() {
    if (this.children.length) return this._text + this.children.map(c => c.textContent).join('');
    return this._text;
  }
  // 只支持 .cls 和 tag 两种选择器（够用）
  querySelector(sel) {
    const want = sel.replace(/^\./, '').toLowerCase();
    const walk = (node) => {
      for (const c of node.children) {
        if (c.className.split(/\s+/).map(x => x.toLowerCase()).includes(want)) return c;
        if (c.tagName.toLowerCase() === want) return c;
        const r = walk(c);
        if (r) return r;
      }
      return null;
    };
    return walk(this);
  }
}

function makeCard() {
  const card = new El('div', 'card');
  card.append(new El('div', 'idx').text('第 4 句').append(new El('button', 'regen').text('\u27f3')));
  card.append(new El('div', 'src').text('Application areas for computer-vision technology include many more.'));

  const body = new El('div', 'body');
  body.append(new El('div', 'sec').text('【这句在说什么】'));
  body.append(new El('div', 'ln').text('描述了计算机视觉技术应用于各种不同领域。'));
  body.append(new El('div', 'gap'));
  body.append(new El('div', 'sec').text('【词】'));

  const t1 = new El('div', 'term');
  t1.append(new El('span', 'en').text('computer vision'));
  t1.append(new El('span', 'zh').text(' = 计算机视觉 （用计算机处理图像）'));
  t1.append(new El('span', 'badge ok').text('✓ 外部查证'));
  t1.append(new El('button', 'fix').text('订正'));
  body.append(t1);

  const t2 = new El('div', 'term');
  t2.append(new El('span', 'en').text('OpenCV'));
  t2.append(new El('span', 'zh').text(' （开源计算机视觉库）'));
  t2.append(new El('button', 'fix').text('订正'));
  body.append(t2);

  body.append(new El('div', 'gap'));
  body.append(new El('div', 'sec').text('【难点】'));
  body.append(new El('div', 'ln').text('句子结构简单。'));
  card.append(body);

  card.append(new El('div', 'srcstat').text('术语 2 条：外部查证 1 · 模型给出 1'));
  return card;
}

// ---- 从源码里抽出 cardToMarkdown ----
const src = fs.readFileSync(path.join(__dirname, '..', 'demo', 'reader_flow.html'), 'utf8');
const m = src.match(/function cardToMarkdown\(card\) \{[\s\S]*?\n  \}/);
if (!m) { console.log('  找不到 cardToMarkdown'); process.exit(1); }

let pass = 0, fail = 0;
function check(ok, label, extra) {
  if (ok) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label + (extra ? ('\n      ' + extra) : '')); }
}

console.log('='.repeat(74));
console.log('讲解导出为 Markdown');
console.log('='.repeat(74));

// eslint-disable-next-line no-new-func
const cardToMarkdown = new Function('card', m[0] + '\nreturn cardToMarkdown(card);');

const md = cardToMarkdown(makeCard());

check(md.indexOf('## 第 4 句') === 0 || md.startsWith('## 第 4 句'),
      '第一行是「## 第 N 句」', JSON.stringify(md.slice(0, 40)));

check(md.split('\n').length >= 10,
      '有分段（不是挤成一行）', '实得 ' + md.split('\n').length + ' 行');
check(md.indexOf('\n\n') >= 0, '有空行分隔');

check(/\n> Application areas/.test(md), '原句以引用块（>）给出');
check(/^【这句在说什么】$/m.test(md), '分节标题独占一行');
check(/^【词】$/m.test(md), '【词】独占一行');
check(/^【难点】$/m.test(md), '【难点】独占一行');

check(/^- computer vision = 计算机视觉 （用计算机处理图像）　`✓ 外部查证`$/m.test(md),
      '术语行写成 Markdown 列表，带译名与来源',
      JSON.stringify((md.match(/^- computer vision.*$/m) || [''])[0]));

check(/^- OpenCV （开源计算机视觉库）$/m.test(md),
      '没有来源的术语行不带来源标记',
      JSON.stringify((md.match(/^- OpenCV.*$/m) || [''])[0]));

check(md.indexOf('订正') < 0, '不包含「订正」按钮文字',
      '导出里出现了按钮文字：' + JSON.stringify((md.match(/.*订正.*/) || [''])[0]));
check(md.indexOf('\u27f3') < 0, '不包含 ⟳ 按钮符号');
check(md.indexOf('术语 2 条') >= 0, '末尾带来源统计');

check(md.indexOf('\n\n\n') < 0, '没有连续多个空行');

// ---------------------------------------------------------------- UI 状态残留
console.log('\n\u2460 内联样式不会残留（失败一次之后不该一直红）');
{
  // fail() 会设 b.style.color = '#ff6b6b'，而 fill() 只改文字。
  //  不显式清掉的话，内联样式会一直生效 —— 表现就是"这句永远是红的"。
  const panelSrc = (function () {
    const a = src.indexOf('const SidePanel = (() => {');
    const b = src.indexOf('const App = (() => {');
    return src.slice(a, b > a ? b : src.length);
  })();

  const sets = (panelSrc.match(/\.style\.color\s*=\s*'[^']+'/g) || []);
  const clears = (panelSrc.match(/\.style\.color\s*=\s*''/g) || []);

  check(sets.length > 0, 'SidePanel 里确实有设内联颜色的地方（否则这条检查没意义）',
        '实得 ' + sets.length + ' 处');
  check(clears.length > 0, '也存在清空内联颜色的地方',
        '设了 ' + sets.length + ' 处、清空 ' + clears.length + ' 处 —— ' +
        '只设不清会导致颜色残留');

  // fill 必须清颜色
  const fillM = panelSrc.match(/function fill\(card, result\) \{[\s\S]*?\n  \}/);
  check(!!fillM && /\.style\.color\s*=\s*''/.test(fillM[0]),
        'fill() 会把内联颜色清掉',
        'fill 是"重新显示内容"的地方，不清颜色的话失败后的红色会一直留着');

  // 重新生成的进行中状态也要清
  const regenM = panelSrc.match(/function bindRegen\(card\) \{[\s\S]*?\n  \}/);
  check(!!regenM && /\.style\.color\s*=\s*''/.test(regenM[0]),
        '重新生成时也会清掉旧颜色');
}

console.log('\n--- 导出样例 ---');
console.log(md.split('\n').map(l => '  | ' + l).join('\n'));
console.log();

console.log('='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
