// ============================================================================
//  verify-fusion.mjs — 用合成数据无头验证融合管线的数值正确性
//
//  目的：在让人实测之前，先用【确定性合成数据】跑通真实代码路径，
//  把数值层面的 bug（索引错位、维度不匹配、增益反向、指标没累加等）
//  全部在 Node 里抓出来。否则每一轮迭代都要占用使用者的时间，
//  而他们反馈的信息量远不如一份精确的断言失败。
//
//  做法：
//    ① 最小 DOM 桩：让 demo 的模块脚本能在 Node 里被 import
//    ② 合成一个"理想手"：给定屏幕坐标，反算出指尖特征
//    ③ 用合成数据跑真实的 buildFeatures → fitCalibration → predict
//    ④ 用合成数据跑真实的 fitGazeZoneClassifier → predictGazeZone
//    ⑤ 驱动真实的实验框架，检查指标是否被正确记录
//
//  用法： node tools/verify-fusion.mjs
// ============================================================================
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const DEMO = path.join(ROOT, 'demo', 'demo-hand.html');

let pass = 0, fail = 0;
function ok(cond, name, detail) {
  if (cond) { pass++; console.log('  \u2713 ' + name); }
  else { fail++; console.log('  \u2717 ' + name + (detail ? '  \u2014 ' + detail : '')); }
}
function near(a, b, tol) { return Math.abs(a - b) <= tol; }

// ---------------------------------------------------------------- DOM 桩
function makeEl(id) {
  const el = {
    id, style: {}, dataset: {}, children: [],
    className: '', innerHTML: '', textContent: '', value: '', checked: false,
    disabled: false, width: 0, height: 0,
    classList: {
      _s: new Set(),
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      toggle(c, v) { if (v === undefined) { this._s.has(c) ? this._s.delete(c) : this._s.add(c); } else { v ? this._s.add(c) : this._s.delete(c); } },
      contains(c) { return this._s.has(c); },
    },
    appendChild(c) { this.children.push(c); return c; },
    removeChild(c) { this.children = this.children.filter(x => x !== c); },
    remove() {},
    querySelectorAll() { return []; },
    querySelector() { return null; },
    addEventListener() {},
    requestFullscreen() { return Promise.resolve(); },
    getContext() {
      const noop = () => {};
      return { clearRect: noop, beginPath: noop, moveTo: noop, lineTo: noop, stroke: noop,
               arc: noop, fill: noop, fillRect: noop, save: noop, restore: noop,
               translate: noop, scale: noop, drawImage: noop, closePath: noop,
               setLineDash: noop, createLinearGradient: () => ({ addColorStop: noop }) };
    },
    play() { return Promise.resolve(); },
    toDataURL() { return ''; },
  };
  return el;
}

const els = new Map();
function getEl(id) {
  if (!els.has(id)) els.set(id, makeEl(id));
  return els.get(id);
}

globalThis.document = {
  getElementById: getEl,
  createElement: (tag) => makeEl('created-' + tag),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener: () => {},
  body: makeEl('body'),
  fullscreenElement: null,
  exitFullscreen: () => Promise.resolve(),
  currentScript: { src: pathToFileURL(path.join(ROOT, 'demo', 'demo-hand.html')).href },
};
globalThis.window = globalThis;
globalThis.innerWidth = 1920;
globalThis.innerHeight = 1080;
globalThis.screen = { width: 1920, height: 1080 };
globalThis.devicePixelRatio = 1;
globalThis.location = { protocol: 'http:', href: 'http://127.0.0.1:8765/demo/demo-hand.html' };
globalThis.performance = globalThis.performance || { now: () => Date.now() };
globalThis.requestAnimationFrame = () => 0;
globalThis.cancelAnimationFrame = () => {};
globalThis.addEventListener = () => {};
globalThis.setTimeout = globalThis.setTimeout;
// navigator 在 Node 里是只读 getter，必须用 defineProperty 覆盖
try {
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { mediaDevices: { getUserMedia: () => Promise.reject(new Error('no camera in node')) } },
  });
} catch (e) {
  console.warn('无法覆盖 navigator，某些路径可能失败:', e.message);
}
globalThis.Blob = class { constructor() {} };
globalThis.URL.createObjectURL = () => 'blob:stub';

// ---------------------------------------------------------------- 提取并加载模块
const html = fs.readFileSync(DEMO, 'utf8');
const m = html.match(/<script type="module">([\s\S]*?)<\/script>/);
if (!m) { console.error('未能从 demo 提取模块脚本'); process.exit(1); }
const tmpDir = path.join(ROOT, 'tools', '.tmp-verify');
fs.mkdirSync(tmpDir, { recursive: true });
const modPath = path.join(tmpDir, 'demo-module.mjs');
// 把裸标识符导入与动态 import 变成惰性（Node 里不需要真的加载 MediaPipe）
let code = m[1];
code = code.replace(/await import\([^)]*\)/g, 'await (async () => { throw new Error("no mediapipe in node"); })()');
fs.writeFileSync(modPath, code, 'utf8');

console.log('='.repeat(76));
console.log('融合管线无头验证（合成数据驱动真实代码）');
console.log('='.repeat(76));

await import(pathToFileURL(modPath).href);
const D = globalThis.__demo;
if (!D) { console.error('钩子 globalThis.__demo 未导出'); process.exit(1); }

console.log('\n[1] 钩子与常量');
ok(!!D, 'globalThis.__demo 已导出');
ok(D.FEAT_NAMES.length > 0, 'FEAT_NAMES 可用', JSON.stringify(D.FEAT_NAMES));
console.log('     特征: ' + D.FEAT_NAMES.join(', '));
console.log('     区域分类器特征维度由样本自适应');

// ---------------------------------------------------------------- 合成"理想手"
// 模型：指尖特征 = 屏幕坐标的线性函数（含轻微二次项），模拟真实映射
function synthHand(px, py) {
  const u = px / globalThis.innerWidth, v = py / globalThis.innerHeight;
  const tipx = 0.15 + 0.55 * u;          // 归一化图像坐标
  const tipy = 0.25 + 0.45 * v;
  // 构造一个与 buildFeatures 期望格式一致、但由 (px,py) 决定的 landmark 数组
  const lm = new Array(500).fill(null).map(() => ({ x: 0, y: 0, z: 0 }));
  const wr = { x: tipx - 0.10, y: tipy + 0.18 };
  const mc = { x: wr.x + 0.045, y: wr.y - 0.06 };
  lm[D.GAZE_LM ? 8 : 8] = { x: tipx, y: tipy };     // 8 = indexTip
  lm[0] = { x: wr.x, y: wr.y, z: 0 };               // 0 = wrist
  lm[9] = { x: mc.x, y: mc.y, z: 0 };               // 9 = middleMCP
  lm[4] = { x: tipx - 0.03, y: tipy + 0.03, z: 0 }; // 4 = thumbTip
  lm[6] = { x: tipx - 0.02, y: tipy + 0.02, z: 0 };
  lm[5] = { x: wr.x, y: wr.y - 0.02, z: 0 };
  return lm;
}

console.log('\n[2] 手部特征构建');
{
  const lm = synthHand(960, 540);
  const f = D.buildFeatures(lm);
  ok(Array.isArray(f) && f.length === D.FEAT_NAMES.length,
     'buildFeatures 输出维度与 FEAT_NAMES 一致',
     'got ' + (f ? f.length : 'null') + ' want ' + D.FEAT_NAMES.length);
  ok(f.every(Number.isFinite), '特征全部有限');
  const f2 = D.buildFeatures(synthHand(1700, 900));
  ok(Math.abs(f2[0] - f[0]) > 1e-3, '指尖 x 确实随屏幕位置变化', `${f[0]} vs ${f2[0]}`);
  ok(Math.abs(f2[1] - f[1]) > 1e-3, '指尖 y 确实随屏幕位置变化', `${f[1]} vs ${f2[1]}`);
}

// ---------------------------------------------------------------- 校准拟合
console.log('\n[3] 校准拟合（真实 fitCalibration + predict）');
{
  // 9 点米字布局，与 demo 的 buildCalibGrid 几何一致
  const W = globalThis.innerWidth, H = globalThis.innerHeight;
  const ix = W * 0.10, iy = H * 0.10;
  const pts = [[W/2,H/2],[W/2,iy],[W/2,H-iy],[ix,H/2],[W-ix,H/2],
               [ix,iy],[W-ix,iy],[ix,H-iy],[W-ix,H-iy]];
  const samples = [];
  for (const [px, py] of pts) {
    const lm = synthHand(px, py);
    for (let k = 0; k < 30; k++) {
      // 加一点噪声模拟真实抖动
      const jitter = () => (Math.random() - 0.5) * 0.002;
      const lmj = synthHand(px + jitter() * 400, py + jitter() * 400);
      samples.push({ f: D.buildFeatures(lmj), px, py, t: k * 16 });
    }
  }
  D.S.topFeats = D.pickTopFeats(samples);
  ok(D.S.topFeats && D.S.topFeats.length === Math.min(D.CALIB_FEATS, D.FEAT_NAMES.length),
     'pickTopFeats 返回正确的特征数', 'got ' + (D.S.topFeats || []).length);

  const cal = D.fitCalibration(samples);
  ok(!!cal, 'fitCalibration 成功返回');
  if (cal) {
    ok(cal.bx.every(Number.isFinite) && cal.by.every(Number.isFinite), '回归系数全部有限');
    ok(Number.isFinite(cal.cvErr), '留一误差是有限值', 'cvErr=' + cal.cvErr);
    console.log('     留一误差 ' + (cal.cvErr !== null ? cal.cvErr.toFixed(1) + ' px' : 'null') +
                '  (' + (cal.cvErr / Math.hypot(W, H)).toFixed(4) + ' 对角线)');
    console.log('     增益 gainX=' + cal.gainX.toFixed(3) + ' gainY=' + cal.gainY.toFixed(3));
    console.log('     偏移 offX=' + cal.offX.toFixed(1) + ' offY=' + cal.offY.toFixed(1));

    // 合成数据是干净的单调映射，留一误差应该很小
    ok(cal.cvErr / Math.hypot(W, H) < 0.10,
       '合成数据下留一误差应 < 0.10 对角线（验证管线正确性）',
       '实际 ' + (cal.cvErr / Math.hypot(W, H)).toFixed(4));

    // 预测单调性：屏幕坐标增大，预测坐标也应增大（不能反向）
    D.setCal(cal);
    const xs = [], ys = [];
    for (let u = 0.1; u <= 0.9; u += 0.2) {
      for (let v = 0.1; v <= 0.9; v += 0.2) {
        const pv = D.predict(D.buildFeatures(synthHand(u * W, v * H)));
        if (pv) { xs.push(pv[0]); ys.push(pv[1]); }
      }
    }
    ok(xs.length > 0 && ys.length > 0, 'predict 在合成数据上全部返回有限值');
    // 检查最小/最大跨越范围
    const spanX = Math.max(...xs) - Math.min(...xs);
    const spanY = Math.max(...ys) - Math.min(...ys);
    ok(spanX > W * 0.4, '预测 x 跨度合理（不是常数）', 'span=' + spanX.toFixed(0));
    ok(spanY > H * 0.3, '预测 y 跨度合理（不是常数）', 'span=' + spanY.toFixed(0));
    // 单调性：按 u 排序后 x 应基本单调
    let mono = 0, tot = 0;
    for (let v = 0.1; v <= 0.9; v += 0.2) {
      const arr = [];
      for (let u = 0.1; u <= 0.9; u += 0.1) {
        const pv = D.predict(D.buildFeatures(synthHand(u * W, v * H)));
        if (pv) arr.push(pv[0]);
      }
      for (let i = 1; i < arr.length; i++) { tot++; if (arr[i] >= arr[i-1] - 1) mono++; }
    }
    ok(mono / tot > 0.8, '预测 x 随手部右移单调不减（无折叠）',
       '单调比例 ' + (mono / Math.max(tot,1) * 100).toFixed(0) + '%');
  }
}

// ---------------------------------------------------------------- 区域分类
console.log('\n[4] 眼动区域分类（真实 fitGazeZoneClassifier）');
{
  const W = globalThis.innerWidth, H = globalThis.innerHeight;
  // 合成视线特征：gx 随屏幕 x 单调，iry 随屏幕 y 单调。
  //
  // 用【水平 1x2】而不是 2x2，这是有实测依据的设计决定。
  // tools/zone_partition_search.py 在三个真实会话上测出的准确率：
  //     水平 1x2   80.4%   ← 采用
  //     垂直 2x1   71.4%
  //     水平 1x3   65.2%
  //     2x2        46.0%   ← 早期设计，被不可靠的垂直分量拖垮
  //   （随机基线：二分类 50%、四分类 25%）
  // 所以粗定位层只判断"左半屏 / 右半屏"。
  const gsamples = [];
  for (let u = 0; u < 4; u++) {
    for (let v = 0; v < 4; v++) {
      const px = (u + 0.5) / 4 * W, py = (v + 0.5) / 4 * H;
      for (let k = 0; k < 20; k++) {
        const nx = (Math.random() - 0.5) * 0.01, ny = (Math.random() - 0.5) * 0.01;
        const gx = -0.05 + 0.10 * (px / W) + nx;
        const iry = 0.74 + 0.03 * (py / H) + ny;
        gsamples.push({ f: [iry, 0.5, gx, gx*gx, iry*iry, gx*0.5, gx*0.5], px, py });
      }
    }
  }
  // 水平 1x2
  const zc = D.fitGazeZoneClassifier(gsamples, 2, 1);
  ok(!!zc, 'fitGazeZoneClassifier 成功返回');
  if (zc) {
    ok(zc.B.length === 2, '分类器输出 2 个区域（水平 1x2）', 'got ' + zc.B.length);
    ok(zc.trainAcc > 0.85, '合成理想信号下 1x2 自检准确率应 > 85%',
       '实际 ' + (zc.trainAcc * 100).toFixed(1) + '%');
    console.log('     1x2 自检准确率 ' + (zc.trainAcc * 100).toFixed(1) + '%');

    // 固化成断言：2x2 会明显更差 —— 这是选择水平二分屏的实测依据，
    // 防止后续改动误把分区加回纵向。
    const zc22 = D.fitGazeZoneClassifier(gsamples, 2, 2);
    ok(!!zc22 && zc22.trainAcc < zc.trainAcc,
       '2x2 准确率应低于 1x2（垂直分量不可靠）',
       zc22 ? ('2x2=' + (zc22.trainAcc*100).toFixed(1) + '% vs 1x2=' + (zc.trainAcc*100).toFixed(1) + '%') : 'null');

    D.S.gazeZone = zc;
    const p0 = D.predictGazeZone(gsamples[0].f);
    ok(!!p0 && Number.isFinite(p0.zone), 'predictGazeZone 返回有效区域');
    ok(p0.zone >= 0 && p0.zone < 2, '预测区域索引在 1x2 范围内', 'got ' + (p0 ? p0.zone : 'null'));

    const idx = D.zoneGridIndex(gsamples[0].px, gsamples[0].py, 2, 1);
    ok(idx === 0, 'zoneGridIndex 左半屏为区域 0', 'got ' + idx);
    const last = gsamples[gsamples.length - 1];
    ok(D.zoneGridIndex(last.px, last.py, 2, 1) === 1, 'zoneGridIndex 右半屏为区域 1');

    // targetInZone：左列目标应属于区域 0
    ok(D.targetInZone({ x: 300, y: 500 }, 0, 2, 1) === true, '左列目标属于区域 0');
    ok(D.targetInZone({ x: 300, y: 500 }, 1, 2, 1) === false, '左列目标不属于区域 1');
    ok(D.targetInZone({ x: 1700, y: 500 }, 1, 2, 1) === true, '右列目标属于区域 1');
  }
}

// ---------------------------------------------------------------- 试验序列
console.log('\n[5] 实验框架（配对序列与指标）');
{
  const seq1 = D.simpleOrder(4, 12, 20240607);
  const seq2 = D.simpleOrder(4, 12, 20240607);
  ok(seq1.length === 12, '试验序列长度为 12', 'got ' + seq1.length);
  ok(JSON.stringify(seq1) === JSON.stringify(seq2), '同种子产生同序列（三条件可配对）');
  ok(seq1.every(t => t >= 0 && t < 4), '序列值都在目标范围内');
  let noRepeat = true;
  for (let i = 1; i < seq1.length; i++) if (seq1[i] === seq1[i-1]) noRepeat = false;
  ok(noRepeat, '相邻试验不重复同一目标（减少连击惯性）');
  console.log('     序列: ' + seq1.join(' '));
}

// ---------------------------------------------------------------- 指标记录
console.log('\n[6] 指标记录（状态机 simpleRecord）');
{
  const tg = [{ id:0, label:'A', x:300, y:300, r:200 }, { id:1, label:'B', x:1600, y:300, r:200 }];
  D.setTargets(tg);
  // 造一个"正在计时"的状态机状态
  D.setT({ kind:'basic', rounds:[{mag:1.0}], ri:0, per:12,
           order:[0,1], done:0, hits:0, msList:[], results:[],
           phase:'run', targetId:0,
           trialStart: globalThis.performance.now() - 1234, travelAtStart: 0 });
  D.S.handTravel = 500;
  D.simpleRecord(tg[0]);
  const log = D.getExpLog();
  ok(log.length === 1, 'simpleRecord 写入了一条记录', 'got ' + log.length);
  if (log.length) {
    const r = log[0];
    ok(r.correct === 1, '正确性判定正确', 'got ' + r.correct);
    ok(r.ms >= 1000 && r.ms < 5000, '耗时被记录且量级合理', 'ms=' + r.ms);
    ok(r.travel === 500, '手部移动距离被记录', 'travel=' + r.travel);
    ok(r.cond === 'basic', '条件标签被记录');
  }
  // 选错
  D.setT({ kind:'basic', rounds:[{mag:1.0}], ri:0, per:12,
           order:[0,1], done:1, hits:1, msList:[], results:[],
           phase:'run', targetId:0,
           trialStart: globalThis.performance.now() - 500, travelAtStart: 0 });
  D.simpleRecord(tg[1]);
  const log2 = D.getExpLog();
  ok(log2.length === 2 && log2[1].correct === 0, '选错时 correct=0');
}

fs.rmSync(tmpDir, { recursive: true, force: true });

console.log('\n' + '='.repeat(76));
console.log('结果: ' + pass + ' 通过, ' + fail + ' 失败');
console.log('='.repeat(76));
process.exit(fail ? 1 : 0);
