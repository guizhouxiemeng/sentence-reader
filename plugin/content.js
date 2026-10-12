// content.js —— 注入到网页里，提供「原地阅读辅助」
//
// 设计选择：直接在原网页上叠加一个浮层界面，而不是开侧栏。
//   ① content script 就在页面上下文里，chrome.* 可用（不需要 iframe 绕来源问题）
//   ② 不挤占屏幕，高亮就在原文上
//   ③ 段落结构天然保持原样
//
// 样式用 Shadow DOM 隔离，避免与宿主页面互相污染（这个页面自带 62px 的
// font-size、还有各种 !important，不隔离一定会乱）。
//
// 只做三件事：
//   ① 提取正文段落（{type:'extractArticle'}）
//   ② 在原文上打高亮（{type:'highlight'}）
//   ③ 按需注入/移除浮层界面（{type:'toggleOverlay'}）

(function () {
  if (window.__rfInjected) {
    // 已经注入过：只把已有的控制接口暴露出去，避免重复绑定
    return;
  }
  window.__rfInjected = true;

  // =========================================================================
  //  一、正文提取
  // =========================================================================
  // 明显的"目录/导航/侧栏"容器 —— 这类容器里的 li/a 很容易被当成正文段落。
  // 现场问题："还会受到左侧边栏的干扰"（ACM 那篇文章左侧有一列目录）。
  const SIDEBAR_LIKE = [
    'nav', 'aside', 'header', 'footer',
    '[role="navigation"]', '[role="complementary"]', '[role="banner"]',
    '.toc', '#toc', '.table-of-contents', '.contents', '.outline',
    '.sidebar', '.side-bar', '.aside', '.menu', '.nav', '.navigation',
    '.breadcrumb', '.related', '.recommend', '.share', '.social',
    '.chapter-nav', '.book-nav', '.left-nav', '.right-nav',
    '[class*="toc"]', '[id*="toc"]', '[class*="sidebar"]', '[class*="outline"]',
  ];

  const NON_CONTENT = [
    'script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside',
    'form', 'iframe', 'svg', 'button', 'select', 'template', 'dialog',
    '[role="navigation"]', '[role="banner"]', '[role="contentinfo"]',
    '[role="complementary"]', '[aria-hidden="true"]',
    '.nav', '.navbar', '.sidebar', '.menu', '.footer', '.header',
    '.comment', '.comments', '.ad', '.ads', '.advertisement', '.cookie',
    '.breadcrumb', '.pagination', '.toolbar', '.share', '.related',
    '[class*="advert"]', '[id*="advert"]', '[class*="recommend"]',
  ];

  // 正文容器候选。顺序有意义：语义化标签优先，再退到常见类名/ID。
  // 新浪这种结构（见现场 DOM）：div.article-content > div.article-content-left
  //   > div.article > p，所以 .article-content / .article 都得在候选里。
  const ROOT_CANDS = [
    'article', 'main', '[role="main"]',
    '.article-content', '.article_content', '.article', '#article',
    '#content', '#main', '.content', '.post', '.post-content',
    '.entry-content', '.markdown-body', '.article-body', '.news-content',
  ];

  function pickRoot() {
    // ------------------------------------------------------------------
    //  选"够长的最小容器"。
    //
    //  早先是"第一个超过 600 字的候选就用"，结果经常选到外层大包裹 ——
    //  把页面的侧栏、相关阅读、推荐位全都算进正文（现场 总段数=106，
    //  对一篇技术文章明显偏多）。
    //
    //  改成：在所有候选中，取【正文字数 >= 800 且 字数最小】的那个。
    //  语义化容器（article/main）天然比 .content 这类更具体，所以会优先被选中；
    //  但也不盲目相信标签名 —— 有些站点 article 里只放了标题。
    // ------------------------------------------------------------------
    const MIN_CHARS = 800;
    let best = null, bestLen = Infinity;
    const seen = new Set();

    for (const sel of ROOT_CANDS) {
      let els;
      try { els = document.querySelectorAll(sel); } catch (e) { continue; }
      els.forEach(el => {
        if (seen.has(el)) return;
        seen.add(el);
        const len = (el.innerText || '').length;
        if (len < MIN_CHARS) return;
        if (len < bestLen) { bestLen = len; best = el; try { best.__rfSel = sel; } catch (e) {} }
      });
    }
    if (best) return best;

    // 没有够长的语义容器：退回正文块最多的那个容器
    let fallback = document.body, fbCount = 0;
    try {
      const all = [...document.querySelectorAll('div,section,td')];
      for (const el of all.slice(0, 400)) {
        const n = el.querySelectorAll('p').length;
        if (n > fbCount) { fbCount = n; fallback = el; }
      }
    } catch (e) {}
    return fallback;
  }

  function extract() {
    // 用 let —— 下面会用页面上的 <h1> 覆盖它。
    //  （上一版写成了 const，赋值时抛 TypeError 被 try/catch 吞掉，
    //    所以"标题取 h1"那个修复其实一直没生效。）
    let title = (document.title || '').trim();
    const root = pickRoot();
    if (!root) return { ok: false, error: '找不到正文容器' };

    // ------------------------------------------------------------------
    //  先在【原页面】上按顺序给候选块打标记，再克隆。
    //
    //  为什么这个顺序很关键：
    //    早先是先克隆、在克隆上过滤（去掉导航/短块/重复），
    //    然后拿过滤后的序号去原页面里找元素 —— 但克隆过滤过的序列
    //    与原页面的完整序列【顺序对不上】，于是段落索引整体漂移。
    //    现场表现就是"面板读到第 32 句，原文高亮在第 12 句"。
    //
    //  现在：原页面里【所有】候选块先编号（属性会被克隆保留），
    //  过滤只发生在克隆上。这样只要认标记，索引永远一致。
    // ------------------------------------------------------------------
    const SEL = 'p,h1,h2,h3,h4,h5,h6,li,blockquote,pre,td,dd';
    let liveAll = [];
    try { liveAll = [...root.querySelectorAll(SEL)]; } catch (e) { liveAll = []; }
    liveAll.forEach((el, k) => {
      try { el.setAttribute('data-rf-index', String(k)); } catch (e) {}
    });

    const clone = root.cloneNode(true);
    NON_CONTENT.forEach(sel => {
      try { clone.querySelectorAll(sel).forEach(e => e.remove()); } catch (e) {}
    });
    SIDEBAR_LIKE.forEach(sel => {
      try { clone.querySelectorAll(sel).forEach(e => e.remove()); } catch (e) {}
    });
    // 被移除的容器里可能带着标记，这里把残留标记清掉，避免误导
    try {
      clone.querySelectorAll('[data-rf-index]').forEach(el => {
        // 这里原来写的是 SEL.join(',') —— 但 SEL 是【字符串】，没有 join，
        //  会抛 TypeError 并被外面的空 catch 吞掉（残留标记清不干净）。
        if (!el.closest || el.closest(SEL)) return;
        el.removeAttribute('data-rf-index');
      });
    } catch (e) {}

    const paras = [];
    const uniq = new Set();
    const seenIdx = new Set();

    clone.querySelectorAll(SEL).forEach(el => {
      const t = (el.innerText || el.textContent || '')
        .replace(/\s+/g, ' ').replace(/\u00a0/g, ' ').trim();
      if (t.length < 10) return;              // 过滤导航碎片
      if (uniq.has(t)) return;                // 去重（很多站有隐藏副本）
      uniq.add(t);

      let idx = null;
      try {
        const m = el.getAttribute('data-rf-index');
        if (m != null && !seenIdx.has(m)) { idx = Number(m); seenIdx.add(m); }
      } catch (e) {}

      paras.push({ block: el.tagName.toLowerCase(), text: t, idx: idx });
    });

    // 少数纯 div 排版的站点：退回整段文字再按空行切
    if (!paras.length) {
      const t = (clone.innerText || clone.textContent || '')
        .replace(/[ \t\u00a0]+/g, ' ').replace(/\n{3,}/g, '\n\n').trim();
      t.split(/\n{2,}/).forEach(x => {
        const y = x.replace(/\s+/g, ' ').trim();
        if (y.length >= 10) paras.push({ block: 'p', text: y, idx: null });
      });
    }

    // 带上容器信息与字数，便于判断"提取范围是否过宽"
    let rootChars = 0;
    try { rootChars = (root.innerText || '').length; } catch (e) {}
    // 标题优先取页面上【看得见】的主标题。
    //  原来直接用 document.title，它的值常带站点后缀
    //  （"… – Communications of the ACM"），和页面上的 <h1> 对不上，
    //  于是题目那一句永远高亮不了（文本匹配失败）。
    try {
      const h1 = document.querySelector('h1');
      const h1t = h1 && (h1.innerText || h1.textContent || '').replace(/\s+/g, ' ').trim();
      if (h1t && h1t.length >= 4 && h1t.length <= 300) title = h1t;
    } catch (e) { void e; }

    return { ok: true, title, url: location.href, paras, rootTag: root.tagName,
             rootChars: rootChars, rootSel: root.__rfSel || null };
  }

  // =========================================================================
  //  二、原文高亮（句子级）
  //
  //  目标：面板里高亮到第几句，网页原文上对应那一句也要亮起来。
  //
  //  做法：把每个段落里的文字节点按句子切开，包成 <span class="rf-sent">。
  //    · 只动【文字节点】，不重建元素 —— 这样宿主页面的布局、
  //      事件监听、CSS 全部不受影响（很多站点靠 JS 绑事件，
  //      一旦重建 DOM 就会失效）。
  //    · 包裹只在必要时做一次，之后靠 .rf-cur 类切换高亮。
  //    · 句子跨多个节点（中间夹着链接、加粗等）时退化为整段高亮，
  //      高亮是附加功能，不能因为它失败影响主流程。
  // =========================================================================
  const BLOCK_SEL = 'p,h1,h2,h3,h4,h5,h6,li,blockquote,pre,td,dd';
  let sentSpans = [];      // [{ el, text, group }]
  let markEls = [];        // [{ el, key }] 段落级回退
  const GROUP_ATTR = 'data-rf-g';

  function clearMarks() {
    lastHitTop = -1;
    clearCur();   // 关浮层、重新包裹时也要把残留高亮熄灭（函数声明会提升）

    // 把包裹真正拆掉：<span class="rf-sent"> 的文字换回父元素。
    //
    //  之前这里只做了 classList.remove('rf-cur')，注释却写着"去掉包裹" ——
    //  名字和注释都说拆，实现没拆。于是下一次包裹时
    //  `if (el.querySelector('.rf-sent')) return;` 会把所有段落都跳过，
    //  sentSpans 永远是空的，页面再也高亮不了。
    //  （过去 buildMarks 一个会话基本只跑一次，第一次没有旧 span 可跳过，
    //    所以一直没暴露；加了"高亮自愈"之后 buildMarks 会重复执行，就踩出来了。）
    const touchedParents = [];
    sentSpans.forEach(m => {
      const sp = m && m.el;
      if (!sp) return;
      try { sp.classList.remove('rf-cur'); } catch (e) {}
      try {
        const par = sp.parentNode;
        if (par) {
          par.replaceChild(document.createTextNode(sp.textContent), sp);
          if (touchedParents.indexOf(par) < 0) touchedParents.push(par);
        }
      } catch (e) {
        console.warn('[阅读辅助/包裹] 拆包裹失败（下次可能包不上）：', e);
      }
    });
    // 合并相邻文字节点：反复包裹/拆开会让文字节点越切越碎，
    //  碎到一个句子跨好几个节点时，包裹就会退化成整段高亮。
    touchedParents.forEach(par => {
      try { par.normalize(); } catch (e) {}
    });

    markEls.forEach(m => {
      if (m && m.el) {
        try { m.el.classList.remove('rf-cur'); } catch (e) {}
      }
    });
    sentSpans = [];
    markEls = [];
  }

  // 把一个文字节点按句子切分并包裹。只需一次。
  function wrapTextNode(node, group) {
    const text = node.nodeValue;
    if (!text || text.length < 4) return;
    const parts = splitSentences(text.replace(/\s+/g, ' '));
    // 单句块（例如 <h2>Vision And Heterogeneous Parallel Computing</h2>）
    // 也要包裹 —— 早先要求"至少两句"才包，于是标题没有对应的 span，
    // 文本匹配自然找不到它，表现就是"标题在原文里不高亮"。
    if (!parts.length) return;

    const frag = document.createDocumentFragment();
    let pos = 0;
    let i = 0;
    // 按句子去原文里顺序定位（跳过空白差异）
    for (const p of parts) {
      const key = p.slice(0, 12);
      // 在剩余文本里找这一句的起点（允许前后空白）
      let at = text.indexOf(key, pos);
      if (at < 0) { at = pos; }
      if (at > pos) {
        frag.appendChild(document.createTextNode(text.slice(pos, at)));
      }
      let end = at + p.length;
      // 扩展到底（原文可能有空格，句子长度按去空格算过）
      let probe = end;
      while (probe < text.length && end - at < p.length + 8 &&
             /\s/.test(text[probe])) probe++;
      end = Math.max(end, Math.min(probe, text.length));

      const sp = document.createElement('span');
      sp.className = 'rf-sent';
      sp.setAttribute(GROUP_ATTR, String(group));
      sp.textContent = text.slice(at, end);
      frag.appendChild(sp);
      sentSpans.push({ el: sp, text: p, group });
      pos = end;
      i++;
    }
    if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
    try {
      node.parentNode.replaceChild(frag, node);
    } catch (e) {
      // 失败就退化为段落级 —— 但必须留下痕迹，否则"整页不高亮"查不出来
      console.warn('[阅读辅助/包裹] 替换文字节点失败（这一句会退化成整段高亮）：', e);
    }
  }

  // 找到某个段落在【原页面】里的元素。
  //   优先级：extract() 时记下的引用 -> data-rf-index 标记 -> 文字匹配（最后手段）
  //   早先只用文字匹配，一段对不上后面全错位，所以现在以引用为主。
  function findParaEl(gi, paraText, paraIdx) {
    // 首选：提取时记下的标记值（与原页面候选块一一对应，不会漂移）
    if (paraIdx !== undefined && paraIdx !== null) {
      try {
        const byMark = document.querySelector('[data-rf-index="' + paraIdx + '"]');
        if (byMark) return byMark;
      } catch (e) {}
    }
    // 这里原来有一行 `const el = lastExtractEls[gi];`，
    //  但那个变量从来没被声明过 —— 走到这里会直接抛 ReferenceError，
    //  把后面的文本兜底也一起废掉，表现为"整页没有高亮"。
    //  它是被 data-rf-index 取代的旧设计（提取是在克隆上做的，
    //  拿不到原文元素下标），所以直接去掉。
    if (paraText) {
      const key = paraText.replace(/\s+/g, ' ').trim().slice(0, 40);
      if (key.length >= 10) {
        try {
          const all = [...document.querySelectorAll(BLOCK_SEL)];
          for (const e of all) {
            const t = (e.innerText || e.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 40);
            if (t && t === key) return e;
          }
        } catch (e) {}
      }
    }
    // 两条路都没找到 —— 这类静默失败最难查，留一行痕迹
    console.warn('[阅读辅助/content] 这段文字在原文里没定位到，无法高亮：',
                 String(paraText || '').slice(0, 40));
    return null;
  }

  // 从提取结果切句（与网页版 TextSource 的切句规则保持一致）
  //  注意：这个名字原本定义在浮层那一大段里，改造浮层时被一起删掉了，
  //  但上面的 buildMarks 还在调用它 —— 所以这里补回来。
  const ABBR = /\b(Mr|Mrs|Ms|Dr|Prof|St|vs|etc|e\.g|i\.e|Fig|Eq|Ref|No|Vol|approx|al)\.$/i;

function splitSentences(block) {
    const out = [];
    let buf = '';
    const CLOSERS = '”"’\')）】」';
    for (let i = 0; i < block.length; i++) {
      const ch = block[i];
      buf += ch;
      // 句末只认 。！？!? —— 【分号不算】。
      //  学术写作里分号通常分隔并列分句：
      //    "…(k = 28, r = .21); negative cognitions (k = 6, r = −.03), or…"
      //  在这里断开会让每句都变成残缺片段（用户实测反馈）。
      let isEnd = '。！？!?'.includes(ch);
      if (!isEnd && ch === '.') isEnd = isPeriodEnd(block, i, buf);
      if (isEnd) {
        // 吃掉紧跟的收尾引号/括号
        while (i + 1 < block.length && CLOSERS.indexOf(block[i + 1]) >= 0) {
          buf += block[++i];
        }
        const t = buf.trim();
        if (t) out.push(t);
        buf = '';
      }
    }
    const t = buf.trim();
    if (t) out.push(t);
    return out;
  }

  // 判断这个 '.' 是不是句子结束。
  //
  //  实测踩到的坑：小数点和编号里的点也会断句 ——
  //    "r = −.03"   被切成 "r = −" + "03)"
  //    "3.5 秒"     被切成 "3." + "5 秒"
  //    "准确率 0.87" 被切成 "准确率 0." + "87"
  //  任何含小数点的文章都会中招，不只是 PDF。
  //
  //  三条判据（见下面注释），比"不是缩写就断"稳得多。
  function isPeriodEnd(block, i, buf) {
    // ① 缩写不算句末（Fig. / e.g. / et al. …）
    if (ABBR.test(buf.trim())) return false;

    // ② 点后面紧跟数字或字母 -> 小数点 / 域名 / 版本号，不是句末
    const next = block[i + 1];
    if (next !== undefined && !/[\s”"’')）】」]/.test(next)) return false;

    // ③ 跳过空白与收尾符号后，下一个字符必须是"能开头的"：
    //    大写字母 / 中文 / 开引号 / 结尾。
    //    这样 "Fig. 3 shows"、"et al. (2015)" 不会被误断，
    //    而 "outcomes. We conducted" 正常断句。
    let k = i + 1;
    while (k < block.length && /[\s”"’')）】」]/.test(block[k])) k++;
    if (k >= block.length) return true;
    //   白名单里必须有半角 [ —— 学术写作的引用编号 [1] [2] 几乎都是半角的，
    //   早先只有全角的 （ 和 【，于是 "samadhi). [2] The earliest" 被粘成一句。
    //   『 也一并补上（中文左双直角引号，和已有的「 配套，之前漏了）。
    return /[A-Z\u4e00-\u9fff\u3400-\u4dbf“「『（【[]/.test(block[k]);
  }

  // ------------------------------------------------------------------
  //  直接在活 DOM 上包裹句子。
  //
  //  为什么加这条路径：原来的做法要求"提取时打的标记 / 克隆出来的文字"
  //  能和活元素对上，中间隔了一次往返。页面一重渲染（重前端站点很常见）
  //  带标记的元素就被换掉，主路径失效；克隆时又移除了导航类元素，
  //  文字兜底也可能对不上 —— 结果就是"句子节点 0 个、高亮全失效"。
  //
  //  包裹这件事本身只需要活 DOM。root 已经是"够长的最小容器"（正文区），
  //  在它下面遍历块级元素即可，不需要知道哪个块对应哪一段。
  // ------------------------------------------------------------------
  function wrapInsideRoot() {
    let root = null;
    try { root = pickRoot(); } catch (e) { console.warn('[阅读辅助/包裹] pickRoot 失败：', e); }
    if (!root) return 0;

    let els = [];
    try { els = [...root.querySelectorAll(BLOCK_SEL)]; } catch (e) {
      console.warn('[阅读辅助/包裹] 查询块级元素失败：', e);
      return 0;
    }

    let nSkip = 0, nNoNode = 0;
    els.forEach((el, k) => {
      // 已经包过的跳过（重复调用时不做无用功）
      if (el.querySelector && el.querySelector('.rf-sent')) { nSkip++; return; }
      // 嵌套在别的块里的块（li 里套 p 之类）跳过外层，避免重复包
      if (el.parentElement && el.parentElement.closest &&
          el.parentElement.closest('.rf-sent')) return;

      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      const nodes = [];
      let n;
      while ((n = walker.nextNode())) {
        if (n.nodeValue && n.nodeValue.trim().length >= 8) nodes.push(n);
      }
      if (!nodes.length) { nNoNode++; return; }
      nodes.forEach(node => {
        try { wrapTextNode(node, k); }
        catch (e) { console.warn('[阅读辅助/包裹] 包文字节点失败：', e); }
      });
    });

    console.log('[阅读辅助/包裹] 活 DOM 直包：块 ' + els.length +
                ' 个，跳过 ' + nSkip + '，无文字节点 ' + nNoNode +
                '　=> 句子节点 ' + sentSpans.length);
    return sentSpans.length;
  }

  function buildMarks(paras) {
    clearMarks();

    // 主路径：直接在活 DOM 上包。不依赖任何往返，抗页面重渲染。
    try {
      if (wrapInsideRoot() > 0) { ensurePageStyle(); return; }
      console.warn('[阅读辅助/包裹] 活 DOM 直包没成功，改用段落往返那条路');
    } catch (e) {
      console.warn('[阅读辅助/包裹] 活 DOM 直包抛异常，改用段落往返那条路：', e);
    }
    if (!paras || !paras.length) {
      console.warn('[阅读辅助/包裹] 没有段落可处理');
      return;
    }

    // 四个计数把"包不上"这件事拆开 —— 之前只有一句"句子节点 0 个"，
    //  分不清是没定位到段落、还是段落里没文字节点、还是切不出句子。
    let nNoEl = 0;        // 段落没在原文里定位到
    let nNoNode = 0;      // 定位到了但里面没有够长的文字节点
    let nNoParts = 0;     // 有文字节点但切不出句子
    let nReplaceFail = 0; // 替换文字节点失败
    let nSkipWrapped = 0; // 已经包过了，跳过

    // ---- 兜底：靠 paras 的往返定位 ----
    paras.forEach((p, gi) => {
      let el = null;
      try {
        el = findParaEl(gi, p.text, p.idx);
      } catch (e) {
        console.warn('[阅读辅助/包裹] findParaEl 抛异常：', e);
      }
      if (!el) { nNoEl++; markEls.push(null); return; }
      markEls.push({ el: el, key: String(p.text || '').slice(0, 60) });

      if (el.querySelector && el.querySelector('.rf-sent')) { nSkipWrapped++; return; }

      const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      const nodes = [];
      let n;
      while ((n = walker.nextNode())) {
        if (n.nodeValue && n.nodeValue.trim().length >= 8) nodes.push(n);
      }
      if (!nodes.length) { nNoNode++; return; }

      nodes.forEach(node => {
        const before = sentSpans.length;
        try {
          wrapTextNode(node, gi);
        } catch (e) {
          console.warn('[阅读辅助/包裹] 包一个文字节点失败：', e);
        }
        if (sentSpans.length === before) nNoParts++;
        if (node.parentNode === null) nReplaceFail++;
      });
    });

    console.log('[阅读辅助/包裹] 段落 ' + paras.length +
                '：定位到 ' + (paras.length - nNoEl) + '，未定位 ' + nNoEl +
                '，无文字节点 ' + nNoNode + '，切不出句子 ' + nNoParts +
                '，已包过 ' + nSkipWrapped +
                '　=> 句子节点 ' + sentSpans.length);
    if (!sentSpans.length) {
      console.warn('[阅读辅助/包裹] 一个句子节点都没包上 —— 原文高亮会全部失效。' +
                   '　上面那行数字指出卡在哪一步。');
      // 实在包不上时，把第一个段落的实际情况打出来，便于对照
      if (paras[0]) {
        console.warn('[阅读辅助/包裹] 第一个段落：idx=' + paras[0].idx +
                     '　block=' + paras[0].block +
                     '　文字前 60 字=' + JSON.stringify(String(paras[0].text || '').slice(0, 60)));
      }
    }
    ensurePageStyle();
  }

  // ------------------------------------------------------------------
  //  按【句子文本】在原文里找并高亮 —— 不再依赖任何编号。
  //
  //  为什么放弃编号方案：
  //    面板有一套编号（句子序号 / 段落号），原页面有另一套（标记值），
  //    两套编号在交界处极容易错位。我为此连续改了四次都没稳定：
  //      ① background 转发时漏传 text
  //      ② 把句子号当段落号传
  //      ③ 标题占用了段落号 0
  //      ④ 用过滤后的数组下标当段落号
  //    根子在于"两个编号系统要用同一个数"，这种耦合本身就脆弱。
  //
  //  换法：句子很长、内容独特，直接拿句子文本去原文里找。
  //    匹配规则：开头 12 字相同 + 长度接近 → 命中。
  //    这样面板传什么都不影响，只要句子文本对得上就行。
  //
  //  重复句子的处理：优先选【上一次命中位置之后】的第一个匹配，
  //  这样顺序阅读时能一路往下走，不会总是跳回文章开头那句。
  // ------------------------------------------------------------------
  let lastHitTop = -1;

  function norm(t) {
    return String(t || '').replace(/\s+/g, ' ').replace(/\u00a0/g, ' ').trim();
  }

  // 把页面上所有高亮清掉。
  //  用全页扫描而不是遍历自己的名单 —— 名单一定会漏：
  //  sentSpans（句子级）、markEls（段落级）、整块回退（任意块级）都会加类，
  //  将来还可能加别的分支。扫描不会漏。
  function clearCur() {
    try {
      const all = document.querySelectorAll('.rf-cur');
      for (let i = 0; i < all.length; i++) {
        try { all[i].classList.remove('rf-cur'); } catch (e) {}
      }
    } catch (e) { void e; }
  }

  function highlight(sentenceText) {
    // 全部熄灭
    // 熄灭上一次的高亮。
    //  必须扫【全页】而不是只清 sentSpans / markEls：
    //  "整块回退"那条路会给任意块级元素加 rf-cur 但不登记，
    //  只清名单的话它永远熄不掉，累积成"好几处同时亮"。
    clearCur();

    const want = norm(sentenceText);
    if (!want || want.length < 4) return 0;
    const head = want.slice(0, 12);

    // 收集所有候选 span，算好它们在页面上的纵向位置
    const cands = [];
    sentSpans.forEach(m => {
      const got = norm(m.text);
      if (!got) return;
      if (got.slice(0, 12) !== head) return;
      // 长度接近才算同一句（避免"前半句相同"的误匹配）
      if (Math.abs(got.length - want.length) > Math.max(8, want.length * 0.35)) return;
      let top = 0;
      try { top = m.el.getBoundingClientRect().top + window.scrollY; } catch (e) {}
      cands.push({ m, top });
    });

    if (!cands.length) {
      // 回退：找"整块文字就等于这一句"的元素。
      //  覆盖两种情况：① 该块没被包裹成功（结构特殊）；
      //  ② 标题这类块本身就只有一句，直接高亮整个块更自然。
      let fallbackEl = null, fallbackTop = 0;
      try {
        const all = document.querySelectorAll(BLOCK_SEL);
        for (const el of all) {
          const got = norm(el.innerText);
          if (!got) continue;
          if (got.slice(0, 12) !== head) continue;
          if (Math.abs(got.length - want.length) > Math.max(8, want.length * 0.35)) continue;
          const top = el.getBoundingClientRect().top + window.scrollY;
          if (!fallbackEl || (top > lastHitTop + 2 && top < fallbackTop)) {
            fallbackEl = el; fallbackTop = top;
            if (top > lastHitTop + 2) break;      // 找到当前位置之后的第一个就够了
          }
        }
      } catch (e) {}

      if (fallbackEl) {
        try { fallbackEl.classList.add('rf-cur'); } catch (e) {}
        lastHitTop = fallbackTop;
        lastHlDebug = { want: want.slice(0, 50), hit: -1, reason: '整块匹配',
                        spans: sentSpans.length, paras: markEls.length };
        try {
          console.log('[阅读辅助/高亮] 整块匹配（该块未被切句）\n  要高亮句: ' +
                      want.slice(0, 55));
        } catch (e) {}
        try {
          const r = fallbackEl.getBoundingClientRect();
          if (r.top < 70 || r.bottom > innerHeight - 70) {
            fallbackEl.scrollIntoView({ block: 'center', behavior: 'smooth' });
          }
        } catch (e) {}
        return -1;
      }

      lastHlDebug = { want: want.slice(0, 50), hit: 0, reason: '原文里没找到这句',
                      spans: sentSpans.length, paras: markEls.length };
      try {
        console.log('[阅读辅助/高亮] 没找到句子（共 ' + sentSpans.length + ' 个句子节点）\n  ' +
                    want.slice(0, 60));
      } catch (e) {}
      return 0;
    }

    // 优先取上一次命中位置之后的；没有就取第一个
    cands.sort((x, y) => x.top - y.top);
    let pick = cands.find(c => c.top > lastHitTop + 2);
    if (!pick) pick = cands[0];
    lastHitTop = pick.top;

    try { pick.m.el.classList.add('rf-cur'); } catch (e) {}

    lastHlDebug = {
      want: want.slice(0, 50),
      hit: 1,
      matched: norm(pick.m.text).slice(0, 50),
      cands: cands.length,
      spans: sentSpans.length,
      paras: markEls.length,
    };
    try {
      console.log('[阅读辅助/高亮] 命中 ' + cands.length + ' 个候选，已高亮\n  要高亮句: ' +
                  want.slice(0, 55) + '\n  实际命中: ' + norm(pick.m.text).slice(0, 55));
    } catch (e) {}

    // 滚动到可见
    try {
      const r = pick.m.el.getBoundingClientRect();
      if (r.top < 70 || r.bottom > innerHeight - 70) {
        pick.m.el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    } catch (e) {}
    return 1;
  }


  // =========================================================================
  //  三、浮层界面
  //
  //  这里【只做容器，不再自己实现一套阅读界面】。
  //
  //  为什么要改：早先 content.js 内联了一整套界面（CSS + HTML 模板 + 讲解器
  //  + 计时逻辑），而 reader_flow.html 里也有同样一整套。两份实现很快分叉 ——
  //  后来在 reader_flow.html 里加的功能（自动/手动模式、重新测速、句长启发式、
  //  静默准备、测试连接）浮层里全都没有，因为浮层走的还是旧代码。
  //  表现就是：改了半天，点图标打开的还是旧界面。
  //
  //  现在浮层用 iframe 装扩展自带的 reader_flow.html：
  //    · iframe 的来源是扩展自己（chrome-extension://），
  //      所以 reader_flow 里 chrome.runtime 可用
  //      （panel.html 用同样的方式加载它，已经验证这条路可行）
  //    · 只有一份实现，改一处两边都对
  //    · reader_flow 通过 background 向本脚本要正文、要高亮，消息协议不变
  // =========================================================================

  const OVERLAY_ID = 'rf-overlay-host';
  let host = null;
  let frame = null;
  let lastHlDebug = null;   // 高亮失败时的诊断信息（{type:'hlDebug'} 会读它）

  const OVERLAY_CSS = `
    :host { all: initial; }
    .rf-pane {
      position: fixed; top: 0; right: 0; height: 100vh;
      width: 480px; max-width: 96vw;
      background: #0f1115;
      border-left: 1px solid #2a3140;
      box-shadow: -14px 0 40px rgba(0,0,0,.45);
      z-index: 2147483000;
      overflow: hidden;
    }
    .rf-pane > iframe {
      border: 0; width: 100%; height: 100%; display: block;
      background: #0f1115;
    }
    /* 左边缘拖拽条：句子长的时候想把界面调宽 */
    .rf-grip {
      position: absolute; left: 0; top: 0; bottom: 0; width: 6px;
      cursor: ew-resize; background: transparent;
    }
    .rf-grip:hover { background: rgba(91,141,239,.35); }
    @media (max-width: 720px) { .rf-pane { width: 100vw; } }
  `;

  function buildOverlay() {
    if (host) return;
    host = document.createElement('div');
    host.id = OVERLAY_ID;
    // 宿主元素本身不参与布局，界面全在 shadow 里绝对定位
    host.style.cssText = 'all:initial;position:fixed;z-index:2147483000;';
    const sh = host.attachShadow({ mode: 'open' });

    const st = document.createElement('style');
    st.textContent = OVERLAY_CSS;

    const pane = document.createElement('div');
    pane.className = 'rf-pane';

    frame = document.createElement('iframe');
    frame.id = 'rf-frame';
    // 指向扩展自己的页面 —— 这样 reader_flow 里才有 chrome.*
    // （早先这个 iframe 指向 http://127.0.0.1:8765/...，来源是本地服务器，
    //   于是 reader_flow 里 chrome 是 undefined，一调用就报
    //   "Cannot read properties of undefined"）
    frame.src = chrome.runtime.getURL('reader_flow.html') + '?extract=1&overlay=1';
    frame.setAttribute('title', '阅读辅助');
    pane.appendChild(frame);

    // 左边缘拖拽调宽。
    //
    //  修过的 bug：面板会"跟着鼠标移动自己变大"——
    //  根因是三个毛病叠在一起：
    //    ① 用了 mousedown，却配 pointermove / pointerup（事件族不一致）
    //    ② mousedown 事件没有 pointerId，setPointerCapture 必然失败
    //    ③ 于是鼠标划过 iframe（iframe 会吞掉指针事件）时 pointerup 不触发，
    //        dragging 一直是 true，此后鼠标一动面板就跟着变宽
    //  关键修法：补 pointercancel / lostpointercapture ——
    //  "指针被别的东西接管"正是这次的情形，pointercancel 就是为它设计的。
    const grip = document.createElement('div');
    grip.className = 'rf-grip';
    let dragging = false;

    function endDrag() {
      if (!dragging) return;
      dragging = false;
      try { document.body.style.userSelect = ''; } catch (e) { void e; }
    }
    function onMove(e) {
      if (!dragging) return;
      const w = Math.max(320, Math.min(window.innerWidth - 40, window.innerWidth - e.clientX));
      pane.style.width = w + 'px';
    }

    grip.addEventListener('pointerdown', (e) => {
      dragging = true;
      e.preventDefault();
      try { document.body.style.userSelect = 'none'; } catch (err) { void err; }
      // 指针捕获成功后，后续事件都由 grip 收到（即使划过 iframe）
      try { grip.setPointerCapture(e.pointerId); } catch (err) { void err; }
    });
    grip.addEventListener('pointermove', onMove);
    grip.addEventListener('pointerup', endDrag);
    // 这三条是兜底：指针被别的东西接管 / 窗口失焦时也要结束拖拽
    grip.addEventListener('pointercancel', endDrag);
    grip.addEventListener('lostpointercapture', endDrag);
    window.addEventListener('pointerup', endDrag);
    window.addEventListener('pointercancel', endDrag);
    window.addEventListener('blur', endDrag);
    pane.appendChild(grip);

    sh.appendChild(st);
    sh.appendChild(pane);
    document.documentElement.appendChild(host);
  }

  function startOverlay() {
    buildOverlay();
    return { ok: true, src: 'reader_flow.html' };
  }

  function removeOverlay() {
    if (host) {
      host.remove();
      host = null;
      frame = null;
    }
    clearMarks();
  }

  function ensurePageStyle() {
    if (document.getElementById('rf-page-style')) return;
    const st = document.createElement('style');
    st.id = 'rf-page-style';
    st.textContent =
      // .rf-sent 只是把文字包起来，必须【不改变任何排版】：
      //   显式声明 display:inline 且不加 padding/margin，
      //   否则会导致换行位置或行高变化，页面看起来"被改过"。
      //   （宿主页面的 CSS 可能有 p span{...} 这类规则，用 all:unset 风险太大，
      //     所以只针对我们自己的类做最小声明。）
      '.rf-sent{display:inline;background:transparent;}' +
      // 整段回退高亮 + 句子级高亮共用同一个类
      '.rf-cur{background:rgba(91,141,239,.26)!important;' +
      'box-shadow:inset 3px 0 0 0 #5b8def!important;border-radius:3px!important;' +
      'transition:background .15s;}';
    (document.head || document.documentElement).appendChild(st);

    // 校验样式真的生效了。
    //  有些站点（尤其大厂的内容站）有严格 CSP，会拦掉注入的 <style>。
    //  那种情况下：span 都在、类名都加对了、DOM 检查一切正常，
    //  但视觉上完全没有高亮 —— 症状和"根本没包裹"一模一样，必须能区分。
    setTimeout(() => {
      try {
        const probe = document.createElement('span');
        probe.className = 'rf-sent';
        probe.style.cssText = 'position:absolute;left:-9999px;top:-9999px;';
        document.documentElement.appendChild(probe);
        const cs = getComputedStyle(probe);
        const inlineOK = cs.display === 'inline';
        probe.remove();
        if (!inlineOK) {
          console.warn('[阅读辅助/样式] 注入的样式【没有生效】（display=' + cs.display +
                       '）。这个站点的 CSP 可能禁止了内联样式 —— ' +
                       '句子节点都在，但看不到高亮。');
        } else {
          console.log('[阅读辅助/样式] 页面样式注入正常');
        }
      } catch (e) {
        console.warn('[阅读辅助/样式] 样式生效性检查失败：', e);
      }
    }, 0);
  }
  // =========================================================================
  //  消息接口
  // =========================================================================
  chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
    if (!msg || !msg.type) return;

    // 让 background 能判断"本脚本是否已经在这个页面里"，
    //  避免无谓的重复注入（重复注入会清掉已包裹的句子节点）。
    if (msg.type === 'ping') {
      sendResponse({ ok: true, injected: true, spans: sentSpans.length });
      return true;
    }

    if (msg.type === 'extractArticle') {
      try {
        const r = extract();
        if (r.ok) {
          ensurePageStyle();
          try {
        buildMarks(r.paras);
        console.log('[阅读辅助/包裹] 段落 ' + r.paras.length +
                    ' 个，成功包裹句子节点 ' + sentSpans.length + ' 个');
        if (!sentSpans.length) {
          console.warn('[阅读辅助/包裹] 一个句子节点都没包上 —— ' +
                       '原文高亮会全部失效。多半是段落元素没定位到。');
        }
      } catch (e) {
        console.warn('[阅读辅助/包裹] buildMarks 抛异常，高亮会失效：', e);
      }
        }
        sendResponse(r);
      } catch (e) {
        sendResponse({ ok: false, error: (e && e.message) || String(e) });
      }
      return true;
    }

    if (msg.type === 'highlight') {
      ensurePageStyle();
      // ------------------------------------------------------------------
      //  自愈：句子节点为空就自己重建一次。
      //
      //  为什么需要：background 每次发消息前都会重新注入 content.js。
      //  扩展重载 / 页面刷新后隔离世界是全新的，重入守卫失效、脚本整体重跑，
      //  sentSpans 被重新初始化成空数组，但这一轮不会再收到 extractArticle，
      //  于是 buildMarks 不会跑 —— 表现就是"原文高亮突然全没了"。
      //  与其去堵住每一种状态丢失的原因，不如让高亮自己能恢复。
      // ------------------------------------------------------------------
      if (!sentSpans.length) {
        console.log('[阅读辅助/高亮] 句子节点为空，先自动重建一次');
        try {
          const r = extract();
          if (r.ok) {
            buildMarks(r.paras);
            console.log('[阅读辅助/高亮] 重建完成，句子节点 ' + sentSpans.length + ' 个');
          } else {
            console.warn('[阅读辅助/高亮] 重建时提取正文失败：', r.error);
          }
        } catch (e) {
          console.warn('[阅读辅助/高亮] 自动重建失败：', e);
        }
      }
      try {
        // 只认句子文本，不认编号 —— 见 highlight() 上面的说明
        const hit = highlight(msg.text);
        sendResponse({ ok: true, hit });
      } catch (e) {
        sendResponse({ ok: false, error: String(e) });
      }
      return true;
    }

    if (msg.type === 'clearHighlight') {
      clearMarks();
      sendResponse({ ok: true });
      return true;
    }

    if (msg.type === 'toggleOverlay') {
      try {
        if (host) { removeOverlay(); sendResponse({ ok: true, shown: false }); }
        else {
          ensurePageStyle();
          const r = startOverlay();
          sendResponse(Object.assign({ shown: true }, r));
        }
      } catch (e) {
        sendResponse({ ok: false, error: (e && e.message) || String(e) });
      }
      return true;
    }

    if (msg.type === 'hlDebug') {
      sendResponse({ ok: true, debug: lastHlDebug });
      return true;
    }

    if (msg.type === 'closeOverlay') {
      // 幂等的"关"（不用 toggleOverlay，否则已经关了再点会又开出来）
      try {
        if (host) removeOverlay();
        sendResponse({ ok: true, shown: false });
      } catch (e) {
        sendResponse({ ok: false, error: (e && e.message) || String(e) });
      }
      return true;
    }

    if (msg.type === 'isOverlayOpen') {
      sendResponse({ ok: true, shown: !!host });
      return true;
    }
  });

  console.log('[阅读辅助/content] 已注入', location.href);
})();
