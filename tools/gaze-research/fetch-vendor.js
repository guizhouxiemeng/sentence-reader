// fetch-vendor.js — 下载 MediaPipe 运行所需的全部文件到 vendor/
// 用 Node 内置 https 而非 curl/.NET：本机 schannel 凭据链被 DSH 沙箱撤销，只有 Node 的自带 TLS 栈可用。
// 用法：  node tools/fetch-vendor.js
//
// 已验证可用：npmmirror 的 tgz 直连即可下载成功（Node 不做 TLS 拦截，无需代理）。
// Node 内置 https 不读 HTTPS_PROXY；本脚本假设直连可用，或系统级透明代理/TUN 已生效。

const https = require('https');
const fs = require('fs');
const path = require('path');

const VENDOR = path.resolve(__dirname, '..', 'vendor');
const TGZ = 'https://registry.npmmirror.com/@mediapipe/tasks-vision/-/tasks-vision-0.10.12.tgz';

// 每个目标给多个源，按顺序尝试，第一个成功的就用。
// 注意：npm 包里没有 vision_bundle.js，只有 ESM 的 vision_bundle.mjs（我们落盘时改名成 .js）。
// 直接从 CDN 取 vision_bundle.mjs 时，解包后的 tar 成员名才是关键，所以 tgz 放在第一优先。
const TARGETS = [
  {
    dest: 'vision_bundle.js',
    urls: [
      TGZ,
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/vision_bundle.mjs',
      'https://unpkg.com/@mediapipe/tasks-vision@0.10.12/vision_bundle.mjs',
    ],
    tarMember: 'package/vision_bundle.mjs',
    fromTar: true,
  },
  {
    dest: 'wasm/vision_wasm_internal.js',
    urls: [
      TGZ,
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_internal.js',
      'https://unpkg.com/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_internal.js',
    ],
    tarMember: 'package/wasm/vision_wasm_internal.js',
    fromTar: true,
  },
  {
    dest: 'wasm/vision_wasm_internal.wasm',
    tarMember: 'package/wasm/vision_wasm_internal.wasm',
    urls: [
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_internal.wasm',
      'https://unpkg.com/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_internal.wasm',
      'https://registry.npmmirror.com/@mediapipe/tasks-vision/-/tasks-vision-0.10.12.tgz',
    ],
    fromTar: true,
  },
  {
    dest: 'wasm/vision_wasm_nosimd_internal.js',
    tarMember: 'package/wasm/vision_wasm_nosimd_internal.js',
    urls: [
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_nosimd_internal.js',
      'https://unpkg.com/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_nosimd_internal.js',
      'https://registry.npmmirror.com/@mediapipe/tasks-vision/-/tasks-vision-0.10.12.tgz',
    ],
    fromTar: true,
  },
  {
    dest: 'wasm/vision_wasm_nosimd_internal.wasm',
    tarMember: 'package/wasm/vision_wasm_nosimd_internal.wasm',
    urls: [
      'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_nosimd_internal.wasm',
      'https://unpkg.com/@mediapipe/tasks-vision@0.10.12/wasm/vision_wasm_nosimd_internal.wasm',
      'https://registry.npmmirror.com/@mediapipe/tasks-vision/-/tasks-vision-0.10.12.tgz',
    ],
    fromTar: true,
  },
  {
    dest: 'face_landmarker.task',
    urls: [
      'https://cdn.jsdelivr.net/gh/googlesamples/mediapipe@main/examples/face_landmarker/js/face_landmarker.task',
      'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
    ],
    optional: true,
  },
];

function download(url, dest, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 6) return reject(new Error('too many redirects'));
    const req = https.get(url, { timeout: 180000 }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        return download(new URL(res.headers.location, url).href, dest, redirects + 1).then(resolve, reject);
      }
      if (res.statusCode !== 200) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      fs.mkdirSync(path.dirname(dest), { recursive: true });
      const ws = fs.createWriteStream(dest);
      res.pipe(ws);
      ws.on('finish', () => ws.close(() => resolve(fs.statSync(dest).size)));
      ws.on('error', reject);
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

function fetchBuffer(url, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (redirects > 6) return reject(new Error('too many redirects'));
    const req = https.get(url, { timeout: 180000 }, (res) => {
      if ([301, 302, 303, 307, 308].includes(res.statusCode) && res.headers.location) {
        res.resume();
        return fetchBuffer(new URL(res.headers.location, url).href, redirects + 1).then(resolve, reject);
      }
      if (res.statusCode !== 200) { res.resume(); return reject(new Error('HTTP ' + res.statusCode)); }
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    });
    req.on('timeout', () => req.destroy(new Error('timeout')));
    req.on('error', reject);
  });
}

// ---- 极简 tar.gz 读取（只支持我们需要的 regular file + 长名扩展）----
function tarEntries(buf) {
  const zlib = require('zlib');
  const tar = zlib.gunzipSync(buf);
  const out = [];
  let off = 0, longName = null;
  while (off + 512 <= tar.length) {
    const header = tar.slice(off, off + 512);
    if (header.every((b) => b === 0)) break;
    const name = header.slice(0, 100).toString('utf8').replace(/\0.*$/, '');
    const sizeStr = header.slice(124, 136).toString('utf8').replace(/\0.*$/, '').trim();
    const size = parseInt(sizeStr, 8) || 0;
    const type = String.fromCharCode(header[156]);
    const dataStart = off + 512;
    if (type === 'L') {                       // GNU long name
      longName = tar.slice(dataStart, dataStart + size).toString('utf8').replace(/\0.*$/, '');
    } else if (type === '0' || type === '\0' || type === '') {
      out.push({ name: (longName || name).replace(/^\.\//, ''), data: tar.slice(dataStart, dataStart + size) });
      longName = null;
    } else { longName = null; }
    off = dataStart + Math.ceil(size / 512) * 512;
  }
  return out;
}

// 说明：Node 内置的 https 不读 HTTPS_PROXY 环境变量。本机 7897 是可用代理时，
// 在 pwsh 里先设 $env:HTTPS_PROXY 就能生效——做法见 README（用 Node 的 Agent 版本，或先跑工具区里的代理封装）。
// 简化取舍：本脚本假设"直连可用"或"系统级代理（TUN/透明代理）已生效"，这也是国内 V2Ray/Clash 常见的 TUN 模式。

(async () => {
  fs.mkdirSync(path.join(VENDOR, 'wasm'), { recursive: true });
  console.log('vendor ->', VENDOR);

  const tars = new Map();   // url -> entries，避免重复下载 tgz

  for (const t of TARGETS) {
    const destAbs = path.join(VENDOR, t.dest);
    if (fs.existsSync(destAbs) && fs.statSync(destAbs).size > 1024) {
      console.log(`跳过（已存在）      ${t.dest}  ${fs.statSync(destAbs).size} bytes`);
      continue;
    }
    let done = false;
    for (const url of t.urls) {
      try {
        if (t.fromTar) {
          // 先尝试直接下载单个文件；失败则退回从 tgz 里取
          if (url.endsWith('.tgz')) {
            let entries = tars.get(url);
            if (!entries) {
              process.stdout.write(`  取 tgz ${url} ... `);
              const buf = await fetchBuffer(url);
              entries = tarEntries(buf);
              tars.set(url, entries);
              console.log(`ok (${entries.length} entries)`);
            }
            const want = t.tarMember || ('package/' + t.dest);
            const e = entries.find((x) => x.name === want);
            if (!e) throw new Error('tgz 内没有 ' + want);
            fs.writeFileSync(destAbs, e.data);
            console.log(`OK  ${t.dest}  ${e.data.length} bytes  (from tgz)`);
          } else {
            const n = await download(url, destAbs);
            console.log(`OK  ${t.dest}  ${n} bytes`);
          }
        } else {
          const n = await download(url, destAbs);
          console.log(`OK  ${t.dest}  ${n} bytes`);
        }
        done = true;
        break;
      } catch (e) {
        console.log(`  x  ${url}\n     ${e.code || e.message}`);
      }
    }
    if (!done) {
      if (t.optional) console.log(`!!  ${t.dest} 全部源失败（可选，但缺了就无法本地推理）`);
      else { console.log(`!!  ${t.dest} 全部源失败 —— 请检查代理/VPN`); process.exitCode = 1; }
    }
  }

  console.log('\n=== vendor 目录现状 ===');
  const walk = (d, pre = '') => {
    for (const f of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, f.name);
      if (f.isDirectory()) walk(p, pre + f.name + '/');
      else console.log(`  ${pre}${f.name}  ${fs.statSync(p).size} bytes`);
    }
  };
  walk(VENDOR);
})();

