// verify-url.js — 验证 demo 的基准目录推导逻辑在各种访问形式下都正确
// 关键点：从脚本自身 URL 推导基准，而不是从 location.href（后者在 /demo 无尾斜杠时会算错）

function baseFromScriptUrl(scriptSrc) {
  // 与 demo/index.html 中同一个表达式
  return scriptSrc.replace(/[^/]*$/, '');
}

const cases = [
  // 脚本自身 URL：永远是带文件名的完整地址，与"地址栏里是 /demo 还是 /demo/"无关
  { page: 'http://127.0.0.1:8765/demo',          script: 'http://127.0.0.1:8765/demo/index.html' },
  { page: 'http://127.0.0.1:8765/demo/',         script: 'http://127.0.0.1:8765/demo/index.html' },
  { page: 'http://127.0.0.1:8765/demo/index.html', script: 'http://127.0.0.1:8765/demo/index.html' },
  { page: 'https://example.com/a/b/c/',           script: 'https://example.com/a/b/c/index.html' },
];

let bad = 0;
console.log('=== 基准目录推导（从脚本自身 URL）===');
for (const c of cases) {
  const base = baseFromScriptUrl(c.script);
  const bundle = new URL('../vendor/vision_bundle.js', base).href;
  const model = new URL('model.json', base).href;
  const okBundle = bundle.endsWith('/vendor/vision_bundle.js');
  const okModel = /\/model\.json$/.test(model) && !/^http:\/\/127\.0\.0\.1:8765\/model\.json$/.test(model);
  if (!okBundle || !okModel) bad++;
  console.log(`${okBundle && okModel ? 'PASS' : 'FAIL'}  地址栏 ${c.page}`);
  console.log(`        base   ${base}`);
  console.log(`        bundle ${bundle}`);
  console.log(`        model  ${model}`);
}

console.log('\n=== 对比：如果错误地用 location.href 作基准 ===');
for (const c of cases) {
  const wrongModel = new URL('model.json', c.page).href;
  const same = wrongModel === new URL('model.json', baseFromScriptUrl(c.script)).href;
  console.log(`  地址栏 ${c.page}`);
  console.log(`        → model ${wrongModel}${same ? '  (恰好对)' : '  ← 错！'}`);
}

console.log('\n' + (bad === 0 ? '脚本 URL 基准推导在所有形式下都正确 ✓' : `${bad} 项失败 ✗`));
process.exit(bad === 0 ? 0 : 1);
