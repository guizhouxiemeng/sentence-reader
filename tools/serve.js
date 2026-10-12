// serve.js — 极简静态服务器（零依赖）+ 网页抓取代理
//
// 为什么需要它：
//   ① file:// 下 Chrome 会对 wasm 和 fetch 施加 CORS 限制，MediaPipe 可能加载失败；
//      通过 http://127.0.0.1 访问就没有这个问题，摄像头权限在 localhost 下也被视为安全上下文。
//   ② 浏览器有【同源策略】，网页里直接 fetch 别的网站会被 CORS 拦掉。
//      所以"抓取文章正文"必须由【服务器】代抓（服务器端没有同源限制），
//      页面只请求本机这个代理即可。
//
// 用法： node tools/serve.js [port]
//
// 接口：
//   GET /__fetch?url=...   -> 返回目标网页的 HTML（带正确编码），失败返回 JSON 错误

const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const ROOT = path.resolve(__dirname, '..');
const PORT = Number(process.argv[2] || 8765);

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.jsonl': 'application/json; charset=utf-8',
  '.csv': 'text/csv; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.wasm': 'application/wasm',
  '.task': 'application/octet-stream',
  '.tflite': 'application/octet-stream',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.md': 'text/markdown; charset=utf-8',
};

// ---------------------------------------------------------------------------
//  网页抓取代理
// ---------------------------------------------------------------------------
function proxyFetch(targetUrl, res, depth) {
  depth = depth || 0;
  let u;
  try {
    u = new URL(targetUrl);
  } catch (e) {
    res.writeHead(400, { 'content-type': 'application/json; charset=utf-8' })
       .end(JSON.stringify({ ok: false, error: '网址格式不对' }));
    return;
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') {
    res.writeHead(400, { 'content-type': 'application/json; charset=utf-8' })
       .end(JSON.stringify({ ok: false, error: '只支持 http/https' }));
    return;
  }

  const mod = u.protocol === 'https:' ? https : http;
  const req = mod.get({
    hostname: u.hostname,
    port: u.port || (u.protocol === 'https:' ? 443 : 80),
    path: u.pathname + u.search,
    headers: {
      // 不带 UA 很多站点会直接返回 403 / 空页
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ' +
                    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
      'Accept-Encoding': 'identity',   // 不请求压缩，省去解压（多数站点可接受）
    },
    timeout: 20000,
  }, r => {
    // 跟随重定向（最多 5 跳）
    if ([301, 302, 303, 307, 308].includes(r.statusCode) && r.headers.location) {
      r.resume();
      if (depth >= 5) {
        res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
           .end(JSON.stringify({ ok: false, error: '重定向次数过多' }));
        return;
      }
      const next = new URL(r.headers.location, u).toString();
      proxyFetch(next, res, depth + 1);
      return;
    }
    if (r.statusCode < 200 || r.statusCode >= 300) {
      r.resume();
      res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
         .end(JSON.stringify({ ok: false, error: '目标站返回 HTTP ' + r.statusCode }));
      return;
    }

    const chunks = [];
    let size = 0;
    r.on('data', c => {
      size += c.length;
      if (size > 6 * 1024 * 1024) {   // 6MB 上限，避免拖垮内存
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    r.on('end', () => {
      const buf = Buffer.concat(chunks);
      // 从 meta charset 猜编码；没写就按 UTF-8，页面侧还会做替换字符检测
      let charset = 'utf-8';
      const head = buf.slice(0, 4096).toString('latin1');
      const m = /charset\s*=\s*["']?([\w-]+)/i.exec(head);
      if (m) charset = m[1].toLowerCase();
      if (charset === 'gb2312' || charset === 'gbk') charset = 'gbk';

      let text;
      try {
        text = new TextDecoder(charset).decode(buf);
      } catch (e) {
        text = buf.toString('utf8');
      }
      res.writeHead(200, {
        'content-type': 'text/html; charset=utf-8',
        'cache-control': 'no-cache',
      }).end(text);
    });
  });

  req.on('timeout', () => { req.destroy(new Error('请求超时')); });
  req.on('error', e => {
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8' })
       .end(JSON.stringify({ ok: false, error: '抓取失败: ' + e.message }));
  });
}

// ---------------------------------------------------------------------------
const server = http.createServer((req, res) => {
  let rel;
  try {
    rel = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  } catch {
    res.writeHead(400).end('bad request');
    return;
  }

  // ---- 抓取代理 ----
  if (rel === '/__fetch') {
    const q = new URL(req.url, 'http://localhost').searchParams.get('url');
    if (!q) {
      res.writeHead(400, { 'content-type': 'application/json; charset=utf-8' })
         .end(JSON.stringify({ ok: false, error: '缺少 url 参数' }));
      return;
    }
    proxyFetch(q, res);
    return;
  }

  if (rel === '/') rel = '/collector.html';
  if (rel === '/demo' || rel === '/demo/') rel = '/demo/index.html';

  // 防目录穿越：解析后必须仍在 ROOT 内
  const abs = path.resolve(ROOT, '.' + rel);
  if (!abs.startsWith(ROOT)) {
    res.writeHead(403).end('forbidden');
    return;
  }

  fs.stat(abs, (err, st) => {
    if (err || !st.isFile()) {
      res.writeHead(404, { 'content-type': 'text/plain; charset=utf-8' }).end('404 ' + rel);
      return;
    }
    const ext = path.extname(abs).toLowerCase();
    res.writeHead(200, {
      'content-type': MIME[ext] || 'application/octet-stream',
      'content-length': st.size,
      'cache-control': 'no-cache',
      'cross-origin-resource-policy': 'cross-origin',
    });
    fs.createReadStream(abs).pipe(res);
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`serving ${ROOT}`);
  console.log(`打开： http://127.0.0.1:${PORT}/demo/reader_flow.html`);
});
