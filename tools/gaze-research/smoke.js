// smoke.js — 对本地服务器做一次真实请求冒烟测试（用 Node 的 http，不经过 schannel）
const http = require('http');

const BASE = 'http://127.0.0.1:8765';
const PATHS = [
  '/collector.html',
  '/vendor/vision_bundle.js',
  '/vendor/face_landmarker.task',
  '/vendor/wasm/vision_wasm_internal.js',
  '/vendor/wasm/vision_wasm_internal.wasm',
  '/vendor/wasm/vision_wasm_nosimd_internal.js',
  '/vendor/wasm/vision_wasm_nosimd_internal.wasm',
  '/../secret.txt',        // 目录穿越应当被拒
];

function req(pathname) {
  return new Promise((resolve) => {
    const r = http.get(BASE + pathname, { timeout: 15000 }, (res) => {
      let n = 0;
      const hdrs = res.headers;
      res.on('data', (c) => { n += c.length; });
      res.on('end', () => resolve({ pathname, status: res.statusCode, len: n, ct: hdrs['content-type'] }));
    });
    r.on('timeout', () => { r.destroy(); resolve({ pathname, status: 'TIMEOUT' }); });
    r.on('error', (e) => resolve({ pathname, status: 'ERR ' + (e.code || e.message) }));
  });
}

(async () => {
  let bad = 0;
  for (const p of PATHS) {
    const r = await req(p);
    const ok = p.includes('..') ? (r.status === 403 || r.status === 404) : r.status === 200;
    if (!ok) bad++;
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${String(r.status).padEnd(6)} ${String(r.len).padStart(9)}  ${String(r.ct || '').padEnd(28)} ${p}`);
  }
  console.log(bad === 0 ? '\n全部通过' : `\n${bad} 项失败`);
  process.exit(bad === 0 ? 0 : 1);
})();
