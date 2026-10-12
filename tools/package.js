// package.js —— 把扩展打包成可提交的 zip，并做提交前自检。
//
// 为什么自己写 ZIP：
//   这台机器没装 7z，也不该为了打包去装依赖。
//   ZIP 的最小实现是"本地文件头 + 数据 + 中央目录 + 结尾记录"，
//   deflate 用 Node 自带的 zlib 就行。（PNG 图标也是这么生成的。）
//
// 为什么先自检再打包：
//   商店上传失败最常见的原因不是代码问题，是包里少了文件或多了不该有的东西 ——
//   manifest 里引用的图标没带上、把 README 和 tools 一起塞进去了。
//   所以打包前把 manifest 引用的每个文件都核一遍。
//
// 用法：
//   node tools/package.js            打包到 build/（仓库内，供一键校验调用）
//   node tools/package.js --desktop   打包到桌面（交付用）
//   node tools/package.js --out DIR   打包到指定目录
//
// 为什么默认不写桌面：
//   它被接进了一键校验（verify_all）。校验应当只动工作区内的东西 ——
//   每次都往桌面丢一个 zip，既吵又可能被沙箱拦下（校验就整体失败了）。
//   交付那一次显式加 --desktop。

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.resolve(__dirname, '..');
const SRC = path.join(ROOT, 'plugin');

// 只打包运行时需要的东西。
//  明确列白名单，不用"排除法" —— 排除法一旦漏了就会把文档、脚本、样本数据打进去。
const INCLUDE_FILES = [
  'manifest.json',
  'background.js',
  'content.js',
  'panel.html',
  'panel.js',
  'reader_flow.html',
  'reader_flow.js',
];
const INCLUDE_DIRS = [
  'icons',
  '_locales',
  'vendor',
];
// 这些即使在被包含的目录里也要跳过
const SKIP = new Set(['.DS_Store', 'Thumbs.db', 'README.md', '.gitkeep']);

// ---------------------------------------------------------------- ZIP 写入
const CRC_TABLE = (() => {
  const t = new Int32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xedb88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c;
  }
  return t;
})();
function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function dosTime(d) {
  return ((d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1)) & 0xffff;
}
function dosDate(d) {
  return (((d.getFullYear() - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()) & 0xffff;
}

function makeZip(entries) {
  // entries: [{ name, data:Buffer }]
  const now = new Date();
  const t = dosTime(now), dt = dosDate(now);
  const locals = [];
  const centrals = [];
  let offset = 0;

  entries.forEach(e => {
    const nameBuf = Buffer.from(e.name, 'utf8');
    const comp = zlib.deflateRawSync(e.data, { level: 9 });
    const crc = crc32(e.data);

    const lh = Buffer.alloc(30);
    lh.writeUInt32LE(0x04034b50, 0);
    lh.writeUInt16LE(20, 4);          // version needed
    lh.writeUInt16LE(0x0800, 6);      // flags: UTF-8 文件名
    lh.writeUInt16LE(8, 8);           // method: deflate
    lh.writeUInt16LE(t, 10);
    lh.writeUInt16LE(dt, 12);
    lh.writeUInt32LE(crc, 14);
    lh.writeUInt32LE(comp.length, 18);
    lh.writeUInt32LE(e.data.length, 22);
    lh.writeUInt16LE(nameBuf.length, 26);
    lh.writeUInt16LE(0, 28);
    locals.push(lh, nameBuf, comp);

    const ch = Buffer.alloc(46);
    ch.writeUInt32LE(0x02014b50, 0);
    ch.writeUInt16LE(20, 4);          // version made by
    ch.writeUInt16LE(20, 6);          // version needed
    ch.writeUInt16LE(0x0800, 8);
    ch.writeUInt16LE(8, 10);
    ch.writeUInt16LE(t, 12);
    ch.writeUInt16LE(dt, 14);
    ch.writeUInt32LE(crc, 16);
    ch.writeUInt32LE(comp.length, 20);
    ch.writeUInt32LE(e.data.length, 24);
    ch.writeUInt16LE(nameBuf.length, 28);
    ch.writeUInt16LE(0, 30);          // extra
    ch.writeUInt16LE(0, 32);          // comment
    ch.writeUInt16LE(0, 34);          // disk
    ch.writeUInt16LE(0, 36);          // internal attrs
    ch.writeUInt32LE(0, 38);          // external attrs
    ch.writeUInt32LE(offset, 42);
    centrals.push(ch, nameBuf);

    offset += lh.length + nameBuf.length + comp.length;
  });

  const cd = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(0, 4);
  end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(cd.length, 12);
  end.writeUInt32LE(offset, 16);
  end.writeUInt16LE(0, 20);

  return Buffer.concat([...locals, cd, end]);
}

// ---------------------------------------------------------------- 收集文件
function collect() {
  const out = [];
  const add = (abs, rel) => {
    const base = path.basename(abs);
    if (SKIP.has(base)) return;
    out.push({ name: rel.split(path.sep).join('/'), data: fs.readFileSync(abs) });
  };
  INCLUDE_FILES.forEach(f => {
    const p = path.join(SRC, f);
    if (fs.existsSync(p)) add(p, f);
  });
  const walk = (dir, rel) => {
    fs.readdirSync(dir, { withFileTypes: true }).forEach(it => {
      const abs = path.join(dir, it.name);
      const r = path.join(rel, it.name);
      if (it.isDirectory()) walk(abs, r);
      else add(abs, r);
    });
  };
  INCLUDE_DIRS.forEach(d => {
    const p = path.join(SRC, d);
    if (fs.existsSync(p)) walk(p, d);
  });
  return out;
}

// ---------------------------------------------------------------- 自检
function validate(entries) {
  const errs = [];
  const names = new Set(entries.map(e => e.name));

  // ① manifest 能解析
  const mf = entries.find(e => e.name === 'manifest.json');
  if (!mf) { errs.push('包里没有 manifest.json'); return { errs, manifest: null }; }
  let m = null;
  try { m = JSON.parse(mf.data.toString('utf8')); }
  catch (e) { errs.push('manifest.json 不是合法 JSON：' + e.message); return { errs, manifest: null }; }

  // ② manifest 引用的文件必须在包里
  const refs = [];
  (function dig(v) {
    if (typeof v === 'string') {
      // 只挑"看起来是文件路径"的字符串（跳过 URL、__MSG_ 占位、权限名）
      if (/\.(js|html|png|json|mjs)$/.test(v) && !/^https?:/.test(v)) refs.push(v);
    } else if (Array.isArray(v)) v.forEach(dig);
    else if (v && typeof v === 'object') Object.values(v).forEach(dig);
  })(m);
  refs.forEach(r => { if (!names.has(r)) errs.push('manifest 引用了但包里没有：' + r); });

  // ③ host_permissions 存在时给个提醒（不是错误）
  const broad = (m.host_permissions || []).some(x => /\*/.test(x));

  // ④ 不该有的东西
  ['README.md', 'package.json'].forEach(x => {
    if (names.has(x)) errs.push('包里不该有：' + x);
  });

  // ⑤ 图标齐全
  ['icons/icon16.png', 'icons/icon48.png', 'icons/icon128.png'].forEach(x => {
    if (!names.has(x)) errs.push('缺图标：' + x);
  });

  // ⑥ 本地化：default_locale 对应的 messages.json 必须存在
  if (m.default_locale) {
    const want = '_locales/' + m.default_locale + '/messages.json';
    if (!names.has(want)) errs.push('default_locale 是 ' + m.default_locale + '，但缺 ' + want);
  }

  // ⑦ __MSG_ 占位必须在 messages.json 里有对应键
  const msgUsed = [];
  (function dig2(v) {
    if (typeof v === 'string') {
      const mm = /__MSG_([A-Za-z0-9_]+)__/.exec(v);
      if (mm) msgUsed.push(mm[1]);
    } else if (Array.isArray(v)) v.forEach(dig2);
    else if (v && typeof v === 'object') Object.values(v).forEach(dig2);
  })(m);
  if (msgUsed.length) {
    const loc = entries.find(e => e.name === '_locales/' + (m.default_locale || 'zh_CN') + '/messages.json');
    if (loc) {
      let keys = [];
      try { keys = Object.keys(JSON.parse(loc.data.toString('utf8'))); } catch (e) { void e; }
      msgUsed.forEach(k => {
        if (!keys.includes(k)) errs.push('manifest 用了 __MSG_' + k + '__，但 messages.json 里没有这个键');
      });
    }
  }

  // ⑧ 本地化文案的长度
  //
  //  商店会逐语言校验 name / description 的长度：
  //      Chrome  description <= 132    name <= 45
  //      Edge    description <= 190    name <= 45
  //  按【132】卡 —— 一份包两个店都能用，不必维护两份文案。
  //
  //  这条是提交被拒之后补的：英文简介写了 212 字符，
  //  而中文那条只有 46，本地怎么试都发现不了。
  const LIMITS = { name: 45, description: 132 };
  entries.forEach(e => {
    const mm = /^_locales\/([^/]+)\/messages\.json$/.exec(e.name);
    if (!mm) return;
    const loc = mm[1];
    let msgs = null;
    try { msgs = JSON.parse(e.data.toString('utf8')); } catch (err) {
      errs.push(loc + '/messages.json 不是合法 JSON：' + err.message);
      return;
    }
    Object.keys(msgs).forEach(k => {
      const val = msgs[k] && msgs[k].message;
      if (typeof val !== 'string') return;
      const isName = (k === 'appName');
      const isDesc = (k === 'appDescription');
      if (!isName && !isDesc) return;
      const limit = isName ? LIMITS.name : LIMITS.description;
      const kind = isName ? 'name' : 'description';
      if (val.length > limit) {
        errs.push('[' + loc + '] ' + kind + ' 超长：' + val.length +
                  ' 字符（上限 ' + limit + '）—— 商店会因此拒收');
      }
    });
  });

  // ⑨ 体积
  const total = entries.reduce((a, e) => a + e.data.length, 0);
  const big = entries.filter(e => e.data.length > 4 * 1024 * 1024).map(e => e.name);

  return { errs, manifest: m, broad, total, big, refs: refs.length, msgUsed, version: m.version };
}

// ---------------------------------------------------------------- 主程序
const args = process.argv.slice(2);
const outIdx = args.indexOf('--out');
const toDesktop = args.indexOf('--desktop') >= 0;
const desktop = path.join(process.env.USERPROFILE || '', 'Desktop');
const outDir = outIdx >= 0 ? path.resolve(args[outIdx + 1])
             : (toDesktop ? desktop : path.join(ROOT, 'build'));

console.log('='.repeat(74));
console.log('扩展打包');
console.log('='.repeat(74));
console.log('');

const entries = collect();
const v = validate(entries);

console.log('  文件清单（' + entries.length + ' 个）：');
entries.forEach(e => {
  console.log('    ' + e.name.padEnd(38) + (e.data.length / 1024).toFixed(1).padStart(8) + ' KB');
});
console.log('');

if (v.errs.length) {
  console.log('  自检未通过：');
  v.errs.forEach(e => console.log('    ✗ ' + e));
  console.log('');
  process.exit(1);
}

console.log('  自检通过 ✓');
console.log('    manifest 版本      ' + v.version);
// 把构建标记打出来 —— 它是"这一版代码"的唯一标识，
//  和界面上工具栏显示的那个是同一个值。
//  有了它，"你测的是不是这个包"不用再靠记时间线。
{
  const jsEntry = entries.find(e => /reader_flow\.js$/.test(e.name));
  const bm = jsEntry && /const BUILD = '([^']+)'/.exec(jsEntry.data.toString('utf8'));
  console.log('    构建标记（BUILD）  ' + (bm ? bm[1] : '(没找到)'));
}
console.log('    manifest 引用文件  ' + v.refs + ' 个，全部在包里');
console.log('    __MSG_ 占位        ' + (v.msgUsed.length ? v.msgUsed.join(', ') : '（无）'));
  console.log('    解压后总大小       ' + (v.total / 1024 / 1024).toFixed(2) + ' MB');
  // 把各语言文案的长度打出来 —— 商店按长度卡，本地就该看得见
  entries.filter(e => /^_locales\//.test(e.name)).forEach(e => {
    const loc = e.name.split('/')[1];
    let msgs = {};
    try { msgs = JSON.parse(e.data.toString('utf8')); } catch (err) { void err; }
    const nm = (msgs.appName || {}).message || '';
    const ds = (msgs.appDescription || {}).message || '';
    const mark = (x, lim) => x.length > lim ? ('  !! 超过 ' + lim) : '';
    console.log('    文案 [' + loc + ']  name ' + nm.length + '/45' + mark(nm, 45) +
                '   description ' + ds.length + '/132' + mark(ds, 132));
  });
if (v.big.length) console.log('    大于 4MB 的文件    ' + v.big.join(', '));
if (v.broad) {
  console.log('');
  console.log('  提醒：host_permissions 申请了全部站点。');
  console.log('        提交时务必把 store/permissions.md 里的理由填进审核表单 ——');
  console.log('        留空是这个权限最常见的被拒原因。');
}

const zip = makeZip(entries);
fs.mkdirSync(outDir, { recursive: true });
const fname = 'sentence-reader-' + v.version + '.zip';
const outPath = path.join(outDir, fname);
fs.writeFileSync(outPath, zip);

console.log('');
console.log('  已生成：' + outPath);
console.log('           ' + (zip.length / 1024 / 1024).toFixed(2) + ' MB');
console.log('');
console.log('  下一步：');
console.log('    ① 到商店后台上传这个 zip');
console.log('    ② 商店文案    store/listing.md');
console.log('    ③ 权限理由    store/permissions.md');
console.log('    ④ 隐私政策    store/privacy-site/（发布流程见该目录的 README）');
console.log('    ⑤ 逐项核对    store/checklist.md');
console.log('');
