// inspect-eyezip.js — 校验眼部图像 zip，并确认它是 CNN 能吃的格式
const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const zipPath = process.argv[2];
if (!zipPath || !fs.existsSync(zipPath)) {
  console.log('用法: node tools/inspect-eyezip.js <eyes.zip>');
  process.exit(1);
}
const buf = fs.readFileSync(zipPath);
console.log('文件:', path.basename(zipPath), (buf.length / 1048576).toFixed(1), 'MB');

// --- EOCD ---
let eocd = -1;
for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 65535); i--) {
  if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
}
if (eocd < 0) { console.log('✗ 找不到 EOCD，zip 损坏'); process.exit(1); }
const count = buf.readUInt16LE(eocd + 10);
const cdSize = buf.readUInt32LE(eocd + 12);
const cdOff = buf.readUInt32LE(eocd + 16);
console.log('EOCD: 条目数 =', count, ' 中央目录偏移 =', cdOff, ' 大小 =', cdSize);
if (cdOff + cdSize !== eocd) console.log('  ⚠ 中央目录与 EOCD 位置不吻合');

// --- 遍历中央目录 ---
const entries = [];
let p = cdOff;
for (let i = 0; i < count; i++) {
  if (buf.readUInt32LE(p) !== 0x02014b50) { console.log('✗ 中央目录签名错 @', p); break; }
  const method = buf.readUInt16LE(p + 10);
  const crc = buf.readUInt32LE(p + 16);
  const csize = buf.readUInt32LE(p + 20);
  const usize = buf.readUInt32LE(p + 24);
  const nlen = buf.readUInt16LE(p + 28);
  const elen = buf.readUInt16LE(p + 30);
  const clen = buf.readUInt16LE(p + 32);
  const lho = buf.readUInt32LE(p + 42);
  const name = buf.slice(p + 46, p + 46 + nlen).toString('utf8');
  const lnlen = buf.readUInt16LE(lho + 26);
  const lelen = buf.readUInt16LE(lho + 28);
  const dstart = lho + 30 + lnlen + lelen;
  entries.push({ name, method, crc, size: csize, usize, data: buf.slice(dstart, dstart + csize) });
  p += 46 + nlen + elen + clen;
}

const jpgs = entries.filter((e) => e.name.endsWith('.jpg'));
const manifest = entries.find((e) => e.name === 'manifest.json');
console.log('\n条目统计:');
console.log('  jpg 图像 :', jpgs.length);
console.log('  manifest :', manifest ? '有' : '无！');
console.log('  其他     :', entries.length - jpgs.length - (manifest ? 1 : 0));

// --- 校验 JPEG 与 CRC ---
function crc32(u8) {
  const t = (() => { const a = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1); a[n] = c >>> 0; } return a; })();
  let c = 0xFFFFFFFF;
  for (let i = 0; i < u8.length; i++) c = t[(c ^ u8[i]) & 0xFF] ^ (c >>> 8);
  return (c ^ 0xFFFFFFFF) >>> 0;
}

let badCrc = 0, badJpeg = 0, badSize = 0;
const sizes = [];
for (const e of jpgs) {
  if (crc32(new Uint8Array(e.data)) !== e.crc) badCrc++;
  // JPEG 魔数 FFD8 开头，FFD9 结尾
  if (!(e.data[0] === 0xFF && e.data[1] === 0xD8)) badJpeg++;
  else if (!(e.data[e.data.length - 2] === 0xFF && e.data[e.data.length - 1] === 0xD9)) badJpeg++;
  if (e.size !== e.usize) badSize++;
  sizes.push(e.size);
}
sizes.sort((a, b) => a - b);
console.log('\n图像校验:');
console.log('  CRC 错误      :', badCrc, '/', jpgs.length);
console.log('  非合法 JPEG   :', badJpeg);
console.log('  大小字段不一致:', badSize);
if (sizes.length) {
  console.log('  单张字节 min/中位/max = %d / %d / %d', sizes[0], sizes[Math.floor(sizes.length / 2)], sizes[sizes.length - 1]);
  console.log('  估计解码后尺寸: 应为 144x72（左眼|右眼并排）');
}

// --- 解析 manifest，检查标签完整性 ---
if (manifest) {
  try {
    const m = JSON.parse(manifest.data.toString('utf8'));
    const idx = m.index || [];
    console.log('\nmanifest:');
    console.log('  条目数        :', idx.length, '(应等于 jpg 数', jpgs.length + ')');
    console.log('  layout        :', m.layout);
    const names = new Set(jpgs.map((e) => e.name));
    const missing = idx.filter((r) => !names.has(r.name));
    console.log('  manifest 指向缺失的文件:', missing.length);
    const f0 = idx[0];
    if (f0) {
      console.log('  样例: trial=%s tx=%s ty=%s 特征维度=%s', f0.trial, f0.tx, f0.ty, (f0.f || []).length);
    }
    const trials = new Set(idx.map((r) => r.trial));
    console.log('  覆盖试次数    :', trials.size);
    // 每个试次的图像数（反映稳定期帧数）
    const perTrial = {};
    idx.forEach((r) => { perTrial[r.trial] = (perTrial[r.trial] || 0) + 1; });
    const vals = Object.values(perTrial);
    console.log('  每试次图像数 min/中位/max = %d / %d / %d',
      Math.min(...vals), vals.sort((a, b) => a - b)[Math.floor(vals.length / 2)], Math.max(...vals));
    if (m.meta && m.meta.featureNames) {
      console.log('  manifest 里的 featureNames:', m.meta.featureNames.length, '维');
    }
  } catch (e) {
    console.log('  manifest 解析失败:', e.message);
  }
}

// --- 抽一张图存出来，供肉眼确认 ---
if (jpgs.length) {
  const mid = jpgs[Math.floor(jpgs.length / 2)];
  const outDir = path.join(__dirname, '..', 'samples');
  fs.mkdirSync(outDir, { recursive: true });
  const sample = path.join(outDir, 'sample_' + path.basename(mid.name));
  fs.writeFileSync(sample, mid.data);
  console.log('\n抽样导出:', sample);
  console.log('  （请打开看一眼：应该是左眼|右眼并排的两张小图，能看清瞳孔）');
}

const ok = badCrc === 0 && badJpeg === 0 && badSize === 0 && manifest;
console.log('\n结论:', ok ? 'zip 完好，图像与标签齐全，可用于 CNN 训练 ✓' : '存在问题，见上 ✗');
process.exit(ok ? 0 : 1);
