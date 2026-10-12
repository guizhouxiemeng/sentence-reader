// probe-browser.js — 用无头 Edge/Chrome 真实加载采集器，抓控制台错误与关键状态
// 为什么值得做：采集器里最容易出错的环节（ESM 动态 import、wasm MIME、模型实例化）
// 全都只在浏览器里才会暴露，静态检查看不出来。
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const os = require('os');

const URL_ = process.argv[2] || 'http://127.0.0.1:8765/collector.html';

const CANDIDATES = [
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  process.env.LOCALAPPDATA + '\\Google\\Chrome\\Application\\chrome.exe',
].filter(Boolean);

const exe = CANDIDATES.find((p) => fs.existsSync(p));
if (!exe) {
  console.log('没找到 Edge/Chrome，跳过浏览器验证');
  process.exit(2);
}
console.log('使用浏览器:', exe);

const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'dsh-prof-'));
const args = [
  '--headless=new',
  '--disable-gpu',
  '--no-first-run',
  '--no-default-browser-check',
  `--user-data-dir=${profile}`,
  '--enable-logging=stderr',
  '--v=0',
  '--virtual-time-budget=15000',   // 让页面里的异步任务（含 wasm 编译）有机会跑完
  '--dump-dom',
  URL_,
];

const r = spawnSync(exe, args, { encoding: 'utf8', timeout: 120000, maxBuffer: 64 * 1024 * 1024 });
const out = (r.stdout || '') + '\n' + (r.stderr || '');

// --- 1) 抓页面最终显示的状态文本 ---
const dom = r.stdout || '';
const grab = (re) => { const m = dom.match(re); return m ? m[1].replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim() : '(未找到)'; };
console.log('\n[资源状态]  ', grab(/id="asset-status"[^>]*>([\s\S]*?)<\/span>/));
console.log('[面板可见]  ', /id="p-setup"[^>]*class="[^"]*on/.test(dom) ? 'p-setup 可见（正常，未点开始）' : '设置了其他面板');

// --- 2) 抓控制台里的错误行 ---
const lines = out.split(/\r?\n/);
const errRe = /(ERROR|SEVERE|Uncaught|TypeError|ReferenceError|SyntaxError|Failed to|wasm|MIME|CORS|blocked)/i;
const noise = /(DevTools|GCM|Registration response|gpu_|voice_transcription|Fontconfig|dbus|GPU process|DEPRECATED_ENDPOINT)/i;
const errs = lines.filter((l) => errRe.test(l) && !noise.test(l));
console.log('\n[可能的控制台问题] 共', errs.length, '条');
errs.slice(0, 25).forEach((l) => console.log('   ', l.trim().slice(0, 220)));

// --- 3) 判据 ---
const status = grab(/id="asset-status"[^>]*>([\s\S]*?)<\/span>/);
const okLocal = /本地资源就绪/.test(status);
console.log('\n结论:', okLocal ? '本地资源加载成功，ESM import 通路正常' : '需要人工看一眼上面的错误');
try { fs.rmSync(profile, { recursive: true, force: true }); } catch {}
process.exit(okLocal ? 0 : 1);
