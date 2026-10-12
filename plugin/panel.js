// panel.js —— 侧栏外壳的逻辑（脚本必须是外部文件，MV3 的 CSP 禁止内联脚本）
//
// 侧栏是兜底路径：正常情况下点扩展图标是在【页面上开浮层】，
// 只有浮层注入失败（比如站点限制脚本注入）时才退回侧栏。

(function () {
  const frame = document.getElementById('frame');
  const fb = document.getElementById('fb');

  // 如果 iframe 加载失败（比如忘了跑同步脚本），显示提示而不是白屏
  let ok = false;
  frame.addEventListener('load', () => { ok = true; });
  setTimeout(() => {
    if (!ok) {
      fb.style.display = 'block';
      frame.style.display = 'none';
    }
  }, 2500);

  // 侧栏里也可以直接取正文（走后台 -> content script）
  window.addEventListener('error', ev => {
    console.warn('[阅读辅助/panel]', ev && ev.message);
  });
})();
