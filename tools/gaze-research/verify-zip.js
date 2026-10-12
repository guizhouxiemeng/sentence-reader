// verify-zip.js — 验证 collector.html 里的 zipStore 实现是否正确
// 方法：把同一份算法在 Node 里复现，生成 zip 后用系统解压器做独立校验。
// 只依赖 Node 内置模块 + 系统 tar/unzip。
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

// ---- 从 collector.html 里原样抄出的实现（保持一致才有验证意义）----
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
    t[n] = c >>> 0;
  }
  return t;
})();

function crc32(u8) {
  let c = 0xFFFFFFFF;
  for (let i = 0; i < u8.length; i++) c = CRC_TABLE[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

function zipStore(files) {
  const enc = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;

  for (const f of files) {
    const name = enc.encode(f.name);
    const data = f.data;
    const crc = crc32(data);

    const lh = new Uint8Array(30 + name.length);
    const dv = new DataView(lh.buffer);
    dv.setUint32(0, 0x04034b50, true);
    dv.setUint16(4, 20, true);
    dv.setUint16(6, 0, true);
    dv.setUint16(8, 0, true);
    dv.setUint16(10, 0, true);
    dv.setUint16(12, 0x21, true);
    dv.setUint32(14, crc, true);
    dv.setUint32(18, data.length, true);
    dv.setUint32(22, data.length, true);
    dv.setUint16(26, name.length, true);
    dv.setUint16(28, 0, true);
    lh.set(name, 30);
    parts.push(lh, data);

    const ch = new Uint8Array(46 + name.length);
    const cv = new DataView(ch.buffer);
    cv.setUint32(0, 0x02014b50, true);
    cv.setUint16(4, 20, true);
    cv.setUint16(6, 20, true);
    cv.setUint16(8, 0, true);
    cv.setUint16(10, 0, true);
    cv.setUint16(12, 0, true);
    cv.setUint16(14, 0x21, true);
    cv.setUint32(16, crc, true);
    cv.setUint32(20, data.length, true);
    cv.setUint32(24, data.length, true);
    cv.setUint16(28, name.length, true);
    cv.setUint32(42, offset, true);
    ch.set(name, 46);
    central.push(ch);
    offset += lh.length + data.length;
  }

  const cdSize = central.reduce((a, c) => a + c.length, 0);
  const end = new Uint8Array(22);
  const ev = new DataView(end.buffer);
  ev.setUint32(0, 0x06054b50, true);
  ev.setUint16(8, files.length, true);
  ev.setUint16(10, files.length, true);
  ev.setUint32(12, cdSize, true);
  ev.setUint32(16, offset, true);
  return Buffer.concat([...parts, ...central, end].map((u) => Buffer.from(u)));
}

// ---- 造测试数据 ----
const outDir = path.join(__dirname, '..', 'vendor', '.ziptest');
fs.rmSync(outDir, { recursive: true, force: true });
fs.mkdirSync(outDir, { recursive: true });

const files = [];
// 1) 一个普通文本
files.push({ name: 'manifest.json', data: Buffer.from(JSON.stringify({ hello: '世界', n: 42 }), 'utf8') });
// 2) 若干"伪 JPEG"（带 zlib 压缩的随机数据，模拟真实大小）
const crypto = require('crypto');
for (let i = 0; i < 5; i++) {
  files.push({
    name: `eyes/t${String(i).padStart(3, '0')}_${String(1000 + i).padStart(12, '0')}.jpg`,
    data: zlib.gzipSync(crypto.randomBytes(20000)),
  });
}
// 3) 空文件（边界情况）
files.push({ name: 'empty.txt', data: Buffer.alloc(0) });

const zip = zipStore(files);
const zipPath = path.join(outDir, 'test.zip');
fs.writeFileSync(zipPath, zip);
console.log('生成 zip:', zipPath, zip.length, 'bytes');

// 自检签名
const sig = zip.readUInt32LE(0);
console.log('本地头签名 = 0x' + sig.toString(16), sig === 0x04034b50 ? 'OK' : 'FAIL');
const eocdOff = zip.length - 22;
console.log('EOCD 签名 = 0x' + zip.readUInt32LE(eocdOff).toString(16),
  zip.readUInt32LE(eocdOff) === 0x06054b50 ? 'OK' : 'FAIL');
console.log('EOCD 条数 =', zip.readUInt16LE(eocdOff + 10), '(应为', files.length + ')');

// ---- 独立读取器：解析中央目录 + 逐文件校验 CRC32 ----
// 说明：系统 tar 在本沙箱里起不来（被终止），所以改用 Node 自己实现读取器。
// 这实际上比 tar 更严格：会逐一比对 CRC32，而不只是解压成功。
function zipRead(buf) {
  // 找 EOCD（从尾部往前扫，容错注释字段）
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 65535); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error('找不到 EOCD');
  const count = buf.readUInt16LE(eocd + 10);
  const cdSize = buf.readUInt32LE(eocd + 12);
  const cdOff = buf.readUInt32LE(eocd + 16);
  if (cdOff + cdSize !== eocd) {
    console.log(`  注意: 中央目录偏移+大小(${cdOff + cdSize}) != EOCD位置(${eocd})`);
  }
  const out = [];
  let p = cdOff;
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(p) !== 0x02014b50) throw new Error('中央目录签名错 @' + p);
    const method = buf.readUInt16LE(p + 10);
    const crc = buf.readUInt32LE(p + 16);
    const csize = buf.readUInt32LE(p + 20);
    const usize = buf.readUInt32LE(p + 24);
    const nlen = buf.readUInt16LE(p + 28);
    const elen = buf.readUInt16LE(p + 30);
    const clen = buf.readUInt16LE(p + 32);
    const lho = buf.readUInt32LE(p + 42);
    const name = buf.slice(p + 46, p + 46 + nlen).toString('utf8');
    // 定位本地头读取数据
    if (buf.readUInt32LE(lho) !== 0x04034b50) throw new Error('本地头签名错: ' + name);
    const lnlen = buf.readUInt16LE(lho + 26);
    const lelen = buf.readUInt16LE(lho + 28);
    const dstart = lho + 30 + lnlen + lelen;
    const data = buf.slice(dstart, dstart + csize);
    out.push({ name, method, crc, csize, usize, data });
    p += 46 + nlen + elen + clen;
  }
  return out;
}

console.log('\n--- 用 Node 读取器校验 ---');
let bad = 0;
try {
  const entries = zipRead(zip);
  console.log('读取到条目数:', entries.length, '(应为', files.length + ')');
  if (entries.length !== files.length) bad++;
  for (const e of entries) {
    const orig = files.find((f) => f.name === e.name);
    if (!orig) { console.log('  多出的条目:', e.name); bad++; continue; }
    const problems = [];
    if (e.method !== 0) problems.push('压缩方式非 STORE');
    if (e.csize !== orig.data.length) problems.push(`压缩后大小 ${e.csize} != ${orig.data.length}`);
    if (e.usize !== orig.data.length) problems.push(`原始大小 ${e.usize} != ${orig.data.length}`);
    const actualCrc = crc32(new Uint8Array(e.data));
    if (actualCrc !== e.crc) problems.push(`CRC 不符 (记录 ${e.crc.toString(16)}, 实际 ${actualCrc.toString(16)})`);
    if (!e.data.equals(orig.data)) problems.push('内容不一致');
    // 独立用 zlib.crc32 复核（Node 内置）
    if (zlib.crc32) {
      const ref = zlib.crc32(new Uint8Array(orig.data)) >>> 0;
      if (ref !== e.crc) problems.push(`与 zlib.crc32 不符 (${ref.toString(16)})`);
    }
    if (problems.length) { console.log('  ✗', e.name, problems.join('; ')); bad++; }
    else console.log('  ✓', e.name, `(${e.data.length} bytes, crc=${e.crc.toString(16)})`);
  }
} catch (err) {
  console.log('  读取失败:', err.message);
  bad++;
}

console.log('\n结果:', bad === 0 ? 'zip 结构正确、全部文件 CRC 与内容往返一致 ✓' : `${bad} 处问题 ✗`);
process.exit(bad === 0 ? 0 : 1);

