// test-overlay-parse.js —— 验证 content.js 里"把 HTML 字符串变成 DOM"这一步真的能用。
//
// 为什么单独测这一步：
//   浮层界面是一段 HTML 字符串，必须先解析成真正的 DOM 节点，
//   后面的 getElementById + addEventListener 才能工作。
//   早先写成 box.innerHTML = HTML 就以为有节点了，结果
//   root.getElementById('bar') 返回 null，绑定事件时崩在
//   "Cannot read properties of null (reading 'addEventListener')"，
//   表现就是"点了图标什么都不发生"。
//
// 用法： node tools/test-overlay-parse.js

const fs = require('fs');
const path = require('path');

const FILE = path.join(__dirname, '..', 'plugin', 'content.js');
const src = fs.readFileSync(FILE, 'utf8');

// ---- 从源码里抽出 parseHTML 与 HTML 模板，单独跑 ----
const htmlM = src.match(/const HTML = `([\s\S]*?)`;/);
if (!htmlM) { console.error('没找到 HTML 模板'); process.exit(1); }
const TEMPLATE = htmlM[1];

const parseM = src.match(/function parseHTML\(html\) \{[\s\S]*?\n  \}/);
if (!parseM) { console.error('没找到 parseHTML'); process.exit(1); }
const parseSrc = parseM[0];

// ---- 最小 DOM ----
class El {
  constructor(tag) {
    this.tagName = (tag || 'div').toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.style = {};
    this.dataset = {};
    this._class = '';
    this._text = '';
    this.attrs = {};
    this.id = '';
  }
  set className(v) { this._class = v || ''; }
  get className() { return this._class; }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
  get innerText() { return this._text; }
  setAttribute(k, v) { this.attrs[k] = v; }
  appendChild(c) {
    if (c && c.__fragment) {
      // DocumentFragment：把它的子节点搬过来（浏览器行为）
      c.children.slice().forEach(x => this.appendChild(x));
      c.children.length = 0;
      return c;
    }
    c.parentNode = this;
    this.children.push(c);
    return c;
  }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
}

global.document = {
  createElement: t => {
    const e = new El(t);
    if (t === 'template') {
      const frag = new El('fragment');
      frag.__fragment = true;
      Object.defineProperty(e, 'content', { value: frag, enumerable: true });
      // template.innerHTML 的写入要解析进 content
      Object.defineProperty(e, 'innerHTML', {
        set(v) {
          const parsed = parseHTML(v);
          parsed.children.slice().forEach(c => frag.appendChild(c));
        },
        get() { return ''; },
      });
    }
    return e;
  },
  createTextNode: t => { const e = new El('#text'); e.textContent = t; return e; },
};

// 把 parseHTML 定义进当前作用域
eval(parseSrc);

function findById(node, id) {
  if (!node) return null;
  if (node.id === id) return node;
  for (const c of node.children || []) {
    const r = findById(c, id);
    if (r) return r;
  }
  return null;
}

console.log('='.repeat(74));
console.log('浮层 HTML 解析验证');
console.log('='.repeat(74));
console.log('模板长度: ' + TEMPLATE.length + ' 字符');

let tree;
try {
  tree = parseHTML(TEMPLATE);
} catch (e) {
  console.log('!! parseHTML 抛错: ' + e.message);
  process.exit(1);
}

const ids = [];
(function walk(n) {
  if (!n) return;
  if (n.id) ids.push(n.id);
  (n.children || []).forEach(walk);
})(tree);

console.log('解析出的 id (' + ids.length + '):');
console.log('  ' + ids.join(', '));

const need = ['wrap', 'bar', 'doc', 'side', 'cards', 'play', 'prev', 'next',
              'slower', 'faster', 'know', 'close', 'clr', 'cfg', 'prov', 'key',
              'model', 'base', 'saveCfg', 'st', 'cn', 'sideBtn', 'cfgBtn'];
const lost = need.filter(id => !ids.includes(id));

console.log();
if (lost.length) {
  console.log('!! 解析后缺少 ' + lost.length + ' 个元素: ' + lost.join(', '));
  process.exit(1);
} else {
  console.log('OK：解析后 ' + need.length + ' 个关键元素都能找到');
  console.log('    getElementById("bar") 可用: ' + !!findById(tree, 'bar'));
}
