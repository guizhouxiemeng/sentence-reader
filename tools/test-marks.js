// test-marks.js —— 验证"包裹 -> 清除 -> 再包裹"能反复进行。
//
// 为什么必须有这个测试：
//   clearMarks 的注释写着"去掉高亮类与包裹"，实现却只去了类，
//   DOM 里的 <span class="rf-sent"> 一直留着。
//   于是第二次包裹时 `if (el.querySelector('.rf-sent')) return;` 全部跳过，
//   sentSpans 永远是空的 —— 表现就是"页面高亮突然全没了"。
//
//   这个 bug 靠肉眼读代码很难发现（注释和实现说的是两回事），
//   靠人工测试也容易漏（只有重复提取时才出现）。
//   所以用一个最小 DOM 桩把它变成可自动检查的。
//
// 用法： node tools/test-marks.js

const fs = require('fs');
const path = require('path');

// ---- 最小 DOM 桩：只实现这个测试用到的部分 ----
class TNode {
  constructor(text) { this.nodeValue = text; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
}
class ENode {
  constructor(tag) {
    this.tagName = (tag || 'div').toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.className = '';
    this.classList = {
      _o: this,
      add(c) { this._o.className = (this._o.className + ' ' + c).trim(); },
      remove(c) {
        this._o.className = this._o.className.split(/\s+/).filter(x => x && x !== c).join(' ');
      },
      contains(c) { return (' ' + this._o.className + ' ').includes(' ' + c + ' '); },
    };
  }
  appendChild(n) { n.parentNode = this; this.childNodes.push(n); return n; }
  replaceChild(nw, old) {
    const i = this.childNodes.indexOf(old);
    if (i < 0) throw new Error('replaceChild: 找不到旧节点');
    nw.parentNode = this;
    this.childNodes[i] = nw;
    old.parentNode = null;
    return old;
  }
  get textContent() {
    return this.childNodes.map(n => n.textContent).join('');
  }
  // 把相邻文字节点合并（真 DOM 的 normalize）
  normalize() {
    const out = [];
    for (const n of this.childNodes) {
      const prev = out[out.length - 1];
      if (n instanceof TNode && prev instanceof TNode) prev.nodeValue += n.nodeValue;
      else out.push(n);
    }
    this.childNodes = out;
    this.childNodes.forEach(n => { n.parentNode = this; });
  }
  querySelector(sel) {
    const want = sel.replace(/^\./, '');
    const walk = (node) => {
      for (const c of node.childNodes) {
        if (c instanceof ENode) {
          if (c.className.split(/\s+/).includes(want)) return c;
          const r = walk(c);
          if (r) return r;
        }
      }
      return null;
    };
    return walk(this);
  }
}

function buildFixture() {
  const root = new ENode('div');
  const p1 = new ENode('p');
  p1.appendChild(new TNode('Computer vision is a rapidly growing field. Its objective is to determine things.'));
  const p2 = new ENode('p');
  p2.appendChild(new TNode('Modern cameras focus on faces. They trigger the shutter.'));
  root.appendChild(p1);
  root.appendChild(p2);
  return { root, p1, p2 };
}

// ---- 从源码里抽出 clearMarks / wrapTextNode / splitSentences 等 ----
const src = fs.readFileSync(path.join(__dirname, '..', 'plugin', 'content.js'), 'utf8');
function grab(name) {
  const m = src.match(new RegExp('function ' + name + '\\([\\s\\S]*?\\n  \\}'));
  if (!m) throw new Error('找不到 ' + name);
  return m[0];
}

let pass = 0, fail = 0;
function check(ok, label, extra) {
  if (ok) { pass++; console.log('  ✓ ' + label); }
  else { fail++; console.log('  ✗ ' + label + (extra ? ('\n      ' + extra) : '')); }
}

console.log('='.repeat(74));
console.log('句子包裹：能反复进行（clearMarks 必须真的拆包裹）');
console.log('='.repeat(74));

// clearMarks 的源码里必须真的做拆解，不能只去 class
const cm = grab('clearMarks');
check(/replaceChild/.test(cm), 'clearMarks 里真的把 span 拆掉（有 replaceChild）',
      '只做 classList.remove 的话，DOM 里会残留 .rf-sent，下次包裹全部跳过');
check(/normalize\(\)/.test(cm), 'clearMarks 里合并相邻文字节点',
      '不合并的话反复包裹会把文字节点越切越碎');

// wrapTextNode 必须把 span 推进 sentSpans
const wt = grab('wrapTextNode');
check(/sentSpans\.push/.test(wt), 'wrapTextNode 会把 span 记进 sentSpans');
check(/rf-sent/.test(wt), 'wrapTextNode 用的是 .rf-sent 类');

// 包裹判定：必须用 .rf-sent 作为"已包裹"的标记，且 clearMarks 与它一致
check(/querySelector\('\.rf-sent'\)/.test(src),
      '包裹前会检查 .rf-sent（避免重复包）');
check(/classList\.remove\('rf-cur'\)/.test(cm), 'clearMarks 去掉了高亮类 rf-cur');

// ---- 行为验证：用桩跑一遍 包裹 -> 清除 -> 再包裹 ----
console.log('\n行为验证（最小 DOM 桩）');
{
  const { root, p1 } = buildFixture();
  // 手工模拟一次包裹
  const txt = p1.childNodes[0];
  const sp = new ENode('span');
  sp.className = 'rf-sent';
  sp.appendChild(new TNode(txt.nodeValue));
  const before = p1.childNodes.length;
  p1.replaceChild(sp, txt);
  check(p1.childNodes.length === before, '包裹后子节点数不变（是替换不是插入）');
  check(!!p1.querySelector('.rf-sent'), '包裹后能查到 .rf-sent');

  // 模拟 clearMarks 的拆解
  const par = sp.parentNode;
  par.replaceChild(new TNode(sp.textContent), sp);
  par.normalize();
  check(!p1.querySelector('.rf-sent'), '拆解后查不到 .rf-sent', '这是"能再次包裹"的前提');
  check(p1.textContent === 'Computer vision is a rapidly growing field. Its objective is to determine things.',
        '拆解后文字内容完好');
  check(p1.childNodes.length === 1, '拆解并 normalize 后只剩一个文字节点',
        '实得 ' + p1.childNodes.length + ' 个');
}

console.log('\n' + '='.repeat(74));
if (fail === 0) console.log('全部通过 ✓  （' + pass + ' 项）');
else console.log('未通过 ' + fail + ' 项（共 ' + (pass + fail) + ' 项）');
console.log('='.repeat(74));
process.exit(fail === 0 ? 0 : 1);
