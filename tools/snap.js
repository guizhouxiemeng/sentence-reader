// snap.js —— 源码快照与对比（替代 git，因为这台机器没装 git）
//
// 为什么需要：
//   排查"原文高亮突然没了"时，我发现【原来能用的 content.js 已经被直接覆盖】，
//   既没法对比改动前后、也没法回退，只能靠记忆猜。
//   那次前后花了十几轮，其中好几轮是在猜"我上次动了什么"。
//
// 这个工具解决的就是这件事，只做三件：
//   save    把当前源码存一份快照（内容没变就不存）
//   diff    对比两份快照，逐行指出改了什么
//   restore 回退到某份快照
//
// 用法：
//   node tools/snap.js save "改了什么"
//   node tools/snap.js list
//   node tools/snap.js diff              # 最近两次
//   node tools/snap.js diff 3 5
//   node tools/snap.js restore 4
//   node tools/snap.js show 4 plugin/content.js
//
// 快照存在 .snapshots/ 下，不进版本库（本来也没有版本库）。

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const ROOT = path.resolve(__dirname, '..');
const DIR = path.join(ROOT, '.snapshots');
const INDEX = path.join(DIR, 'index.json');

// 要跟踪的源码。刻意【不】包含 vendor/ 与 data/ —— 那些是下载来的依赖和样本数据，
// 又大又不该被改，放进来只会让快照又慢又占地方。
const TRACK = [
  'plugin/content.js',
  'plugin/background.js',
  'plugin/reader_flow.html',
  'plugin/reader_flow.js',
  'plugin/panel.html',
  'plugin/panel.js',
  'plugin/manifest.json',
  'plugin/README.md',
  'demo/reader_flow.html',
  'demo/reader_flow.js',
  'PROBLEMS.md',
  'FINDINGS-trigger.md',
  'INTERVIEW.md',
  'JOURNEY.md',
  'README.md',
  'ROADMAP.md',
];

// tools/ 下的脚本也跟踪（它们同样会被改坏）
function toolFiles() {
  const out = [];
  const walk = (rel) => {
    const abs = path.join(ROOT, rel);
    let items = [];
    try { items = fs.readdirSync(abs, { withFileTypes: true }); } catch (e) { return; }
    items.forEach(it => {
      const r = rel + '/' + it.name;
      if (it.isDirectory()) {
        if (it.name === '__pycache__') return;
        walk(r);
      } else if (/\.(js|py|mjs)$/.test(it.name)) {
        out.push(r);
      }
    });
  };
  walk('tools');
  return out;
}

function tracked() {
  return TRACK.concat(toolFiles()).filter(f => fs.existsSync(path.join(ROOT, f)));
}

function readIndex() {
  try { return JSON.parse(fs.readFileSync(INDEX, 'utf8')); } catch (e) { return { snaps: [] }; }
}
function writeIndex(ix) {
  fs.mkdirSync(DIR, { recursive: true });
  fs.writeFileSync(INDEX, JSON.stringify(ix, null, 2));
}

function hashAll(files) {
  const h = crypto.createHash('sha1');
  files.forEach(f => {
    h.update(f);
    try { h.update(fs.readFileSync(path.join(ROOT, f))); } catch (e) { h.update('ERR'); }
  });
  return h.digest('hex').slice(0, 12);
}

// ---------------------------------------------------------------- save
function cmdSave(msg) {
  const files = tracked();
  const hash = hashAll(files);
  const ix = readIndex();
  const last = ix.snaps[ix.snaps.length - 1];
  if (last && last.hash === hash) {
    console.log('  内容和快照 #' + last.id + ' 一样，不用存');
    return 0;
  }
  const id = (last ? last.id : 0) + 1;
  const dir = path.join(DIR, String(id));
  fs.mkdirSync(dir, { recursive: true });
  files.forEach(f => {
    const dst = path.join(dir, f);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(path.join(ROOT, f), dst);
  });
  const rec = {
    id: id,
    at: new Date().toISOString().replace('T', ' ').slice(0, 19),
    msg: msg || '(无说明)',
    hash: hash,
    files: files.length,
  };
  ix.snaps.push(rec);
  writeIndex(ix);
  console.log('  已存快照 #' + id + '　' + rec.at + '　' + rec.msg +
              '（' + files.length + ' 个文件）');
  return 0;
}

// ---------------------------------------------------------------- list
function cmdList() {
  const ix = readIndex();
  if (!ix.snaps.length) { console.log('  还没有快照。用 node tools/snap.js save "说明" 存一份。'); return 0; }
  console.log('  #   时间                  文件  说明');
  ix.snaps.forEach(s => {
    console.log('  ' + String(s.id).padEnd(4) + s.at + '  ' +
                String(s.files).padStart(4) + '  ' + s.msg);
  });
  return 0;
}

// ---------------------------------------------------------------- diff
// 简单的行级差异：先掐掉公共前后缀，中间用 LCS 找增删。
function lineDiff(aText, bText) {
  const A = aText.split('\n'), B = bText.split('\n');
  let s = 0;
  while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let e = 0;
  while (e < A.length - s && e < B.length - s &&
         A[A.length - 1 - e] === B[B.length - 1 - e]) e++;
  const aMid = A.slice(s, A.length - e), bMid = B.slice(s, B.length - e);

  // LCS（中间段一般不长，O(n*m) 可以接受）
  const n = aMid.length, m = bMid.length;
  const dp = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = aMid[i] === bMid[j] ? dp[i + 1][j + 1] + 1
                                     : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (aMid[i] === bMid[j]) { out.push([' ', aMid[i]]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { out.push(['-', aMid[i]]); i++; }
    else { out.push(['+', bMid[j]]); j++; }
  }
  while (i < n) out.push(['-', aMid[i++]]);
  while (j < m) out.push(['+', bMid[j++]]);
  return { head: s, tail: e, hunks: out };
}

function cmdDiff(aId, bId) {
  const ix = readIndex();
  if (!ix.snaps.length) { console.log('  还没有快照'); return 1; }
  const last = ix.snaps[ix.snaps.length - 1];
  const b = bId ? ix.snaps.find(s => s.id === Number(bId)) : last;
  if (!b) { console.log('  找不到快照 ' + bId); return 1; }
  let a;
  if (aId) a = ix.snaps.find(s => s.id === Number(aId));
  else {
    const i = ix.snaps.indexOf(b);
    a = i > 0 ? ix.snaps[i - 1] : null;
  }
  if (!a) { console.log('  没有可对比的上一份快照'); return 1; }

  const dirA = path.join(DIR, String(a.id));
  const dirB = path.join(DIR, String(b.id));
  if (!fs.existsSync(dirB)) { console.log('  快照 ' + b.id + ' 的目录不见了'); return 1; }

  const files = [];
  const walk = (dir, rel) => {
    let items = [];
    try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
    items.forEach(it => {
      const r = rel ? rel + '/' + it.name : it.name;
      if (it.isDirectory()) walk(path.join(dir, it.name), r);
      else files.push(r);
    });
  };
  walk(dirB, '');

  console.log('  对比 快照 #' + a.id + '（' + a.msg + '）  ->  #' + b.id + '（' + b.msg + '）');
  let nChanged = 0, nAdd = 0, nDel = 0;
  files.forEach(rel => {
    const pa = path.join(dirA, rel), pb = path.join(dirB, rel);
    const hasA = fs.existsSync(pa);
    const ta = hasA ? fs.readFileSync(pa, 'utf8') : '';
    const tb = fs.readFileSync(pb, 'utf8');
    if (hasA && ta === tb) return;
    if (!hasA) { console.log('\n  [新增] ' + rel); nAdd++; return; }
    nChanged++;
    const d = lineDiff(ta, tb);
    const ins = d.hunks.filter(h => h[0] === '+').length;
    const del = d.hunks.filter(h => h[0] === '-').length;
    console.log('\n  [改动] ' + rel + '　+' + ins + ' -' + del);
    let shown = 0;
    d.hunks.forEach(([sign, line]) => {
      if (sign === ' ') return;                 // 只显示增删，上下文省略
      if (shown >= 60) { if (shown === 60) console.log('         …（更多改动省略）'); shown++; return; }
      console.log('         ' + sign + ' ' + line.slice(0, 120));
      shown++;
    });
  });

  // 被删掉的文件
  const walkA = [];
  const walkA2 = (dir, rel) => {
    let items = [];
    try { items = fs.readdirSync(dir, { withFileTypes: true }); } catch (e) { return; }
    items.forEach(it => {
      const r = rel ? rel + '/' + it.name : it.name;
      if (it.isDirectory()) walkA2(path.join(dir, it.name), r);
      else walkA.push(r);
    });
  };
  if (fs.existsSync(dirA)) walkA2(dirA, '');
  walkA.forEach(rel => {
    if (!fs.existsSync(path.join(dirB, rel))) { console.log('\n  [删除] ' + rel); nDel++; }
  });

  console.log('\n  合计：改动 ' + nChanged + '　新增 ' + nAdd + '　删除 ' + nDel);
  return 0;
}

// ---------------------------------------------------------------- restore
function cmdRestore(id) {
  const ix = readIndex();
  const s = ix.snaps.find(x => x.id === Number(id));
  if (!s) { console.log('  找不到快照 ' + id); return 1; }
  const dir = path.join(DIR, String(s.id));
  if (!fs.existsSync(dir)) { console.log('  快照目录不见了'); return 1; }

  // 回退前先存一份当前状态，免得回退本身把东西弄丢
  cmdSave('回退到 #' + s.id + ' 之前的自动快照');

  const files = [];
  const walk = (d, rel) => {
    fs.readdirSync(d, { withFileTypes: true }).forEach(it => {
      const r = rel ? rel + '/' + it.name : it.name;
      if (it.isDirectory()) walk(path.join(d, it.name), r);
      else files.push(r);
    });
  };
  walk(dir, '');
  files.forEach(rel => {
    const src = path.join(dir, rel);
    const dst = path.join(ROOT, rel);
    fs.mkdirSync(path.dirname(dst), { recursive: true });
    fs.copyFileSync(src, dst);
  });
  console.log('  已回退 ' + files.length + ' 个文件到快照 #' + s.id + '（' + s.msg + '）');
  return 0;
}

function cmdShow(id, rel) {
  const p = path.join(DIR, String(id), rel);
  if (!fs.existsSync(p)) { console.log('  快照里没有 ' + rel); return 1; }
  process.stdout.write(fs.readFileSync(p, 'utf8'));
  return 0;
}

// ---------------------------------------------------------------- main
const [cmd, ...rest] = process.argv.slice(2);
let code = 1;
if (cmd === 'save') code = cmdSave(rest.join(' '));
else if (cmd === 'list' || !cmd) code = cmdList();
else if (cmd === 'diff') code = cmdDiff(rest[0], rest[1]);
else if (cmd === 'restore') code = cmdRestore(rest[0]);
else if (cmd === 'show') code = cmdShow(rest[0], rest[1]);
else {
  console.log('用法：');
  console.log('  node tools/snap.js save "改了什么"');
  console.log('  node tools/snap.js list');
  console.log('  node tools/snap.js diff [a] [b]');
  console.log('  node tools/snap.js restore <id>');
  console.log('  node tools/snap.js show <id> <文件>');
  code = 1;
}
process.exit(code);
