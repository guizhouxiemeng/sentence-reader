// smoke-demo.js — 校验 demo 依赖的资源都可访问，且 model.json 结构完整
const http = require('http');
const BASE = 'http://127.0.0.1:8765';

function get(pathname) {
  return new Promise((resolve) => {
    const r = http.get(BASE + pathname, { timeout: 20000 }, (res) => {
      const chunks = [];
      res.on('data', (c) => chunks.push(c));
      res.on('end', () => resolve({ pathname, status: res.statusCode, buf: Buffer.concat(chunks) }));
    });
    r.on('timeout', () => { r.destroy(); resolve({ pathname, status: 'TIMEOUT' }); });
    r.on('error', (e) => resolve({ pathname, status: 'ERR ' + (e.code || e.message) }));
  });
}

(async () => {
  const paths = [
    '/demo',                                        // 目录索引
    '/demo/index.html',
    '/demo/model.json',
    '/vendor/vision_bundle.js',
    '/vendor/face_landmarker.task',
    '/vendor/wasm/vision_wasm_internal.wasm',
  ];
  let bad = 0;
  for (const p of paths) {
    const r = await get(p);
    const ok = r.status === 200;
    if (!ok) bad++;
    console.log(`${ok ? 'PASS' : 'FAIL'}  ${String(r.status).padEnd(6)} ${String(r.buf ? r.buf.length : 0).padStart(9)}  ${p}`);
  }

  // model.json 结构校验：demo 端的推理完全依赖这些字段
  const m = await get('/demo/model.json');
  if (m.status === 200) {
    try {
      const J = JSON.parse(m.buf.toString('utf8'));
      console.log('\n--- model.json 结构 ---');
      console.log('  特征维度        :', J.meta.features.length);
      console.log('  特征顺序        :', J.meta.features.join(', '));
      console.log('  集成成员数      :', J.ensembles.length);
      console.log('  训练屏幕尺寸    : %d x %d (对角线 %d)', J.meta.screen.w, J.meta.screen.h, J.meta.screen.diag);
      console.log('  训练集误差(乐观):', J.meta.insample_err_norm.toFixed(4));
      console.log('  泛化能力参照    :', J.meta.cv_reference_norm, '(来自 train.py 的按目标位置交叉验证)');
      console.log('  种子间分歧 中位 : %s px', J.meta.seed_disag_median_px.toFixed(1));
      console.log('  温度标定 T      :', J.temp.toFixed(2));
      const e0 = J.ensembles[0];
      console.log('  第 1 折层结构   :', e0.layers.map((l) => l.W.length + 'x' + l.W[0].length).join(' -> '));
      // 逐层形状必须能串起来，否则浏览器里会静默算出 NaN
      let dim = J.meta.features.length, okShape = true;
      for (const L of e0.layers) {
        if (L.W[0].length !== dim) { console.log(`  ✗ 层输入维度不匹配: 期望 ${dim}, 实际 ${L.W[0].length}`); okShape = false; }
        if (L.b.length !== L.W.length) { console.log('  ✗ 偏置长度与输出维度不符'); okShape = false; }
        dim = L.W.length;
      }
      if (okShape && dim !== 4) { console.log(`  ✗ 最后一层输出 ${dim}，应为 4 (mu_x, mu_y, log_sx, log_sy)`); okShape = false; }
      console.log('  层形状串联      :', okShape ? 'OK' : '有问题');
      if (!okShape) bad++;
      // 所有折都要形状一致
      for (let i = 1; i < J.ensembles.length; i++) {
        const L = J.ensembles[i].layers;
        if (L[0].W[0].length !== J.meta.features.length || L[L.length - 1].W.length !== 4) {
          console.log(`  ✗ 第 ${i + 1} 折形状不一致`); bad++;
        }
      }
      // 用一条零向量试算，确认不会产生 NaN
      let h = new Array(J.meta.features.length).fill(0);
      for (let li = 0; li < e0.layers.length; li++) {
        const L = e0.layers[li], out = new Array(L.W.length);
        for (let r = 0; r < L.W.length; r++) {
          let s = L.b[r];
          for (let c = 0; c < L.W[r].length; c++) s += L.W[r][c] * h[c];
          out[r] = li < e0.layers.length - 1 ? Math.max(0, s) : s;
        }
        h = out;
      }
      const finite = h.every(Number.isFinite);
      console.log('  零输入试算输出  :', h.map((v) => v.toFixed(3)).join(', '), finite ? '(有限值 OK)' : '(含 NaN/Inf ✗)');
      if (!finite) bad++;
    } catch (e) {
      console.log('  model.json 解析失败:', e.message);
      bad++;
    }
  }

  console.log('\n' + (bad === 0 ? 'demo 资源与模型结构全部正常 ✓' : `${bad} 项有问题 ✗`));
  process.exit(bad === 0 ? 0 : 1);
})();
