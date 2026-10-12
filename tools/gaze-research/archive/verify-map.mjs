// ============================================================================
//  verify-map.mjs — 检验"指尖特征 → 屏幕坐标"映射的全局性质
//
//  现场问题：
//    · 左半边：红球和细线之间有距离，但趋势对
//    · 右半边：红球在 B，判定却是 D（偏差很大）
//
//  "趋势对但有系统性距离"是标定误差的典型表现；但"右半边差得特别多"
//  提示映射在右端可能不是单调的（折叠），或者符号校验引入了偏差。
//
//  本测试直接用真实代码，在特征全域上扫描，检查：
//    ① 单调性：指尖特征从最小到最大，预测 x 是否单调不减
//    ② 端到端误差：用已知映射生成数据，看预测回归得多准
//    ③ 符号校验是否会把正确的映射改坏
//
//  用法： node tools/verify-map.mjs
// ============================================================================
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DEMO = path.join(ROOT, 'demo', 'demo-hand.html');

let pass = 0, fail = 0;
const ok = (c, n, d) => { c ? (pass++, console.log('  \u2713 ' + n)) : (fail++, console.log('  \u2717 ' + n + (d ? '  \u2014 ' + d : ''))); };

// ---------------------------------------------------------------- DOM 桩
function makeEl(id) {
  return {
    id, style: {}, dataset: {}, children: [], className: '', innerHTML: '',
    textContent: '', value: '', checked: false, disabled: false, width: 0, height: 0,
    classList: { _s: new Set(), add(c){this._s.add(c);}, remove(c){this._s.delete(c);},
      toggle(c,v){ if(v===undefined){this._s.has(c)?this._s.delete(c):this._s.add(c);} else {v?this._s.add(c):this._s.delete(c);} },
      contains(c){return this._s.has(c);} },
    appendChild(c){this.children.push(c);return c;}, removeChild(c){this.children=this.children.filter(x=>x!==c);},
    remove(){}, querySelectorAll(){return [];}, querySelector(){return null;},
    addEventListener(){}, requestFullscreen(){return Promise.resolve();},
    getContext(){ const noop=()=>{}; return {clearRect:noop,beginPath:noop,moveTo:noop,lineTo:noop,
      stroke:noop,arc:noop,fill:noop,fillRect:noop,save:noop,restore:noop,translate:noop,
      scale:noop,drawImage:noop,closePath:noop,setLineDash:noop,
      createLinearGradient:()=>({addColorStop:noop})}; },
    play(){return Promise.resolve();}, toDataURL(){return '';},
  };
}
const els = new Map();
const getEl = (id) => { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); };

globalThis.document = { getElementById: getEl, createElement: (t)=>makeEl('c-'+t),
  querySelectorAll: ()=>[], querySelector: ()=>null, addEventListener: ()=>{},
  body: makeEl('body'), fullscreenElement: null, exitFullscreen: ()=>Promise.resolve(),
  currentScript: { src: pathToFileURL(DEMO).href } };
globalThis.window = globalThis;
globalThis.innerWidth = 1920;
globalThis.innerHeight = 1080;
globalThis.screen = { width: 1920, height: 1080 };
globalThis.devicePixelRatio = 1;
globalThis.location = { protocol: 'http:', href: 'http://127.0.0.1:8765/demo/demo-hand.html' };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.addEventListener = () => {};
try {
  Object.defineProperty(globalThis, 'navigator', { configurable: true,
    value: { mediaDevices: { getUserMedia: () => Promise.reject(new Error('no cam')) } } });
} catch (e) {}
globalThis.Blob = class { constructor(){} };
globalThis.URL.createObjectURL = () => 'blob:x';

// ---------------------------------------------------------------- 加载
const html = fs.readFileSync(DEMO, 'utf8');
const code = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
  .replace(/await import\([^)]*\)/g, 'await (async () => { throw new Error("no mp"); })()');
const tmp = path.join(ROOT, 'tools', '.tmp-map');
fs.mkdirSync(tmp, { recursive: true });
const mp = path.join(tmp, 'm.mjs');
fs.writeFileSync(mp, code, 'utf8');
await import(pathToFileURL(mp).href);
const D = globalThis.__demo;
if (!D) { console.error('钩子未导出'); process.exit(1); }

const W = globalThis.innerWidth, H = globalThis.innerHeight;

console.log('='.repeat(74));
console.log('映射全局性质检验');
console.log('='.repeat(74));

// ---------------------------------------------------------------- 合成"理想手"
function synthHand(px, py) {
  const u = px / W, v = py / H;
  const tipx = 0.15 + 0.55 * u, tipy = 0.25 + 0.45 * v;
  const lm = new Array(500).fill(null).map(() => ({ x: 0, y: 0, z: 0 }));
  const wr = { x: tipx - 0.10, y: tipy + 0.18 };
  const mc = { x: wr.x + 0.045, y: wr.y - 0.06 };
  lm[8] = { x: tipx, y: tipy, z: 0 };
  lm[0] = { x: wr.x, y: wr.y, z: 0 };
  lm[9] = { x: mc.x, y: mc.y, z: 0 };
  lm[4] = { x: tipx-0.03, y: tipy+0.03, z: 0 };
  lm[6] = { x: tipx-0.02, y: tipy+0.02, z: 0 };
  lm[5] = { x: wr.x, y: wr.y-0.02, z: 0 };
  return lm;
}

// 校准
console.log('\n[1] 建立校准（9 点米字，与 demo 一致）');
const ix = W*0.10, iy = H*0.10;
const pts = [[W/2,H/2],[W/2,iy],[W/2,H-iy],[ix,H/2],[W-ix,H/2],
             [ix,iy],[W-ix,iy],[ix,H-iy],[W-ix,H-iy]];
const samples = [];
for (const [px,py] of pts) {
  for (let k=0;k<30;k++) {
    const jx = (Math.random()-0.5)*0.0015, jy = (Math.random()-0.5)*0.0015;
    samples.push({ f: D.buildFeatures(synthHand(px + jx*W, py + jy*H)), px, py, t: k*16 });
  }
}
D.S.topFeats = D.pickTopFeats(samples);
const cal = D.fitCalibration(samples);
ok(!!cal, 'fitCalibration 成功');
console.log('  留一误差 %.1fpx   增益 gainX=%.3f gainY=%.3f',
  cal.cvErr, cal.gainX, cal.gainY);
console.log('  dirFixed(符号校验是否触发) = %s', D.S.dirFixed);
D.setCal(cal);

// ---------------------------------------------------------------- 单调性扫描
console.log('\n[2] 全范围单调性扫描（检查右端是否折叠）');
console.log('  沿屏幕 x 从 0 到满幅扫描，看预测 x 是否单调不减');
{
  const rows = [];
  for (let i=0;i<=20;i++) {
    const px = i/20*W;
    const pv = D.predict(D.buildFeatures(synthHand(px, H/2)));
    rows.push({ px, pred: pv ? pv[0] : NaN });
  }
  let dec = 0;
  for (let i=1;i<rows.length;i++) if (rows[i].pred < rows[i-1].pred - 1) dec++;
  console.log('    输入 x → 预测 x：');
  console.log('    ' + rows.map(r=>Math.round(r.pred)).join(' '));
  ok(dec === 0, '预测 x 单调不减（无折叠）', dec + ' 处下降');
  // 端点检查
  const firstDiff = rows[1].pred - rows[0].pred;
  const lastDiff = rows[rows.length-1].pred - rows[rows.length-2].pred;
  console.log('    起点斜率 %.1f px/格   终点斜率 %.1f px/格', firstDiff, lastDiff);
  ok(Math.abs(lastDiff) > 1, '右端仍在变化（不是饱和）', 'lastDiff='+lastDiff.toFixed(1));
}

// ---------------------------------------------------------------- 端到端误差
console.log('\n[3] 端到端误差（合成数据的可复现上限）');
{
  let sumx=0, sumy=0, n=0, maxe=0;
  for (let i=0;i<=12;i++) for (let j=0;j<=8;j++) {
    const px = W*0.08 + i/12*W*0.84, py = H*0.08 + j/8*H*0.84;
    const pv = D.predict(D.buildFeatures(synthHand(px, py)));
    if (!pv) continue;
    const ex = pv[0]-px, ey = pv[1]-py;
    sumx += Math.abs(ex); sumy += Math.abs(ey); n++;
    maxe = Math.max(maxe, Math.hypot(ex, ey));
  }
  const maex = sumx/n, maey = sumy/n;
  console.log('    |误差| 平均 x %.1f px   y %.1f px   最大 %.1f px', maex, maey, maxe);
  ok(maex < 60, 'x 方向平均误差 < 60px（映射本身正确）', maex.toFixed(1));
  ok(maey < 60, 'y 方向平均误差 < 60px', maey.toFixed(1));
}

// ---------------------------------------------------------------- 左右半屏对称性
console.log('\n[4] 左右半屏误差是否对称（现场症状：右半边差得多）');
{
  const bucket = { left: [], right: [] };
  for (let i=0;i<=20;i++) {
    const px = i/20*W;
    const pv = D.predict(D.buildFeatures(synthHand(px, H/2)));
    if (!pv) continue;
    (px < W/2 ? bucket.left : bucket.right).push(Math.abs(pv[0]-px));
  }
  const avg = a => a.reduce((x,y)=>x+y,0)/a.length;
  const L = avg(bucket.left), R = avg(bucket.right);
  console.log('    左半屏平均 |误差| %.1f px   右半屏 %.1f px', L, R);
  ok(Math.abs(L-R) < 80, '左右半屏误差接近（无单侧系统性偏差）',
     'L='+L.toFixed(1)+' R='+R.toFixed(1));
}

// ---------------------------------------------------------------- 符号校验的影响
console.log('\n[5] 符号校验是否会改坏正确的映射');
{
  // 再做一次校准，分别看"校验前/后"的端到端误差
  D.S.topFeats = D.pickTopFeats(samples);
  const cal2 = D.fitCalibration(samples);
  const fixed = D.S.dirFixed;
  D.setCal(cal2);
  let e = 0, n = 0;
  for (let i=0;i<=20;i++) {
    const px = i/20*W;
    const pv = D.predict(D.buildFeatures(synthHand(px, H/2)));
    if (pv) { e += Math.abs(pv[0]-px); n++; }
  }
  console.log('    dirFixed=%s   平均 |误差| %.1f px', fixed, e/n);
  ok(e/n < 80, '符号校验未破坏映射', (e/n).toFixed(1));
}

fs.rmSync(tmp, { recursive: true, force: true });
console.log('\n' + '='.repeat(74));
console.log('结果: ' + pass + ' 通过, ' + fail + ' 失败');
console.log('='.repeat(74));
process.exit(fail ? 1 : 0);
