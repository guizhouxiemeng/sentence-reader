// unzip-eyes.js — 把眼部图像 zip 解到一个目录（STORE 模式，无需 inflate）
// 用法: node tools/unzip-eyes.js gaze_xxx_eyes.zip data/eyes_p029379
const fs = require('fs');
const path = require('path');

const zipPath = process.argv[2];
const outDir = process.argv[3];
if (!zipPath || !outDir) {
  console.log('用法: node tools/unzip-eyes.js <eyes.zip> <输出目录>');
  process.exit(1);
}
if (!fs.existsSync(zipPath)) { console.log('找不到', zipPath); process.exit(1); }

const buf = fs.readFileSync(zipPath);
let eocd = -1;
for (let i = buf.length - 22; i >= Math.max(0, buf.length - 22 - 65535); i--) {
  if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
}
if (eocd < 0) { console.log('zip 损坏：找不到 EOCD'); process.exit(1); }

const count = buf.readUInt16LE(eocd + 10);
const cdOff = buf.readUInt32LE(eocd + 16);
fs.mkdirSync(outDir, { recursive: true });

let p = cdOff, n = 0, bytes = 0;
for (let i = 0; i < count; i++) {
  const method = buf.readUInt16LE(p + 10);
  const csize = buf.readUInt32LE(p + 20);
  const nlen = buf.readUInt16LE(p + 28);
  const elen = buf.readUInt16LE(p + 30);
  const clen = buf.readUInt16LE(p + 32);
  const lho = buf.readUInt32LE(p + 42);
  const name = buf.slice(p + 46, p + 46 + nlen).toString('utf8');
  const lnlen = buf.readUInt16LE(lho + 26);
  const lelen = buf.readUInt16LE(lho + 28);
  const dstart = lho + 30 + lnlen + lelen;

  if (method !== 0) {
    console.log('⚠ 条目是压缩的，本脚本只支持 STORE:', name);
    process.exit(1);
  }
  const dest = path.join(outDir, name);
  if (!path.resolve(dest).startsWith(path.resolve(outDir))) {
    console.log('⚠ 路径穿越，跳过:', name);
  } else {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.writeFileSync(dest, buf.slice(dstart, dstart + csize));
    n++; bytes += csize;
  }
  p += 46 + nlen + elen + clen;
}
console.log(`解出 ${n} 个文件，共 ${(bytes / 1048576).toFixed(1)} MB -> ${outDir}`);
const mf = path.join(outDir, 'manifest.json');
if (fs.existsSync(mf)) {
  const m = JSON.parse(fs.readFileSync(mf, 'utf8'));
  console.log('manifest 条目:', (m.index || []).length, '  layout:', m.layout);
}
