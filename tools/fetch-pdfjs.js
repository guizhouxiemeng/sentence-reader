// fetch-pdfjs.js —— 下载 pdf.js 到 plugin/vendor/pdf/，用于解析 PDF 正文。
//
// 为什么要 pdf.js：
//   浏览器内置 PDF 阅读器把页面渲染在【它自己的文档】里，
//   内容脚本读不到里面的文字（document.body 只有阅读器的工具栏）。
//   所以要拿到 URL、自己把文件抓下来解析。
//
// 为什么放 plugin/vendor 而不是 vendor/：
//   插件必须自带依赖才能离线工作。vendor/ 是网页版用的，插件目录要独立。
//
// 用法：node tools/fetch-pdfjs.js
// 说明：沿用 fetch-vendor.js 的做法 —— 用 Node 内置 https + npmmirror 直连
//       （本机 schannel 凭据链被沙箱撤销，只有 Node 自带 TLS 可用）。

const https = require('https');
const fs = require('fs');
const path = require('path');

const DEST = path.resolve(__dirname, '..', 'plugin', 'vendor', 'pdf');
const VERSION = '4.6.82';   // 4.x 的 legacy 构建兼容性最好

const FILES = [
  { dest: 'pdf.mjs',        name: 'legacy/build/pdf.mjs' },
  { dest: 'pdf.worker.mjs', name: 'legacy/build/pdf.worker.mjs' },
];

const SOURCES = [
  'https://registry.npmmirror.com/pdfjs-dist/-/pdfjs-dist-' + VERSION + '.tgz',
  'https://registry.npmjs.org/pdfjs-dist/-/pdfjs-dist-' + VERSION + '.tgz',
];

function get(url, redirects) {
  return new Promise((resolve, reject) => {
    if ((redirects || 0) > 5) return reject(new Error('重定向过多'));
    https.get(url, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        res.resume();
        return get(res.headers.location, (redirects || 0) + 1).then(resolve, reject);
      }
      if (res.statusCode !== 200) {
        res.resume();
        return reject(new Error('HTTP ' + res.statusCode + ' ' + url));
      }
      const chunks = [];
      res.on('data', c => chunks.push(c));
      res.on('end', () => resolve(Buffer.concat(chunks)));
    }).on('error', reject);
  });
}

// 极简 tar 解包：只取需要的成员（npm 包的 tgz 是 gzip + tar）
function untar(buf, wanted) {
  const zlib = require('zlib');
  const tar = zlib.gunzipSync(buf);
  const out = {};
  let off = 0;
  while (off + 512 <= tar.length) {
    const header = tar.slice(off, off + 512);
    const name = header.slice(0, 100).toString('utf8').replace(/\0.*$/, '');
    if (!name) break;
    const sizeStr = header.slice(124, 136).toString('utf8').replace(/\0.*$/, '').trim();
    const size = parseInt(sizeStr, 8) || 0;
    const dataStart = off + 512;
    if (wanted.indexOf(name) >= 0) {
      out[name] = tar.slice(dataStart, dataStart + size);
    }
    off = dataStart + Math.ceil(size / 512) * 512;
  }
  return out;
}

(async () => {
  fs.mkdirSync(DEST, { recursive: true });
  let tgz = null, usedUrl = null;
  for (const url of SOURCES) {
    try {
      console.log('尝试 ' + url);
      tgz = await get(url);
      usedUrl = url;
      console.log('  成功，' + (tgz.length / 1048576).toFixed(1) + ' MB');
      break;
    } catch (e) {
      console.log('  失败：' + e.message);
    }
  }
  if (!tgz) {
    console.error('所有源都失败。请检查网络，或手动把 pdf.mjs / pdf.worker.mjs 放到 ' + DEST);
    process.exit(1);
  }

  const names = FILES.map(f => 'package/' + f.name);
  const got = untar(tgz, names);
  let ok = 0;
  for (const f of FILES) {
    const data = got['package/' + f.name];
    if (!data) { console.error('包里没有 ' + f.name); continue; }
    fs.writeFileSync(path.join(DEST, f.dest), data);
    console.log('  已写入 ' + f.dest + '  ' + (data.length / 1024).toFixed(0) + ' KB');
    ok++;
  }
  console.log(ok === FILES.length
    ? '\n完成。来源：' + usedUrl
    : '\n有文件缺失，检查上面的输出。');
})();
