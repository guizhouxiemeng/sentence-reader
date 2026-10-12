// verify-solve.js — 直接测试 demo 里的 ridgeFit 在三套数据上的数值稳定性
//
// 背景：HUD 出现「光标 (NaN, NaN)」而留一误差却正常，说明全量拟合的系数是 NaN。
// 怀疑是病态正规方程（条件数 5.6e11）导致手写高斯消元溢出。这里用真实数据
// 把三种实现放在一起对比，不靠推断。
const fs = require('fs');

// ---------- 被测实现 1：与 demo/index.html 当前版本一致（归一化 + 保护 + 残差校验）----------
function ridgeFitCurrent(X, y, lambda) {
  const n = X.length, d0 = X[0].length, d = d0 + 1;
  const mu = new Array(d0).fill(0), sd = new Array(d0).fill(0);
  for (let j = 0; j < d0; j++) {
    let m = 0;
    for (let i = 0; i < n; i++) m += X[i][j];
    m /= n;
    let v = 0;
    for (let i = 0; i < n; i++) v += (X[i][j] - m) ** 2;
    mu[j] = m; sd[j] = Math.sqrt(v / n) || 1e-9;
  }
  const A = [], b = [];
  for (let i = 0; i < d; i++) { A.push(new Array(d).fill(0)); b.push(0); }
  for (let k = 0; k < n; k++) {
    const x = new Array(d);
    for (let j = 0; j < d0; j++) x[j] = (X[k][j] - mu[j]) / sd[j];
    x[d0] = 1;
    for (let i = 0; i < d; i++) {
      b[i] += x[i] * y[k];
      for (let j = 0; j < d; j++) A[i][j] += x[i] * x[j];
    }
  }
  for (let i = 0; i < d0; i++) A[i][i] += lambda;
  for (let i = 0; i < d; i++) {
    let piv = i;
    for (let r = i + 1; r < d; r++) if (Math.abs(A[r][i]) > Math.abs(A[piv][i])) piv = r;
    if (piv !== i) {
      const t = A[i]; A[i] = A[piv]; A[piv] = t;
      const tb = b[i]; b[i] = b[piv]; b[piv] = tb;
    }
    const p = A[i][i];
    if (!Number.isFinite(p) || Math.abs(p) < 1e-9) return { beta: null, why: '主元过小 @' + i };
    for (let r = 0; r < d; r++) {
      if (r === i) continue;
      const f = A[r][i] / p;
      if (!Number.isFinite(f) || f === 0) continue;
      for (let cc = i; cc < d; cc++) A[r][cc] -= f * A[i][cc];
      b[r] -= f * b[i];
    }
  }
  const betaN = new Array(d);
  for (let i = 0; i < d; i++) {
    betaN[i] = b[i] / A[i][i];
    if (!Number.isFinite(betaN[i]) || Math.abs(betaN[i]) > 1e8) return { beta: null, why: '解越界 @' + i };
  }
  let ss = 0, sy = 0;
  const ym = y.reduce((a, v) => a + v, 0) / n;
  for (let k = 0; k < n; k++) {
    let pr = betaN[d0];
    for (let j = 0; j < d0; j++) pr += betaN[j] * ((X[k][j] - mu[j]) / sd[j]);
    ss += (y[k] - pr) ** 2; sy += (y[k] - ym) ** 2;
  }
  if (!Number.isFinite(ss) || ss > sy * 1.01) return { beta: null, why: '残差校验失败' };
  const beta = new Array(d);
  let inter = betaN[d0];
  for (let j = 0; j < d0; j++) { const w = betaN[j] / sd[j]; beta[j] = w; inter -= w * mu[j]; }
  beta[d0] = inter;
  for (const v of beta) if (!Number.isFinite(v)) return { beta: null, why: '反变换出现 NaN' };
  return { beta, why: null, ss, sy };
}

// ---------- 被测实现 2：旧版（未归一化，无保护）—— 用于复现 NaN ----------
function ridgeFitOld(X, y, lambda) {
  const n = X.length, d = X[0].length;
  const A = [], b = [];
  for (let i = 0; i < d; i++) { A.push(new Array(d).fill(0)); b.push(0); }
  for (let k = 0; k < n; k++) {
    const x = X[k];
    for (let i = 0; i < d; i++) {
      b[i] += x[i] * y[k];
      for (let j = 0; j < d; j++) A[i][j] += x[i] * x[j];
    }
  }
  for (let i = 0; i < d - 1; i++) A[i][i] += lambda;
  for (let i = 0; i < d; i++) {
    let piv = i;
    for (let r = i + 1; r < d; r++) if (Math.abs(A[r][i]) > Math.abs(A[piv][i])) piv = r;
    if (piv !== i) { const t = A[i]; A[i] = A[piv]; A[piv] = t; const tb = b[i]; b[i] = b[piv]; b[piv] = tb; }
    const p = A[i][i];
    if (Math.abs(p) < 1e-12) return { beta: null, why: '主元过小' };
    for (let r = 0; r < d; r++) {
      if (r === i) continue;
      const f = A[r][i] / p;
      for (let cc = i; cc < d; cc++) A[r][cc] -= f * A[i][cc];
      b[r] -= f * b[i];
    }
  }
  const beta = new Array(d);
  for (let i = 0; i < d; i++) beta[i] = b[i] / A[i][i];
  return { beta, why: null };
}

const cases = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
let bad = 0;
for (const cs of cases) {
  console.log('\n=== ' + cs.name + ' ===');
  console.log('  设计矩阵 ' + cs.X.length + ' x ' + cs.X[0].length);
  const oldR = ridgeFitOld(cs.X, cs.y, 0.01);
  const oldNaN = oldR.beta && oldR.beta.some((v) => !Number.isFinite(v));
  console.log('  旧实现(未归一化): ' + (oldR.beta ? (oldNaN ? '✗ 含 NaN' : '有限值，最大 |β|='
    + Math.max(...oldR.beta.map(Math.abs)).toExponential(2)) : '拒绝: ' + oldR.why));
  const newR = ridgeFitCurrent(cs.X, cs.y, 0.01);
  if (!newR.beta) {
    console.log('  新实现(归一化+保护): ✗ 拒绝: ' + newR.why);
    bad++;
  } else {
    const pred = cs.X.map((x) => {
      let p = newR.beta[x.length];
      for (let j = 0; j < x.length; j++) p += newR.beta[j] * x[j];
      return p;
    });
    const err = Math.sqrt(pred.reduce((a, p, i) => a + (p - cs.y[i]) ** 2, 0) / pred.length);
    const range = Math.max(...pred) - Math.min(...pred);
    console.log('  新实现(归一化+保护): ✓ 最大 |β|=' + Math.max(...newR.beta.map(Math.abs)).toExponential(2)
      + '  RMSE=' + err.toFixed(1) + '  预测跨度=' + range.toFixed(0));
    if (!Number.isFinite(err) || !Number.isFinite(range) || range < 1) { console.log('    ✗ 输出异常'); bad++; }
  }
}
console.log('\n' + (bad === 0 ? '新求解器全部可靠 ✓' : bad + ' 项失败 ✗'));
process.exit(bad === 0 ? 0 : 1);
