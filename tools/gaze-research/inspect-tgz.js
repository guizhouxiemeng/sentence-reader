// inspect-tgz.js — 下载 npm 包并在内存里列出条目（不依赖 tar.exe / schannel）
const https = require('https');
const zlib = require('zlib');
const fs = require('fs');
const path = require('path');

const URL_ = 'https://registry.npmmirror.com/@mediapipe/tasks-vision/-/tasks-vision-0.10.12.tgz';
const SAVE = path.join(__dirname, '..', 'vendor', '.cache', 'tasks-vision-0.10.12.tgz');

function fetch(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 6) return reject(new Error('too many redirects'));
    https.get(url, { timeout: 120000 }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        return fetch(new URL(res.headers.location, url).href, redirects + 1).then(resolve, reject);
      }
      if (res.statusCode !== 200) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject).on('timeout', function () { this.destroy(new Error('timeout')); });
  });
}

function tarEntries(buf) {
  const tar = zlib.gunzipSync(buf);
  const out = [];
  let off = 0, longName = null;
  while (off + 512 <= tar.length) {
    const h = tar.slice(off, off + 512);
    if (h.every((b) => b === 0)) break;
    const name = h.slice(0, 100).toString('utf8').replace(/\0.*$/, '');
    const size = parseInt(h.slice(124, 136).toString('utf8').replace(/\0.*$/, '').trim(), 8) || 0;
    const type = String.fromCharCode(h[156]);
    const start = off + 512;
    if (type === 'L') {
      longName = tar.slice(start, start + size).toString('utf8').replace(/\0.*$/, '');
    } else if (type === '0' || type === '\0') {
      out.push({ name: (longName || name).replace(/^\.\//, ''), size, data: tar.slice(start, start + size) });
      longName = null;
    } else { longName = null; }
    off = start + Math.ceil(size / 512) * 512;
  }
  return out;
}

(async () => {
  fs.mkdirSync(path.dirname(SAVE), { recursive: true });
  let buf;
  if (fs.existsSync(SAVE) && fs.statSync(SAVE).size > 100000) {
    console.log('复用已缓存的 tgz:', SAVE, fs.statSync(SAVE).size);
    buf = fs.readFileSync(SAVE);
  } else {
    console.log('下载', URL_);
    buf = await fetch(URL_);
    fs.writeFileSync(SAVE, buf);
    console.log('已保存', SAVE, buf.length, 'bytes');
  }
  const entries = tarEntries(buf);
  console.log('\n=== 条目（共 ' + entries.length + '）===');
  for (const e of entries) {
    console.log(String(e.size).padStart(10) + '  ' + e.name);
  }
  // 把根目录的 mjs 全部落盘（后面要用）
  const root = path.join(__dirname, '..', 'vendor');
  for (const e of entries) {
    if (/^package\/[^/]+\.(mjs|js|json|d\.ts)$/.test(e.name)) {
      const dest = path.join(root, path.basename(e.name));
      fs.writeFileSync(dest, e.data);
      console.log('已释放 ->', path.basename(e.name));
    }
    if (/^package\/wasm\//.test(e.name)) {
      const dest = path.join(root, 'wasm', path.basename(e.name));
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      fs.writeFileSync(dest, e.data);
      console.log('已释放 -> wasm/' + path.basename(e.name));
    }
  }
})();
