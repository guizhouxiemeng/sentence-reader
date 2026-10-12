// test-overlay-contract.js —— 检查三个文件之间的「消息协议」是否对得上。
//
// 为什么换成这个测试：
//   原先这里测的是 content.js 里"把 HTML 字符串解析成 DOM"那一步。
//   后来把浮层改成【用 iframe 装扩展自带的 reader_flow.html】，
//   那个自写的解析器连同整套内联界面一起删掉了 —— 旧测试的前提不复存在。
//
//   而真正出过的问题恰恰是"协议对不上"：
//     content.js 里内联了另一套阅读界面，于是 reader_flow.html 里加的功能
//     （自动/手动模式、重新测速、句长启发式、关闭按钮）浮层里全都没有，
//     点图标打开的还是旧界面 —— 改了半天没生效。
//   这类"两份实现分叉"的问题，靠这个测试能在改代码时立刻发现。
//
// 检查内容：
//   ① content.js 的浮层确实是指向扩展自己的 reader_flow.html
//   ② reader_flow.js【发出】的每种消息，background.js 都转发了
//   ③ background.js【转发】给 content.js 的每种消息，content.js 都处理了
//   ④ content.js【发出】的消息（高亮结果等）不需要额外处理
//
// 用法： node tools/test-overlay-contract.js

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const F = {
  content: path.join(ROOT, 'plugin', 'content.js'),
  background: path.join(ROOT, 'plugin', 'background.js'),
  readerFlow: path.join(ROOT, 'plugin', 'reader_flow.js'),
  panel: path.join(ROOT, 'plugin', 'panel.html'),
};

const read = f => fs.readFileSync(f, 'utf8');

// 从源码里收集 `type: 'xxx'` 出现的所有消息名
function typesIn(src) {
  const out = new Set();
  const re = /type\s*:\s*'([A-Za-z][\w]*)'/g;
  let m;
  while ((m = re.exec(src))) out.add(m[1]);
  return out;
}

// 收集 `msg.type === 'xxx'` / `case 'xxx'` 里被处理的类型
function handledIn(src) {
  const out = new Set();
  let m;
  const re1 = /msg\.type\s*===\s*'([A-Za-z][\w]*)'/g;
  while ((m = re1.exec(src))) out.add(m[1]);
  const re2 = /case\s+'([A-Za-z][\w]*)'\s*:/g;
  while ((m = re2.exec(src))) out.add(m[1]);
  return out;
}

let pass = 0, fail = 0;
function check(ok, label, detail) {
  if (ok) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label + (detail ? ('\n      ' + detail) : '')); }
}

console.log('='.repeat(74));
console.log('浮层与消息协议一致性');
console.log('='.repeat(74));

const cSrc = read(F.content);
const bSrc = read(F.background);
const rSrc = read(F.readerFlow);

// ---- ① 浮层指向扩展自己的页面 ----
console.log('\n① 浮层加载的是哪份界面');
check(/chrome\.runtime\.getURL\(\s*'reader_flow\.html'\s*\)/.test(cSrc),
      'content.js 用 chrome.runtime.getURL 加载扩展自带的 reader_flow.html',
      '如果不是，浮层就会加载到别的来源（例如本地服务器），chrome.* 会不可用');

const cTypes = typesIn(cSrc);
check(!/const\s+CSS\s*=/.test(cSrc) && !/const\s+HTML\s*=/.test(cSrc),
      'content.js 里没有第二套界面模板（CSS/HTML）',
      '如果还在，说明又分叉出一份实现 —— reader_flow 里改的东西浮层看不到');

check(/function\s+splitSentences/.test(cSrc) && /function\s+splitSentences/.test(rSrc),
      '两边都有自己的切句函数（各自运行环境不同，允许重复但要都在）');

// ---- ② reader_flow 发出的消息，background 必须转发 ----
console.log('\n② reader_flow.js 发出的消息 -> background.js 是否转发');
const rSends = typesIn(rSrc);
const bTypes = typesIn(bSrc);
const bHandled = handledIn(bSrc);
const OVERLAY_ONLY = new Set(['closeOverlay', 'toggleOverlay', 'isOverlayOpen', 'clearHighlight']);
rSends.forEach(t => {
  check(bHandled.has(t), 'background 处理 ' + t,
        'reader_flow 会发 ' + t + '，但 background 没有对应分支');
});

// ---- ③ background 转给 content 的消息，content 必须处理 ----
console.log('\n③ background.js 转给 content.js 的消息 -> content.js 是否处理');
const cHandled = handledIn(cSrc);
// background 里 chrome.tabs.sendMessage(tabId, { type: 'xxx' }) 的目标
const toContent = new Set();
let m;
const reSend = /chrome\.tabs\.sendMessage\([^,]+,\s*\{\s*type\s*:\s*'([A-Za-z][\w]*)'/g;
while ((m = reSend.exec(bSrc))) toContent.add(m[1]);
// 用变量传类型的情况（例如 { type: 'highlight', ... } 已经在上面覆盖）
toContent.forEach(t => {
  check(cHandled.has(t), 'content 处理 ' + t,
        'background 会转 ' + t + '，但 content.js 没有对应分支');
});

// ---- ④ 关闭链路完整 ----
console.log('\n④ 关闭浮层的链路（reader_flow -> background -> content）');
check(typesIn(rSrc).has('closeOverlay') || /closeOverlay/.test(rSrc),
      'reader_flow 会发 closeOverlay');
check(/closeOverlay/.test(bSrc), 'background 转发 closeOverlay');
check(/msg\.type\s*===\s*'closeOverlay'/.test(cSrc), 'content 处理 closeOverlay');
check(!/toggleOverlay[\s\S]{0,80}closeOverlay/.test(rSrc),
      '关闭用的是 closeOverlay 而不是 toggleOverlay',
      '用 toggle 会出现"已经关了再点又开出来"');

// ---- ⑤ 侧栏与浮层用同一个界面文件 ----
console.log('\n⑤ 两条入口是否共用同一份界面');
const pSrc = read(F.panel);
check(/reader_flow\.html/.test(pSrc), 'panel.html 指向 reader_flow.html');
check(/chrome\.runtime\.getURL\(\s*'reader_flow\.html'\s*\)/.test(cSrc),
      '浮层也指向 reader_flow.html（两条入口同一个界面）');

console.log('\n' + '='.repeat(74));
if (fail === 0) {
  console.log('全部通过 ✓  （' + pass + ' 项）');
} else {
  console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
}
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
