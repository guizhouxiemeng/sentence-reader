/**
 * verify-oneeuro.mjs — 用官方 groundTruth.csv 验证 1€ filter 实现
 *
 * 为什么必须做这一步
 * ------------------
 * 这个项目已经因为"自己写滤波"反复踩坑（截止频率下限设错、beta 被增益放大、
 * 参数耦合进模式里改不动）。把滤波换成官方实现后，还要确认【我们的搬运没出错】。
 * 官方仓库提供了 groundTruth.csv（1201 行，含 signal/noisy/filtered 三列），
 * 用同一组参数重算 filtered，逐行对比即可把"滤波是否正确"变成事实而非猜测。
 *
 * 参数来源：casiez/OneEuroFilter 的 C++ 实现默认构造
 *   （README 说明该文件由 C++ 实现生成，见仓库说明）
 *
 * 用法： node tools/verify-oneeuro.mjs
 */
import fs from 'node:fs';
import path from 'node:path';
import { OneEuroFilter } from '../demo/vendor/oneEuroFilter.js';

const CACHE = 'D:/projects/gaze-project/.ghcache';
const GT = path.join(CACHE, 'groundTruth.csv');

if (!fs.existsSync(GT)) {
  console.error('缺少 groundTruth.csv（预期在 ' + GT + '）');
  process.exit(1);
}

const lines = fs.readFileSync(GT, 'utf8').trim().split('\n');
const header = lines[0].split(',');
console.log('='.repeat(84));
console.log('1€ filter 官方标准数据验证');
console.log('='.repeat(84));
console.log('  列: ' + header.join(', '));
console.log('  数据行数: ' + (lines.length - 1));

// 逐行解析
const rows = [];
for (let i = 1; i < lines.length; i++) {
  const p = lines[i].split(',');
  if (p.length < 4) continue;
  rows.push({
    t: parseFloat(p[0]),
    signal: parseFloat(p[1]),
    noisy: parseFloat(p[2]),
    filtered: parseFloat(p[3]),
  });
}
console.log('  解析成功: ' + rows.length + ' 行');

// ------------------------------------------------------------------
//  参数搜索：官方未在 README 里写明生成该文件用的参数，
//  所以这里用"标称常用值"为起点做一次小范围搜索，
//  找到能把最大误差压到 1e-4 以下的组合即认为实现正确。
//  这不是"调参调出来的拟合"，而是确认算法与官方一致 ——
//  因为只有正确的实现才能在某一组参数上逐行重合。
// ------------------------------------------------------------------
function run(mincutoff, beta, dcutoff, freq) {
  const f = new OneEuroFilter(freq, mincutoff, beta, dcutoff);
  const out = new Array(rows.length);
  for (let i = 0; i < rows.length; i++) {
    out[i] = f.filter(rows[i].noisy, rows[i].t);
  }
  return out;
}

function maxErr(out) {
  let m = 0, sum = 0;
  for (let i = 0; i < rows.length; i++) {
    const e = Math.abs(out[i] - rows[i].filtered);
    if (e > m) m = e;
    sum += e;
  }
  return { max: m, mean: sum / rows.length };
}

console.log();
console.log('='.repeat(84));
console.log('用官方参数验证');
console.log('='.repeat(84));
// 参数取自官方 /cpp/Test.cpp 与 /javascript/test.js：
//   frequency=120Hz  mincutoff=1.0  beta=0.1  dcutoff=1.0
// 官方 /test.py 的判据是 |filtered 差| > 0.0001 即失败。
const OFFICIAL = { freq: 120, mincutoff: 1.0, beta: 0.1, dcutoff: 1.0 };
console.log('  frequency=' + OFFICIAL.freq + '  mincutoff=' + OFFICIAL.mincutoff +
            '  beta=' + OFFICIAL.beta + '  dcutoff=' + OFFICIAL.dcutoff);
const out0 = run(OFFICIAL.mincutoff, OFFICIAL.beta, OFFICIAL.dcutoff, OFFICIAL.freq);
const e0 = maxErr(out0);
console.log('  最大误差: ' + e0.max.toExponential(3) +
            '　平均误差: ' + e0.mean.toExponential(3));
console.log('  官方判据: 最大误差 < 1.0e-4');
console.log('  结果: ' + (e0.max < 1e-4 ? '通过 ✓' : '不通过 ✗'));

// 逐行找第一个超出容差的位置，便于定位
if (e0.max >= 1e-4) {
  for (let i = 0; i < rows.length; i++) {
    const d = Math.abs(out0[i] - rows[i].filtered);
    if (d > 1e-4) {
      console.log('  首个超差点: 第 ' + (i + 1) + ' 行  t=' + rows[i].t +
                  '  期望 ' + rows[i].filtered + '  实得 ' + out0[i].toFixed(7) +
                  '  差 ' + d.toExponential(3));
      break;
    }
  }
}
const best = { mc: OFFICIAL.mincutoff, b: OFFICIAL.beta, dc: OFFICIAL.dcutoff, err: e0 };

// ------------------------------------------------------------------
//  判定
// ------------------------------------------------------------------
console.log();
console.log('='.repeat(84));
console.log('结论');
console.log('='.repeat(84));
const ok = best.err.max < 1e-4;
if (ok) {
  console.log('  ✓ 逐行重合（最大误差 ' + best.err.max.toExponential(2) + ' < 1e-4）');
  console.log('    -> 我们的 1€ filter 搬运与官方实现一致，可以放心接进 reader。');
  console.log('    -> 使用的参数：freq(由时间戳自动更新)  mincutoff=' + best.mc +
              '  beta=' + best.b + '  dcutoff=' + best.dc);
} else {
  console.log('  ✗ 未能重合（最大误差 ' + best.err.max.toExponential(2) + '）');
  console.log('    -> 实现可能与官方不一致，需逐行核对。');
  console.log('    提示：官方 groundTruth 由 C++ 实现生成，');
  console.log('          其 dcutoff 默认值或初始化方式可能与我们不同。');
}

// ------------------------------------------------------------------
//  顺带给出"抖动 vs 延迟"的量化，用于判断我们的参数是否合理
// ------------------------------------------------------------------
console.log();
console.log('='.repeat(84));
console.log('顺带量化：不同 mincutoff 下的"抖动抑制"与"延迟"');
console.log('='.repeat(84));
console.log('  用官方数据里的 noisy 列做输入，统计：');
console.log('    抖动 = 滤波输出的一阶差分标准差（越小越稳）');
console.log('    延迟 = 输出与 signal 的互相关最大处的滞后（帧，越小越跟手）');
console.log();
console.log('  mincutoff     抖动          延迟');
console.log('  ' + '-'.repeat(60));
for (const mc of [0.2, 0.5, 1.0, 2.0, 4.0]) {
  const out = run(mc, best.b, best.dc, 120);
  // 抖动
  let js = 0, jsn = 0;
  for (let i = 1; i < out.length; i++) { js += (out[i] - out[i - 1]) ** 2; jsn++; }
  const jitter = Math.sqrt(js / jsn);
  // 延迟：找使 out[i] 最接近 signal[i-lag] 的 lag
  let bestLag = 0, bestC = -Infinity;
  for (let lag = 0; lag <= 30; lag++) {
    let c = 0, n = 0;
    for (let i = lag; i < out.length; i++) { c += out[i] * rows[i - lag].signal; n++; }
    c /= (n || 1);
    if (c > bestC) { bestC = c; bestLag = lag; }
  }
  console.log('  mincutoff=' + String(mc).padEnd(6) +
              '  抖动=' + jitter.toFixed(5).padEnd(12) +
              '  延迟=' + (bestLag * 8.33).toFixed(0) + ' ms');
}
console.log();
console.log('  注：官方文档给出的预算判据是"总延迟 < 60ms，其中 40~50ms 是固有延迟，');
console.log('      所以留给滤波的预算只有 10~20ms"。上表可用于判断参数是否越界。');
