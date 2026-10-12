// verify-package.js —— 核对"压缩包里的东西"和"浏览器加载的那份（plugin/）"是否一致。
//
// 为什么需要（用户问："你确定压缩包内的东西和我测的一样吧"）：
//     我改了代码之后，压缩包是新的，但用户浏览器里加载的还是旧的 ——
//     "重新加载扩展"这个动作只有他会做。
//     而"改了 demo、忘了同步、忘了打包"这类事，我这两天犯过好几次，
//     没有任何检查会拦下来。
//
// 这个脚本把三件事一次核对掉：
//     ① 包内每个文件 vs plugin/ 里的同名文件（逐字节）
//     ② 包内清单 vs plugin/ 清单（有没有漏掉该进包的文件）
//     ③ 打印构建标记（BUILD），并和 plugin/reader_flow.js 里的对比
//
// 【为什么自己解析 ZIP】
//     先写了 Python 版，结果被接进一键校验的【JS 列表】里，用 node 跑就语法错误。
//     与其改校验框架，不如让这个检查用 Node 写 —— 反正 ZIP 的最小读取
//     就是"顺序走本地文件头 + inflate"，几十行。
//     （打包脚本里那个 ZIP 写入器也是这么来的，两边对称。）
//
// 用法： node tools/verify-package.js [zip 路径...]
//       不给参数时，检查 build/ 和桌面上的包。

const fs = require('fs');
const os = require('os');
const path = require('path');
const zlib = require('zlib');

const ROOT = path.resolve(__dirname, '..');
const PLUGIN = path.join(ROOT, 'plugin');

// 打包时明确排除的文件（不该出现在包里，出现了也不算"漏"）
const NOT_PACKED = new Set(['README.md']);

// ---------------------------------------------------------------- 最小 ZIP 读取
//  走本地文件头（0x04034b50）而不是中央目录 —— 打包脚本是自己写的，
//  标志位里没有 bit 3（数据描述符），所以本地头里的长度是可信的。
function readZip(file) {
  const buf = fs.readFileSync(file);
  const entries = [];
  let p = 0;
  while (p + 30 <= buf.length) {
    if (buf.readUInt32LE(p) !== 0x04034b50) break;   // 不是本地文件头，结束
    const flags = buf.readUInt16LE(p + 6);
    const method = buf.readUInt16LE(p + 8);
    const compSize = buf.readUInt32LE(p + 18);
    const rawSize = buf.readUInt32LE(p + 22);
    const nameLen = buf.readUInt16LE(p + 26);
    const extraLen = buf.readUInt16LE(p + 28);
    const name = buf.toString('utf8', p + 30, p + 30 + nameLen);
    const dataStart = p + 30 + nameLen + extraLen;

    if (flags & 0x08) {
      // 有数据描述符的话本地头里的长度不可信 —— 我们的打包器不这么写，
      //  真遇到了直接报出来，不要假装读对了。
      throw new Error('包里有文件用了数据描述符（flags bit3），本读取器不支持：' + name);
    }

    const raw = buf.slice(dataStart, dataStart + compSize);
    const data = method === 0 ? raw : zlib.inflateRawSync(raw);
    if (data.length !== rawSize) {
      throw new Error('解压后长度不符：' + name +
                      '（头里写 ' + rawSize + '，实际 ' + data.length + '）');
    }
    entries.push({ name: name, data: data });
    p = dataStart + compSize;
  }
  return entries;
}

function sha(b) {
  return require('crypto').createHash('sha256').update(b).digest('hex').slice(0, 16);
}

function listPlugin() {
  const out = [];
  const walk = (dir, rel) => {
    fs.readdirSync(dir, { withFileTypes: true }).forEach(it => {
      const abs = path.join(dir, it.name);
      const r = rel ? rel + '/' + it.name : it.name;
      if (it.isDirectory()) walk(abs, r);
      else out.push(r);
    });
  };
  walk(PLUGIN, '');
  return out;
}

function checkZip(zipPath, label) {
  const line = '='.repeat(74);
  console.log(line);
  console.log('核对 ' + label);
  console.log('  ' + zipPath);
  console.log(line);

  if (!fs.existsSync(zipPath)) {
    console.log('  文件不存在');
    console.log('');
    return { ok: false, missing: true };
  }

  let entries;
  try {
    entries = readZip(zipPath);
  } catch (e) {
    console.log('  !! 读不了这个包：' + e.message);
    console.log('');
    return { ok: false };
  }

  console.log('  包内文件 ' + entries.length + ' 个');
  console.log('');

  const diffs = [];
  const missing = [];
  let build = '(没找到)';

  entries.forEach(e => {
    const p = path.join(PLUGIN, e.name.split('/').join(path.sep));
    if (!fs.existsSync(p)) { missing.push(e.name); return; }
    const cur = fs.readFileSync(p);
    if (!cur.equals(e.data)) {
      diffs.push({ name: e.name, a: e.data.length, b: cur.length,
                   ha: sha(e.data), hb: sha(cur) });
    }
    if (/reader_flow\.js$/.test(e.name)) {
      const m = /const BUILD = '([^']+)'/.exec(e.data.toString('utf8'));
      if (m) build = m[1];
    }
  });

  const inZip = new Set(entries.map(e => e.name));
  const extra = listPlugin().filter(r => !NOT_PACKED.has(path.basename(r)) && !inZip.has(r));

  let ok = true;
  if (missing.length) {
    ok = false;
    console.log('  !! 包里有、plugin/ 里没有的：');
    missing.forEach(n => console.log('       ' + n));
  }
  if (diffs.length) {
    ok = false;
    console.log('  !! 内容不一致（说明改了代码但没重新打包）：');
    diffs.forEach(d => {
      console.log('       %s   包 %d 字节(%s)   plugin %d 字节(%s)',
                  d.name, d.a, d.ha, d.b, d.hb);
    });
  }
  if (extra.length) {
    ok = false;
    console.log('  !! plugin/ 里有、包里漏掉的（会少功能）：');
    extra.forEach(n => console.log('       ' + n));
  }

  if (ok) console.log('  ✓ 包里每个文件都和 plugin/ 逐字节一致，且没有遗漏');
  console.log('    构建标记（BUILD）  ' + build);
  console.log('');
  return { ok: ok, build: build };
}

// ---------------------------------------------------------------- 主程序
const args = process.argv.slice(2);
const desktop = path.join(os.homedir(), 'Desktop', 'sentence-reader-1.0.0.zip');
const build = path.join(ROOT, 'build', 'sentence-reader-1.0.0.zip');

const targets = args.length
  ? args.map(a => ({ p: path.resolve(a), label: '指定的包' }))
  : [{ p: build, label: 'build/ 里的包（一键校验用）' },
     { p: desktop, label: '桌面上的包（提交用）' }];

let allOk = true;
let buildTag = null;
targets.forEach(t => {
  const r = checkZip(t.p, t.label);
  if (!r.ok) allOk = false;
  if (r.build && r.build !== '(没找到)') buildTag = r.build;
});

// plugin/ 里两个同步文件的指纹，方便人工核对
console.log('='.repeat(74));
console.log('plugin/ 里关键文件的指纹（人工核对用）');
console.log('='.repeat(74));
['reader_flow.html', 'reader_flow.js', 'content.js', 'manifest.json'].forEach(f => {
  const p = path.join(PLUGIN, f);
  if (!fs.existsSync(p)) return;
  const b = fs.readFileSync(p);
  console.log('  %s  %s  %d 字节', f.padEnd(20), sha(b), b.length);
});
console.log('');
console.log('  构建标记对上了吗：界面上工具栏显示的 BUIILD 应该等于 ' + (buildTag || '（上面那个值）'));
console.log('  如果两者不一样，说明浏览器里加载的还是旧代码 —— 去 edge://extensions 点【重新加载】。');
console.log('');

if (allOk) {
  console.log('全部通过 ✓');
  process.exit(0);
} else {
  console.log('发现不一致，请重新打包： node tools/package.js --desktop');
  process.exit(1);
}
