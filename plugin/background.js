// background.js —— 扩展的 service worker（MV3）
//
// 职责：
//   ① 点扩展图标 → 在【当前网页里】注入浮层阅读界面（不挤占屏幕，不用侧栏）
//   ② 转发消息（取正文 / 打高亮 / 开浮层）
//
// 为什么优先用「页面内浮层」而不是侧栏：
//   content script 本身就运行在页面上下文里，chrome.* 可用，
//   所以界面可以直接叠在原文上 —— 既没有 iframe 的来源问题，
//   也不用把用户的空间分一半给侧栏。侧栏作为兜底保留。

const DEBUG = true;
const log = (...a) => { if (DEBUG) console.log('[阅读辅助/bg]', ...a); };

let targetTabId = null;

function readable(t) {
  if (!t || t.id == null) return false;
  // 注意：只有拿到 tabs 权限（或 activeTab 已授予）时 t.url 才有值。
  // 读不到 url 时这里会一律返回 false，表现为"找不到可读取的网页标签页"。
  const u = t.url || '';
  if (!u) {
    log('标签页 ' + t.id + ' 的 url 读不到（权限不足？）标题=' + (t.title || ''));
    return false;
  }
  return /^https?:/i.test(u);
}

async function resolveTabId(preferred) {
  if (preferred != null) {
    try { const t = await chrome.tabs.get(preferred); if (readable(t)) return t.id; } catch (e) {}
  }
  if (targetTabId != null) {
    try { const t = await chrome.tabs.get(targetTabId); if (readable(t)) return targetTabId; }
    catch (e) { targetTabId = null; }
  }
  // 侧栏/独立页打开时"当前标签页"可能是扩展页面本身 —— 要跳过
  const inWin = await chrome.tabs.query({ active: true, currentWindow: true });
  log('当前窗口活动标签: ' + (inWin[0] ? ('id=' + inWin[0].id + ' url=' + (inWin[0].url || '(空)')) : '无'));
  if (inWin.length && readable(inWin[0])) return inWin[0].id;
  const all = (await chrome.tabs.query({})).filter(readable);
  if (all.length) {
    const same = all.filter(t => t.windowId === (inWin[0] && inWin[0].windowId));
    return (same.length ? same : all).slice(-1)[0].id;
  }
  return null;
}

// 确保 content.js 已注入，返回 tabId
async function ensureInjected(preferred) {
  const tabId = await resolveTabId(preferred);
  if (tabId == null) {
    const all = await chrome.tabs.query({});
    throw new Error('找不到可读取的网页标签页（当前共 ' + all.length +
      ' 个标签页，但没有 http/https 的）—— 请先切到文章页，再点扩展图标');
  }
  let tab = null;
  try { tab = await chrome.tabs.get(tabId); } catch (e) {}
  const url = (tab && tab.url) || '';
  if (/^(chrome|edge|about|chrome-extension|edge-extension|devtools):/i.test(url)) {
    throw new Error('当前是浏览器内部页面，无法读取（请切到文章页）');
  }
  // 先问一句在不在，避免每次发消息都重新注入。
  //  重新注入本身有重入守卫兜着，但守卫依赖 window.__rfInjected ——
  //  扩展重载或页面刷新后隔离世界是全新的，守卫失效、脚本整体重跑，
  //  会把 content.js 里的状态（已包裹的句子节点）清空，
  //  表现为"原文高亮突然全没了"。
  let alive = false;
  try {
    const pong = await chrome.tabs.sendMessage(tabId, { type: 'ping' });
    alive = !!(pong && pong.ok);
  } catch (e) { alive = false; }
  if (alive) {
    log('content.js 已在 tab ' + tabId + '，跳过注入');
    return tabId;
  }

  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
    log('已注入 content.js 到 tab ' + tabId);
  } catch (e) {
    const m = (e && e.message) || String(e);
    // 区分两种情况：已经注入过（可以继续），和权限不足（必须报错）
    if (/Cannot access contents of url|must request permission/i.test(m)) {
      throw new Error('没有权限读取这个页面（' + m + '）' +
        '　→ 请到扩展管理页重新加载扩展，确认已授予"读取和更改您在所访问网站上的数据"');
    }
    // 其余情况多半是重复注入，继续走后面的 sendMessage
    log('注入 content.js 失败（可能是已注入过）:', m);
  }
  return tabId;
}

async function doExtract(preferred) {
  const tabId = await ensureInjected(preferred);
  const resp = await chrome.tabs.sendMessage(tabId, { type: 'extractArticle' });
  if (!resp) return { ok: false, error: '页面脚本没有返回内容' };
  if (resp.ok) {
    // 打印正文容器与字数，便于判断"提取范围是否过宽"
    // （现场出现过一篇技术文章提取出 346 句，明显是把非正文也算进来了）
    log('提取成功：' + resp.paras.length + ' 段' +
        '　容器=' + resp.rootTag + (resp.rootSel ? '(' + resp.rootSel + ')' : '') +
        '　容器字数=' + resp.rootChars +
        '　标题=' + resp.title);
  } else {
    log('提取失败：', resp.error);
  }
  return resp;
}

// 点图标：在页面里开/关浮层
chrome.action.onClicked.addListener(async (tab) => {
  targetTabId = tab && tab.id != null ? tab.id : null;
  log('点击图标，目标标签页 =', targetTabId, tab && tab.url);
  try {
    const tabId = await ensureInjected(targetTabId);
    const r = await chrome.tabs.sendMessage(tabId, { type: 'toggleOverlay' });
    log('toggleOverlay 结果:', r);
  } catch (e) {
    log('开浮层异常:', e && e.message);
    // 兜底：用侧栏
    try { await chrome.sidePanel.open({ tabId: tab.id }); }
    catch (e2) {
      try { await chrome.sidePanel.open({ windowId: tab.windowId }); }
      catch (e3) { log('侧栏也打不开:', e3 && e3.message); }
    }
  }
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;

  if (msg.type === 'ping') {
    sendResponse({ ok: true, targetTabId });
    return true;
  }

  if (msg.type === 'extract') {
    (async () => {
      try { sendResponse(await doExtract(msg.tabId)); }
      catch (e) { sendResponse({ ok: false, error: '后台异常：' + ((e && e.message) || e) }); }
    })();
    return true;
  }

  if (msg.type === 'highlight') {
    (async () => {
      try {
        const tabId = await ensureInjected(null);
        // 注意：content.js 靠 text 做"句子级"匹配，只传 index 的话它拿不到句子文本，
        // 只能退化成整段高亮 —— 现场表现就是"原文整段变蓝，而不是那一句"。
        // 之前这里漏传了 text，是个很低级的转发 bug。
        const r = await chrome.tabs.sendMessage(tabId, {
          type: 'highlight', index: msg.index, text: msg.text || '' });
        sendResponse(r || { ok: true });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }

  if (msg.type === 'toggleOverlay') {
    (async () => {
      try {
        const tabId = await ensureInjected(msg.tabId);
        const r = await chrome.tabs.sendMessage(tabId, { type: 'toggleOverlay' });
        sendResponse(r || { ok: false, error: '无响应' });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }

  if (msg.type === 'tabInfo') {
    (async () => {
      try {
        const tabId = await resolveTabId(msg.tabId);
        if (tabId == null) { sendResponse({ ok: false, error: '找不到标签页' }); return; }
        const t = await chrome.tabs.get(tabId);
        sendResponse({ ok: true, url: (t && t.url) || '', title: (t && t.title) || '' });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }

  if (msg.type === 'closeOverlay') {
    (async () => {
      try {
        const tabId = await resolveTabId(msg.tabId);
        if (tabId == null) { sendResponse({ ok: false, error: '找不到标签页' }); return; }
        const r = await chrome.tabs.sendMessage(tabId, { type: 'closeOverlay' });
        sendResponse(r || { ok: true });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }

  if (msg.type === 'hlDebug') {
    (async () => {
      try {
        const tabId = await ensureInjected(msg.tabId);
        const r = await chrome.tabs.sendMessage(tabId, { type: 'hlDebug' });
        sendResponse(r || { ok: false, error: '无响应' });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }

  if (msg.type === 'listTabs') {
    (async () => {
      try {
        const all = (await chrome.tabs.query({})).filter(readable);
        sendResponse({ ok: true, tabs: all.map(t => ({
          id: t.id, title: t.title || '(无标题)', url: t.url || '', active: !!t.active })) });
      } catch (e) { sendResponse({ ok: false, error: (e && e.message) || String(e) }); }
    })();
    return true;
  }
});

chrome.runtime.onInstalled.addListener(() => log('已安装/更新'));
