"use strict";
/* ===========================================================================
 *  自适应阅读辅助 · 原型
 *
 *  架构（高内聚低耦合）：五个模块，各自闭环，彼此只通过数据交互。
 *  想换任何一个部件，只改对应那一个模块，其余不动。
 *
 *    ① TextSource  文本 → 句子数组            （未来：PDF / EPUB / 网页正文）
 *    ② Reader      高亮推进 + 键位             （未来：滚动 / RSVP / 分页）
 *    ③ Trigger     判断"该不该讲解"            （未来：接停留时长推断层）
 *    ④ Explainer   建 prompt + 调 LLM + 缓存   （未来：BYOK / 本地模型 / 多技能）
 *    ⑤ SidePanel   显示讲解卡片                （未来：不同呈现形式）
 *
 *  数据流：TextSource → Reader →(事件)→ Trigger → Explainer → SidePanel
 * =========================================================================== */

/* ---------------------------------------------------------------------------
 *  ① TextSource —— 只负责"把文本变成句子数组"
 *  接口：TextSource.load(text) -> { paras: [{id}], sents: [{idx, text, para}] }
 * ------------------------------------------------------------------------- */
  // ==================================================================
  //  PDF 取正文
  //
  //  为什么需要它：浏览器内置 PDF 阅读器把页面渲染在【它自己的文档】里，
  //  内容脚本读不到里面的文字（document.body 里只有阅读器的工具栏）。
  //  所以只能自己把 PDF 文件抓下来解析。而学术阅读的主要格式就是 PDF。
  //
  //  用 pdf.js（随扩展打包在 vendor/pdf/，离线可用）。
  //
  //  四个必须处理的坑（都是实测踩出来的）：
  //    ① 【双栏排版】pdf.js 给的文字块顺序是内容流顺序，不是视觉顺序。
  //       直接拼接会让左右栏交错，句子完全读不通。
  //       -> 扫描横向的文字覆盖，找中段最宽的空白带切开。
  //
  //    ② 【非正文干扰】标题、作者、单位、邮箱、DOI、版权声明、
  //       以及下载水印（"Downloaded from ... by guest on ..."）都会被提取出来，
  //       用户前二十句全是这些垃圾。
  //       -> 按【字号】+【是否旋转】过滤：
  //          正文有稳定的主字号；标题更大、脚注更小；
  //          水印是斜排的（transform 里有非零的 b/c），字号也偏小。
  //          这两个判据与出版社无关，比按关键词黑名单可靠。
  //
  //    ③ 【同一行被拆开】斜体数学（如 (k = 28, r = −.21)）里的字符
  //       基线常有偏移，用"字高 × 0.55"当同一行的容差会把它们拆散，
  //       再按 y 排序就变成了乱序（实测提取成 "(k!428,r!. 21)"）。
  //       -> 容差改用【本页主字号】的比例，比按单个字符的高度稳。
  //
  //    ④ 【段落边界】PDF 没有段落概念，只有一行行文字块。
  //       -> 用行间距中位数判断：明显大于常规行距的就是新段落。
  //
  //  说明：浏览器内置阅读器里的原文【无法高亮】—— 内容脚本改不了
  //  阅读器自己文档里的节点。所以 PDF 模式下靠右侧面板逐句显示。
  // ==================================================================
  const PdfSource = (() => {
    let lib = null;
    let loading = null;

    async function loadLib() {
      if (lib) return lib;
      if (loading) return loading;
      loading = (async () => {
        // 这里【不能】调 hasExt() —— 它定义在 App 的 IIFE 里，本模块够不着。
        //  之前这么写导致 "ReferenceError: hasExt is not defined"，
        //  又被外层 catch 吞成"PDF 解析失败"，看不出真正原因。
        //  本模块保持自包含。
        if (typeof chrome === 'undefined' || !chrome.runtime ||
            typeof chrome.runtime.getURL !== 'function') {
          throw new Error('PDF 解析需要扩展环境（当前页面拿不到扩展 API）');
        }
        const base = chrome.runtime.getURL('vendor/pdf/');
        const mod = await import(base + 'pdf.mjs');
        mod.GlobalWorkerOptions.workerSrc = base + 'pdf.worker.mjs';
        lib = mod;
        return mod;
      })();
      try { return await loading; }
      catch (e) { loading = null; throw e; }
    }

    // ---- 字号与旋转：用来区分正文 / 标题 / 页眉页脚 / 水印 ----
    function sizeOf(it) {
      // transform = [a, b, c, d, e, f]；未旋转时 d 就是字号的纵向缩放
      const d = Math.abs(it.transform[3]);
      const a = Math.abs(it.transform[0]);
      return d || a || it.height || 0;
    }
    function rotOf(it) {
      // 未旋转的文字 b、c 都接近 0；斜排水印会明显非零
      return Math.abs(it.transform[1]) + Math.abs(it.transform[2]);
    }

    // 本页「主字号」：按字符数加权，避免标题的大字把结果带偏
    function dominantSize(items) {
      const hist = new Map();
      items.forEach(it => {
        const s = Math.round(sizeOf(it) * 2) / 2;   // 半磅一档
        if (s <= 0) return;
        hist.set(s, (hist.get(s) || 0) + (it.str ? it.str.length : 1));
      });
      let best = 0, bestN = -1;
      hist.forEach((n, s) => { if (n > bestN) { bestN = n; best = s; } });
      return best;
    }

    // 过滤掉非正文：旋转的（水印）、字号明显偏离主字号的（标题/脚注/页眉）
    function filterBody(items) {
      const usable = items.filter(it => it && typeof it.str === 'string' && it.str.trim());
      if (usable.length < 20) return usable;
      const dom = dominantSize(usable);
      if (!(dom > 0)) return usable;

      return usable.filter(it => {
        const s = sizeOf(it);
        // ① 旋转的一律不要（水印几乎都是斜排的）
        if (rotOf(it) > s * 0.08) return false;
        // ② 字号必须在主字号的 0.86 ~ 1.14 倍之间
        //    正文有稳定的主字号；标题更大、脚注与页眉更小
        if (s > 0 && (s < dom * 0.86 || s > dom * 1.14)) return false;
        return true;
      });
    }

    // 兜底的关键词过滤：字号判据漏掉的少量非正文
    //  只放"几乎不可能是正文"的模式，宁可漏杀不要错杀
    const JUNK = [
      /^https?:\/\/\S+$/i,
      /^doi:\s*10\./i,
      /^https?:\/\/doi\.org\//i,
      /^downloaded from\b/i,
      /^by guest on\b/i,
      /^advance access publication\b/i,
      /^©/,
      /^all rights reserved\b/i,
      /^corresponding author\b/i,
      /^[\w.+-]+@[\w.-]+\.\w+$/,
      /^keywords?:/i,
      /^\d{4}\s+\w+\s+\d{1,2}\b/,        // 水印里的日期行，如 "2026 Psychological…" 不匹配
    ];
    function isJunkLine(t) {
      const s = t.trim();
      if (!s) return true;
      if (s.length <= 2) return true;
      // 水印那种 "academic. oup. com/xxx" 形式
      if (/^[\w-]+(\s*\.\s*[\w-]+)+\s*(com|org|net|edu|cn)\b/i.test(s)) return true;
      for (let i = 0; i < JUNK.length; i++) if (JUNK[i].test(s)) return true;
      // 邮箱/网址占比高的行
      if (s.length > 20 && /@|https?:\/\//.test(s)) return true;
      return false;
    }

    // 把一页的文字块合并成"行"。
    //  容差用【主字号】而不是单个字符的高度 —— 关键修正：
    //  斜体数学里的字符基线常有偏移，用字高当容差会把同一行拆开，
    //  再按 y 排序就变成乱序（实测 "(k = 28, r = −.21)" 提取成 "(k!428,r!. 21)"）。
    function toLines(items) {
      const dom = dominantSize(items);
      const tol = (dom > 0 ? dom : 10) * 0.55;   // 同一行的纵向容差

      const sorted = items.slice().sort((a, b) =>
        (b.transform[5] - a.transform[5]) || (a.transform[4] - b.transform[4]));

      const rows = [];
      let cur = null;
      sorted.forEach(it => {
        const y = it.transform[5];
        if (!cur || Math.abs(cur.y - y) > tol) {
          cur = { y: y, items: [it] };
          rows.push(cur);
        } else {
          cur.items.push(it);
          // 行基准取平均，避免第一个字符的基线偏移把整行带偏
          cur.y = (cur.y * (cur.items.length - 1) + y) / cur.items.length;
        }
      });
      rows.forEach(r => {
        r.items.sort((a, b) => a.transform[4] - b.transform[4]);
        r.text = joinItems(r.items);
        // 记录左右边界与字号 —— 判断段落要用（首行缩进 / 有没有写满）
        let x0 = Infinity, x1 = -Infinity, sz = 0;
        r.items.forEach(it => {
          const x = it.transform[4];
          const w = it.width || 0;
          if (x < x0) x0 = x;
          if (x + w > x1) x1 = x + w;
          if (!sz) sz = Math.abs(it.transform[3]) || it.height || 0;
        });
        r.x0 = isFinite(x0) ? x0 : 0;
        r.x1 = isFinite(x1) ? x1 : 0;
        r.size = sz || 10;
        // 平均字宽：用行宽除字数估算（中英文混排也能过得去）
        r.charW = r.text.length ? ((r.x1 - r.x0) / r.text.length) : (r.size * 0.5);
      });
      return rows.filter(r => r.text.trim());
    }

    // 拼接一条行内相邻的文字块。中英混排区别对待：
    //  两块都是拉丁字母/数字 -> 补空格；否则直接连（中文本来不空格）
    function joinItems(items) {
      let out = '';
      let prev = null;
      items.forEach(it => {
        const t = it.str;
        if (!t) return;
        if (out && prev !== null) {
          const a = out[out.length - 1];
          const b = t[0];
          const gap = it.transform[4] - (prev.transform[4] + (prev.width || 0));
          const needSpace = /[A-Za-z0-9]/.test(a) && /[A-Za-z0-9]/.test(b) && gap > 0.5;
          if (needSpace && !/\s$/.test(out)) out += ' ';
        }
        out += t;
        prev = it;
      });
      return out.replace(/\s+/g, ' ').trim();
    }

    // 检测分栏：找页面中部最宽的一条"没有文字"的竖直空白带
    function splitColumns(items) {
      const spans = items.map(it => [it.transform[4], it.transform[4] + (it.width || 0)])
                         .filter(s => s[1] > s[0]);
      if (spans.length < 20) return [items];

      let minX = Infinity, maxX = -Infinity;
      spans.forEach(s => { if (s[0] < minX) minX = s[0]; if (s[1] > maxX) maxX = s[1]; });
      const W = maxX - minX;
      if (!(W > 0)) return [items];

      const N = 120;
      const cover = new Array(N).fill(0);
      spans.forEach(s => {
        const a = Math.max(0, Math.floor((s[0] - minX) / W * N));
        const b = Math.min(N, Math.ceil((s[1] - minX) / W * N));
        for (let k = a; k < b; k++) cover[k]++;
      });

      let run = -1, bestA = -1, bestB = -1, bestW = 0;
      for (let k = Math.floor(N * 0.32); k <= Math.ceil(N * 0.68); k++) {
        if (cover[k] === 0) {
          if (run < 0) run = k;
        } else if (run >= 0) {
          if (k - run > bestW) { bestW = k - run; bestA = run; bestB = k; }
          run = -1;
        }
      }
      if (run >= 0 && N - run > bestW) { bestW = N - run; bestA = run; bestB = N; }

      if (bestW < N * 0.03) return [items];
      const cut = minX + ((bestA + bestB) / 2) / N * W;
      const left = items.filter(it => it.transform[4] < cut);
      const right = items.filter(it => it.transform[4] >= cut);
      if (left.length < 15 || right.length < 15) return [items];
      return [left, right];
    }

    // 一组行 -> 段落（按行距突变切段）
    // 一组行 -> 段落。
    //
    //  早先只用一条依据：行距明显大于中位数。
    //  但很多 PDF 行距均匀，段落靠【首行缩进】或【上一行没写满】区分 ——
    //  结果整页正文被合成一大段，面板里看起来就是一大坨（用户实测反馈）。
    //
    //  现在三条依据，任一成立就断段：
    //    ① 行距明显大于常规
    //    ② 本行有首行缩进（左边界明显比正文基准靠右）
    //    ③ 上一行明显没写满（右边界离正文右缘还差得多）
    //  ②③ 是排版学里判断段落的常规手段，比单看行距稳得多。
    function linesToParas(lines) {
      if (!lines.length) return [];

      const gaps = [];
      for (let i = 1; i < lines.length; i++) {
        const g = lines[i - 1].y - lines[i].y;
        if (g > 0) gaps.push(g);
      }
      gaps.sort((a, b) => a - b);
      const med = gaps.length ? gaps[Math.floor(gaps.length / 2)] : 0;
      const gapThresh = med > 0 ? med * 1.35 : Infinity;

      // 正文左右基准：左边界取众数（多数行从同一位置起），右边界取最大值
      const lefts = lines.map(l => Math.round(l.x0 || 0));
      const cnt = new Map();
      lefts.forEach(v => cnt.set(v, (cnt.get(v) || 0) + 1));
      let bodyLeft = lefts[0], best = -1;
      cnt.forEach((c, v) => { if (c > best) { best = c; bodyLeft = v; } });
      // 右缘只由【没有缩进的行】决定。
      //  用 max(x1) 会被"缩进的首行"拉偏：那种行 x1 = 左边界+缩进+行宽，偏大，
      //  于是正文行相对它"显得没写满"，被误判成段落结尾（实测把一段拆成四段）。
      const bodyLines = lines.filter(l => Math.abs(Math.round(l.x0 || 0) - bodyLeft) <= 1);
      const bodyRight = bodyLines.length
        ? Math.max.apply(null, bodyLines.map(l => l.x1 || 0))
        : Math.max.apply(null, lines.map(l => l.x1 || 0));

      const paras = [];
      let buf = [lines[0].text];
      for (let i = 1; i < lines.length; i++) {
        const cur = lines[i], prev = lines[i - 1];
        const g = prev.y - cur.y;
        const cw = cur.charW || cur.size * 0.5 || 5;

        const bigGap = med > 0 && (g > gapThresh || g < 0);
        const indented = ((cur.x0 || 0) - bodyLeft) > cw * 1.2;       // 首行缩进
        // "上一行没写满"必须【配合句末标点】才算段落结尾。
        //  单看"没写满"在 ragged-right 排版里到处都是 ——
        //  每一行都可能没写满，于是到处断段，切出半个句子。
        //  （用户实测："on a Saturday" / "morning are learning it…" 被切成两段）
        const prevEndsSentence = /[.。!！?？]["'\u201d\u2019)\]]*\s*$/.test(prev.text.trim());
        const prevShort = prevEndsSentence && (bodyRight - (prev.x1 || 0)) > cw * 2.0;

        if (buf.length && (bigGap || indented || prevShort)) {
          paras.push(buf.join(' '));
          buf = [cur.text];
        } else {
          buf.push(cur.text);
        }
      }
      paras.push(buf.join(' '));

      // 兜底：段落必须在句末结束。
      //  判据再怎么调都可能出偏差，但"一个段落不该以半个句子结尾"是硬要求
      //  （用户原话："至少一段的结尾是一句话吧"）。
      //  凡是没以句末标点结尾的段落，与下一段合并。
      //  最后一段若是被页面截断，就保留原样。
      const SENT_END = /[.。!！?？]["'\u201d\u2019)\]]*$/;
      const merged = [];
      let acc = '';
      paras.forEach(p => {
        const t = p.replace(/\s+/g, ' ').trim();
        if (!t) return;
        acc = acc ? (acc + ' ' + t) : t;
        if (SENT_END.test(acc)) {
          merged.push(acc);
          acc = '';
          return;
        }
        // 安全阀：累积太长还没见到句末标点，就在【最后一个句末标点】处切开。
        //  防止"某份 PDF 提取出来没有句末标点"时把整篇合成一大段
        //  （测试用例第一版就是这么炸的：所有行都没句号 -> 全并成一段）。
        if (acc.length > 400) {
          const m2 = acc.match(/[\s\S]*[.。!！?？]/);
          if (m2 && m2[0].length > 40) {
            // 在最后一个句末标点处切开
            merged.push(m2[0].trim());
            acc = acc.slice(m2[0].length).trim();
          } else if (!m2 && acc.length > 400) {
            // 整段一个句末标点都没有（扫描件、公式页）——
            //  没地方"切在句末"，只能按长度硬切。
            //
            //  注意：这里必须真的切，不能 merged.push(acc) 了事。
            //  第一版就是 push(acc) —— 而这一支通常发生在
            //  "paras 只有一整块、acc 已经等于全部内容"的时候，
            //  于是等于原样推出去，一段都没切开（测试当场抓到）。
            let cut = acc.lastIndexOf(' ', 400);
            if (cut < 200) cut = 400;          // 中文没空格，直接按字数切
            merged.push(acc.slice(0, cut).trim());
            acc = acc.slice(cut).trim();
          }
        }
      });
      if (acc) merged.push(acc);

      return merged.filter(t => t.length > 1 && !isJunkLine(t));
    }

    // ------------------------------------------------------------------
    //  字体映射表坏掉的保守补救
    //
    //  有些出版社的 PDF 把 "=" 映射成了 "¼"（U+00BC）：
    //      (k = 6, r = −.03)  提取成  (k¼6,r¼−. 03)
    //  原因在字体的 ToUnicode 表本身，**信息不在文件里**，任何解析器都改不了
    //  （字形渲染是对的，但映射表说它读作 ¼）。
    //
    //  ¼ ½ ¾ 在学术正文里极少见（真要用也写作 1/4），
    //  所以出现在"两边是字母/数字/运算符"的位置时基本可以断定是 "="。
    //  只在 PDF 路径上做 —— 网页正文里合法的 ¼ 不该被动。
    // ------------------------------------------------------------------
    let warnedEncoding = false;
    function repairMisencoded(t) {
      if (!/[\u00bc\u00bd\u00be]/.test(t)) return t;
      if (!warnedEncoding) {
        warnedEncoding = true;
        console.warn('[reader] 这个 PDF 的字体映射表有问题（= 被映射成 ¼），' +
                     '已按上下文做保守替换。若发现正文里本来该是 ¼ 的地方被改成 =，' +
                     '请反馈。');
      }
      return t.replace(/([A-Za-z0-9)\]])\s*[\u00bc\u00bd\u00be]\s*(?=[0-9A-Za-z\u2212+\-(])/g,
                       '$1 = ')
              .replace(/\s{2,}/g, ' ');
    }

    function pageToParas(items) {
      const body = filterBody(items);
      const out = [];
      splitColumns(body).forEach(col => {
        linesToParas(toLines(col)).forEach(p => out.push(repairMisencoded(p)));
      });
      return out;
    }

    // 从整页里取"最像标题"的一行：字号最大的那批里最靠上的一条
    function guessTitle(items) {
      if (!items.length) return '';
      const dom = dominantSize(items);
      const big = items.filter(it => sizeOf(it) > dom * 1.25 && it.str && it.str.trim());
      if (!big.length) return '';
      big.sort((a, b) => (b.transform[5] - a.transform[5]) ||
                         (a.transform[4] - b.transform[4]));
      // 同一行合并
      const topY = big[0].transform[5];
      const sameRow = big.filter(it => Math.abs(it.transform[5] - topY) < sizeOf(big[0]) * 0.6);
      sameRow.sort((a, b) => a.transform[4] - b.transform[4]);
      const t = joinItems(sameRow);
      return t.length >= 8 && t.length <= 300 ? t : '';
    }

    async function fromUrl(url, onProgress) {
      const mod = await loadLib();
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) throw new Error('下载 PDF 失败：HTTP ' + res.status);
      const buf = await res.arrayBuffer();
      const head = new TextDecoder().decode(buf.slice(0, 5));
      if (head !== '%PDF-') {
        throw new Error('这个地址返回的不是 PDF（可能是登录页或错误页）');
      }
      const doc = await mod.getDocument({ data: buf }).promise;
      let title = '';
      try {
        const meta = await doc.getMetadata();
        title = (meta && meta.info && meta.info.Title) || '';
      } catch (e) { void e; }

      const paras = [];
      let firstPageItems = null;
      let paraIdx = 0;
      for (let p = 1; p <= doc.numPages; p++) {
        if (onProgress) onProgress(p, doc.numPages);
        const page = await doc.getPage(p);
        const tc = await page.getTextContent();
        if (p === 1) firstPageItems = tc.items;
        // 必须给每个段落一个 idx —— 面板是按 para 分组显示的。
        //  早先这里只 push { block, text }，没有 idx，于是 fromParas 里
        //  所有段落都拿到 gid = -1，全部归到一组，看起来"完全没有分段"。
        pageToParas(tc.items).forEach(t => {
          paras.push({ block: 'p', text: t, idx: paraIdx++ });
        });
        page.cleanup();
      }
      console.log('[reader] PDF 解析：' + doc.numPages + ' 页，' +
                  paras.length + ' 个段落');
      // 元数据没有标题就用首页最大的字当标题
      if (!title && firstPageItems) title = guessTitle(firstPageItems);
      try { doc.destroy(); } catch (e) { void e; }
      return { title: title, paras: paras };
    }

    return { fromUrl: fromUrl };
  })();

const TextSource = (() => {
  // 中文句末标点 + 英文句末标点；保留标点在句内。
  // 英文要避开常见缩写（Mr. Dr. etc. e.g. i.e. vs. Fig. 等），否则会被切开。
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

  function load(text) {
    const blocks = text.replace(/\r/g, '')
                       .split(/\n\s*\n/)
                       .map(s => s.replace(/\s*\n\s*/g, ' ').trim())
                       .filter(Boolean);
    const sents = [];
    let idx = 0;
    blocks.forEach((b, pi) => {
      splitSentences(b).forEach(s => {
        sents.push({ idx: idx++, text: s, para: pi });
      });
    });
    return { paras: blocks.map((_, i) => ({ id: i })), sents };
  }

  // 从 HTML 里提取可读正文。
  //  做法：去掉 script/style/nav/header/footer/aside 等非正文元素，
  //  优先取 <article> / <main>，否则退回整个 body，再按块级元素切成段落。
  //  这是"够用"的提取，不追求 Readability 那种完整度 ——
  //  抓不准时用户还能手动粘贴。
  function fromHTML(html, baseUrl) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    if (baseUrl) {
      // 把相对链接补全，避免解析器把 <base> 之外的东西搞乱（这里只做规范化）
      try {
        const b = doc.createElement('base');
        b.href = baseUrl;
        doc.head.appendChild(b);
      } catch (e) {
        // 容错但留痕：空 catch 会把问题变成沉默（本项目踩过一次，
        // 见状态栏那段 —— 用错变量名抛 ReferenceError 被吞掉，界面上什么都不显示）
        console.warn("[reader] 设置 base href 失败（不影响主流程）:", e && e.message);
      }
    }
    ['script', 'style', 'noscript', 'nav', 'header', 'footer', 'aside',
     'form', 'iframe', 'svg', 'button', 'select', 'template'].forEach(tag => {
      doc.querySelectorAll(tag).forEach(e => e.remove());
    });
    // 去掉明显的导航/侧栏容器
    doc.querySelectorAll('[role="navigation"],[role="banner"],[role="contentinfo"],' +
                         '[aria-hidden="true"],.nav,.navbar,.sidebar,.menu,.footer,' +
                         '.header,.comment,.comments,.ad,.ads,.advertisement')
       .forEach(e => e.remove());

    const root = doc.querySelector('article') || doc.querySelector('main') ||
                 doc.querySelector('[role="main"]') || doc.body;
    if (!root) return '';

    const title = (doc.querySelector('title') || {}).textContent || '';
    const blocks = [];
    root.querySelectorAll('h1,h2,h3,h4,h5,h6,p,li,blockquote,pre,td,dd')
        .forEach(el => {
          const t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          // 过滤过短的碎片（导航项、按钮文字、行号等）
          if (t.length >= 12) blocks.push(t);
        });

    if (!blocks.length) {
      const t = (root.innerText || root.textContent || '').replace(/[ \t]+/g, ' ')
                    .replace(/\n{3,}/g, '\n\n').trim();
      return (title ? title + '\n\n' : '') + t;
    }
    return (title ? title + '\n\n' : '') + blocks.join('\n\n');
  }

  // 从【已成段的记录】构造句子列表（扩展模式用）。
  //  与 load() 的区别：段落边界由调用方给（网页的 <p>/<li>/<h2> 等），
  //  不再靠空行猜。这样切句后的 para 归属与页面结构一一对应，
  //  渲染时就能原样还原段落。
  function fromParas(paras, title) {
    const sents = [];
    let idx = 0;

    // ------------------------------------------------------------------
    //  标题：给 para = -1
    //
    //  踩过的坑：早先给标题分配了 para 0，于是正文第一段的段落号变成 1，
    //  而它在原文里的标记值是 0 —— 段落号整体错开 1，原文高亮永远落后一段。
    //  日志里能直接看出来：
    //      段#1  原文该段: Modern cameras are able...
    //            要高亮句: Computer vision is a rapidly growing field...（正是段#0 的原文）
    //  标题本来也不需要在原文上高亮，所以用 -1 标记"不参与原文高亮"。
    // ------------------------------------------------------------------
    if (title && title.trim()) {
      sents.push({ idx: idx++, text: title.trim(), para: -1 });
    }

    // 段落号 = 【原文里的标记值 p.idx】，而不是过滤后数组的下标。
    //  过滤会把导航/短块/重复块剔掉，所以数组下标与原文标记值不一致；
    //  只有用标记值才能在原文里准确定位到同一个元素。
    paras.forEach((p, pi) => {
      const txt = (p.text || '').replace(/\s+/g, ' ').trim();
      if (!txt) return;
      const parts = splitSentences(txt);
      if (!parts.length) return;
      // 段落号优先用【原文标记值】（网页版靠它在原文里定位到对应元素）；
      //  没有标记值时退回【数组下标】，而不是一律 -1。
      //  实测踩到：PDF 那条路的段落没有 idx，全部拿到 -1，
      //  面板按 para 分组 -> 全归一组 -> 看起来完全没有分段。
      //  para 只用于【面板分组显示】；原文高亮是按句子文本匹配的，不受影响。
      const gid = (p.idx === undefined || p.idx === null) ? pi : p.idx;
      parts.forEach(x => sents.push({ idx: idx++, text: x, para: gid }));
    });

    return { paras: paras.map((_, i) => ({ id: i })), sents };
  }

  // ------------------------------------------------------------------
  //  阅读单位数 —— 这是"这句该给多少时间"的基础，必须按语言算对。
  //
  //  踩过的坑（现场发现）：
  //    ① 直接用 text.length 把【空格】也算成了字数；
  //    ② 英文按【字母数】算 —— "architectures" 有 13 个字母，
  //       被当成 13 个字，而它只是一个词，读起来远快于 13 个中文字。
  //    于是英文长句被给了离谱的时间。
  //
  //  正确做法：按语言分别计数
  //    中文 -> 字数（CJK 字符）
  //    英文 -> 词数（字母/数字开头的连续串，自动排除空格与标点）
  //  两者作为同一单位相加 —— 因为阅读速度上"1 个中文字 ≈ 1 个英文词"，
  //  典型值都是约 5 单位/秒（中文 300 字/分，英文 300 词/分）。
  // ------------------------------------------------------------------
  const CJK = /[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]/g;
  const LATIN_WORD = /[A-Za-z0-9][A-Za-z0-9'’\-]*/g;

  function units(text) {
    const t = String(text || '');
    const cjk = (t.match(CJK) || []).length;
    // 先把 CJK 挖掉，剩下按"词"数 —— 这样中英混排也不会重复计数
    const rest = t.replace(CJK, ' ');
    const words = (rest.match(LATIN_WORD) || []).filter(w => /[A-Za-z]/.test(w)).length;
    return { cjk, words, units: cjk + words };
  }

  return { load, splitSentences, fromHTML, fromParas, units };
})();

/* ---------------------------------------------------------------------------
 *  ② Reader —— 只负责"高亮推进 + 键位"
 *  接口：Reader.load(sents) / start() / pause() / toggle() / next() / prev()
 *        Reader.onAdvance = (sent, reason) => {}     reason: 'auto' | 'manual'
 *  不依赖 Trigger / Explainer / SidePanel —— 它不知道讲解是什么。
 * ------------------------------------------------------------------------- */
const Reader = (() => {
  let sents = [], cur = -1, playing = false;
  let perSent = 3.2, acc = 0, last = 0;
  let raf = 0;

  // ------------------------------------------------------------------
  //  自适应推进速度
  //
  //  设计思路（来自现场反馈）：
  //    固定间隔有个根本问题 —— "每句 3.2 秒"对长句太短、对短句太长，
  //    而且这样测出来的"停留时长"恒等于 3.2 秒，没有任何信息量，
  //    推断层拿到的是废数据。
  //
  //  改成：本句给的时间 = 本句字数 × 每字秒数 × 余量
  //    长句自然得到更多时间；"每字秒数"就是用户的阅读速度。
  //
  //  速度从哪来 —— 用户的【手动纠正】就是真值信号：
  //    · 按 ← 退回上一句  ->  说明上一句给的时间不够  ->  调慢
  //    · 计时未到就按 →  ->  说明给多了            ->  调快
  //    这样不需要直接测"你看了多久"，也能逼近你的真实速度。
  //
  //  同时：退回某句本身就是"这句难"的证据（设计文档里的"回看次数"），
  //  所以这个方案顺带让推断层重新有了有效信号。
  // ------------------------------------------------------------------
  const PACE = {
    cps: 5.0,          // 当前的"单位/秒"（会随纠正自适应）
    MIN: 1.5,
    MAX: 20.0,
    MARGIN: 1.15,      // 余量：宁可稍宽松，因为退回比等待更烦
    MIN_SEC: 0.9,      // 单句下限，避免极短句一闪而过
    MAX_SEC: 25.0,     // 单句上限，避免超长句卡住
    ADAPT_DOWN: 0.90,  // 退回时：速度乘这个（变慢 = 每单位给更多时间）
    ADAPT_UP: 1.04,    // 跳过时：速度乘这个（变快）
    DEFAULT_CPS: 5.0,

    // ------------------------------------------------------------------
    //  按语言分别记住速度，并持久化。
    //
    //  现场要求："阅读速度一次测试结束后就直接保存，不用每次读的时候重测。"
    //  而且中英文阅读速度本来就不同（同一个人的中文和英文速度能差一倍），
    //  所以分三档记：zh（中文为主）/ en（英文为主）/ mix（中英混排）。
    //  载入文章时按文章的主要语言取对应的速度。
    // ------------------------------------------------------------------
    // 推进模式：'auto' 系统按句长推进；'manual' 用户自己按 → 翻句。
    //
    //  为什么要有手动模式（现场数据给的结论）：
    //    自动推进下，ratio = 实际停留/系统给的时间，而两者都由系统决定，
    //    实测难的句子 ratio 均值 1.089、顺的 1.066 —— 完全重合，没有区分力。
    //    而且用户面对难句的典型反应是【什么都不做】（79% 的难句没有任何操作），
    //    系统观察不到"不作为"。
    //    手动模式下由用户决定何时翻句，"卡住就停得久"才成为可观测的信号。
    mode: 'auto',
    lang: 'mix',
    byLang: { zh: null, en: null, mix: null },
    learnedFrom: '',    // 'saved' | 'learned' | 'default'，用于状态栏提示
  };

  const PACE_KEY = 'rf_pace_v1';

  function loadPace() {
    try {
      const raw = localStorage.getItem(PACE_KEY);
      if (!raw) return;
      const o = JSON.parse(raw);
      if (o && o.byLang) {
        ['zh', 'en', 'mix'].forEach(k => {
          const v = Number(o.byLang[k]);
          if (v > PACE.MIN && v < PACE.MAX) PACE.byLang[k] = v;
        });
      }
    } catch (e) { /* 忽略损坏的数据 */ }
  }

  // 最近一次真正写盘的时间，用于节流
  let lastPaceSave = 0;
  let pendingPaceSave = null;

  function savePace(force) {
    const now = Date.now();
    // 节流：2 秒内最多写一次。避免每句都写 localStorage（浪费且可能抖动）。
    //  但 force=true 时立刻写 —— 关闭面板/暂停阅读时必须落盘。
    if (!force && now - lastPaceSave < 2000) {
      if (pendingPaceSave) clearTimeout(pendingPaceSave);
      pendingPaceSave = setTimeout(() => { pendingPaceSave = null; savePace(true); }, 2100);
      return;
    }
    lastPaceSave = now;
    if (pendingPaceSave) { clearTimeout(pendingPaceSave); pendingPaceSave = null; }
    try {
      localStorage.setItem(PACE_KEY, JSON.stringify({
        byLang: PACE.byLang, cps: PACE.cps, lang: PACE.lang, at: now,
      }));
      window.__lastPaceSavedAt = now;      // 供界面显示"已保存"
    } catch (e) {
      console.warn('[reader] 速度保存失败（隐私模式或存储满，仅影响下次自动载入）:', e && e.message);
    }
  }

  // 判断一段文字的主要语言
  function langOf(text) {
    const u = TextSource.units(text);
    if (!u.words) return u.cjk ? 'zh' : 'mix';
    if (!u.cjk) return 'en';
    // 混排：哪一个占比高就算哪一类
    return (u.cjk >= u.words) ? 'zh' : 'en';
  }

  // 载入一批句子时：按主要语言套用记住的速度
  function applyPaceFor(list) {
    if (!list || !list.length) return;
    let cjk = 0, words = 0;
    list.forEach(s => {
      const u = TextSource.units(s.text);
      cjk += u.cjk; words += u.words;
    });
    PACE.lang = (!words) ? 'zh' : (!cjk) ? 'en' : (cjk >= words ? 'zh' : 'en');
    const saved = PACE.byLang[PACE.lang];
    if (saved) {
      PACE.cps = saved;
      PACE.learnedFrom = 'saved';
    } else {
      PACE.cps = PACE.DEFAULT_CPS;
      PACE.learnedFrom = 'default';
    }
    return PACE.lang;
  }

  // 速度变了就记到当前语言档里并持久化
  function notePace() {
    PACE.byLang[PACE.lang] = PACE.cps;
    if (PACE.learnedFrom === 'default') PACE.learnedFrom = 'learned';
    savePace();
  }

  loadPace();          // 模块初始化时就把上次记住的速度读进来

  // 单句的【额外时间】—— 用户退回过某句，说明那句给的时间不够。
  //
  //  为什么单独一张表、而不是调全局速度：
  //    全局速度 PACE.cps 是「我的阅读速度」，是个人属性、相对稳定；
  //    「这一句需要更多时间」是单句属性。
  //    把两者混在一起会出现：退几次之后整篇文章都被拖慢，
  //    而且这个被拖慢的速度还会被永久保存 —— 现场就是这个问题。
  //
  //  所以：退回只给【那一句】加时间，全局速度只从实际阅读速度观测里学。
  const extraSec = {};

  function advanceFor(i) {
    const s = sents[i];
    if (!s) return perSent;
    // 用【阅读单位】而不是字符数 —— 英文按词、中文按字，空格不计。
    const u = TextSource.units(s.text).units;
    const sec = u / PACE.cps * PACE.MARGIN + (extraSec[i] || 0);
    return Math.max(PACE.MIN_SEC, Math.min(PACE.MAX_SEC, sec));
  }

  // 每句的统计（停留时长 / 进入次数），供 Trigger 与导出使用
  const stats = {};

  function st(i) {
    if (!stats[i]) {
      stats[i] = { dwell: 0, visits: 0, lastEnter: 0, marks: 0,
                   asked: 0, longest: 0, prep: 0, backs: 0,
                   truth: null,      // 人工真值：1=确实难，0=没问题，null=未标注
                   pred: null,       // 离开这句时系统的判定（不留到未来信息）
                   predRatio: null };
    }
    return stats[i];
  }

  // 渲染：**保留原文的段落结构**，在每段内部把句子包成内联 <span>。
  //
  //  为什么不用"每句一个 div"：那样会把一段话拆成好几行，段落感和行文节奏全没了，
  //  用户看到的不再是"原文"，而是被重排过的列表。阅读辅助工具不应该改变
  //  文章的呈现结构 —— 它只应该在原文上叠加高亮。
  //
  //  实现要点：段内文字是连续的，所以按【句子长度累加】把每句 span 接起来，
  //  而不是给每句单独换行。句间不加任何空格或标点（标点已在句内）。
  function render() {
    const doc = document.getElementById('doc');
    doc.innerHTML = '';

    // 按段落分组（TextSource 已经给每句标了 para）
    const groups = new Map();
    sents.forEach((s, i) => {
      if (!groups.has(s.para)) groups.set(s.para, []);
      groups.get(s.para).push(i);
    });

    // 第一段若很短且不像正文句子，当作标题单独呈现（很多网页/文档的第一段是标题）
    const keys = [...groups.keys()].sort((a, b) => a - b);
    keys.forEach(pi => {
      const idxs = groups.get(pi);
      const el = document.createElement('p');
      const firstText = sents[idxs[0]].text;
      const totalLen = idxs.reduce((a, i) => a + sents[i].text.length, 0);
      if (pi === keys[0] && totalLen < 60 && idxs.length <= 2) {
        el.className = 'title';
      }
      idxs.forEach(i => {
        const sp = document.createElement('span');
        sp.className = 's';
        sp.dataset.i = i;
        sp.textContent = sents[i].text;
        sp.addEventListener('click', () => go(i, 'click'));
        el.appendChild(sp);
      });
      doc.appendChild(el);
    });
  }

  function paint() {
    // 阅读进度：已读到第几句 / 共几句。
    //  放在 paint 里更新 —— 它是"界面状态变化"的统一入口，
    //  不需要额外挂事件，也不会漏掉任何导致 cur 变化的路径。
    try {
      const bar = document.querySelector('#prog i');
      if (bar) {
        const n = sents.length || 1;
        const pct = Math.max(0, Math.min(100, ((cur + 1) / n) * 100));
        bar.style.width = pct.toFixed(2) + '%';
        // 读到最后一句时变绿：给一个"读完了"的明确信号
        bar.classList.toggle('done', cur >= sents.length - 1);
      }
    } catch (e) { void e; }

    const nodes = document.querySelectorAll('#doc .s');
    nodes.forEach((n, i) => {
      n.classList.toggle('cur', i === cur);
      const v = stats[i];
      n.classList.toggle('done', i < cur);
      n.classList.toggle('known', !!(v && v.marks));
      n.classList.toggle('asked', !!(v && v.asked));
      // prep = 系统已在后台为这句准备好讲解（用户没求助，所以不弹出来）
      n.classList.toggle('prepped', !!(v && v.prep));
      // 人工标注的真值（用于评估）：难=红色左框，没问题=绿色左框
      n.classList.toggle('truth-hard', !!(v && v.truth === 1));
      n.classList.toggle('truth-ok', !!(v && v.truth === 0));
    });
    const node = nodes[cur];
    if (node) {
      const r = node.getBoundingClientRect();
      // 只在高亮句离开舒适区时滚动，避免每句都跳
      if (r.top < 120 || r.bottom > innerHeight - 120) {
        node.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
    // 这里不再写死"每句 N 秒" —— 那是旧的固定间隔，
    // 会把"按句长计算"的真实结果盖住，让人以为系统没在算。
    // 状态栏由 updateStateHud() 统一维护（含倒计时）。
  }

  function go(i, reason) {
    if (i < 0 || i >= sents.length) return;
    if (cur >= 0 && cur !== i) {
      // 离开时结算本句停留时长（>=0.15s 才算，避免抖动穿越）
      const v = st(cur);
      if (reader._enterAt) {
        const d = (performance.now() - reader._enterAt) / 1000;
        if (d >= 0.15) {
          v.dwell += d;
          // 最长单次停留 —— 受阻判定的辅助依据之一（"卡了很久"）
          if (d > v.longest) v.longest = d;
        }
      }
    }
    // 访问计数（= 回看次数的来源）
    //
    //  修过的错误：早先只要"进入一句且距上次离开 > 0.5s"就 visits++，
    //  于是 5 -> 退回 4 -> 前进回 5 这一串操作会给第 5 句记一次"回看"，
    //  进而被判为"用户卡住了"、提前准备并打上标记。
    //  但【从退回状态前进回来】不是你主动回看 —— 那是返程，不是访问。
    //
    //  现在只把两种情况算作新访问：
    //    · 第一次进入这一句
    //    · 通过【退回】(reason === 'back') 主动回到这一句
    const isFirstTime = (st(i).visits || 0) === 0;
    const isDeliberateBack = (reason === 'back');
    const isNewVisit = isFirstTime || (isDeliberateBack && cur !== i);
    if (cur >= 0) st(cur).lastExit = performance.now();

    cur = i;
    const v = st(i);
    if (isNewVisit) { v.visits++; v.lastEnter = performance.now(); }
    v.asked = v.asked || 0;
    reader._enterAt = performance.now();
    acc = 0;
    paint();
    if (reader.onAdvance) reader.onAdvance(sents[cur], reason || 'auto', cur);
  }

  function tick(now) {
    raf = requestAnimationFrame(tick);
    if (!last) { last = now; return; }
    const dt = (now - last) / 1000;
    last = now;
    if (!playing) return;
    acc += dt;                     // acc 仍然累计 —— 它就是"本句实际停留时长"
    // 手动模式下不自动翻句：由用户按 → 决定何时前进。
    //  这样"停留时长"才真正反映阅读行为，而不是系统给的配额。
    if (PACE.mode === 'auto' && acc >= advanceFor(cur)) go(cur + 1, 'auto');
  }
  raf = requestAnimationFrame(tick);

  const reader = {
    onAdvance: null,
    onCorrection: null,   // (kind, idx) kind: 'back' | 'skip'
    _enterAt: 0,
    load(list) {
      sents = list; cur = -1;
      for (const k in stats) delete stats[k];
      for (const k in extraSec) delete extraSec[k];   // 单句额外时间只属于本次阅读
      // 按文章主要语言套用上次记住的速度 —— 不用重新学一遍
      applyPaceFor(list);
      render();
      go(0, 'init');
    },
    start() { playing = true; acc = 0; paint(); this._sync(); },
    pause() { playing = false; this._sync(); },
    toggle() { playing ? this.pause() : this.start(); },
    isPlaying() { return playing; },
    // → 下一句。提前跳过说明【这一句给多了】—— 同样只影响这一句，不动全局速度。
    next() {
      if (playing && cur >= 0 && acc < advanceFor(cur) * 0.6) {
        const ex = extraSec[cur] || 0;
        if (ex > 0) extraSec[cur] = Math.max(0, ex - advanceFor(cur) * 0.3);
        if (reader.onCorrection) reader.onCorrection('skip', cur);
      }
      go(cur + 1, 'manual');
    },
    // ← 上一句。退回说明【上一句给的时间不够】—— 只给那一句加时间。
    //
    //  早先这里会把全局速度调慢并保存，那是错的：
    //  退回是单句信息，不该改变"我的阅读速度"这个个人属性，
    //  更不该把它永久写进 localStorage（下次打开整篇都变慢）。
    prev() {
      if (cur > 0) {
        const target = cur - 1;
        const base = advanceFor(target);
        // 每次退回给该句增加 50% 的时间（上限 3 倍，避免无限累加）
        const cur2 = extraSec[target] || 0;
        extraSec[target] = Math.min(cur2 + base * 0.5, base * 2);
        if (reader.onCorrection) reader.onCorrection('back', target);
      }
      go(cur - 1, 'back');   // 用独立 reason：调用方据此判断"这句是被退回的，没读完"
    },
    jump(i) { go(i, 'manual'); },
    // 速度现在以"字/秒"为单位（滑块直接对应它）
    setSpeed(v) {
      PACE.cps = Math.max(PACE.MIN, Math.min(PACE.MAX, v));
      perSent = v;
      notePace();          // 滑块是显式设置，直接记住
      paint();
    },
    getSpeed() { return PACE.cps; },
    advanceFor(i) { return advanceFor(i === undefined ? cur : i); },
    // 本句的时间进度，供状态栏做倒计时（让"系统在算"这件事看得见）
    progress() {
      if (!playing || cur < 0) return null;
      return { budget: advanceFor(cur), elapsed: acc, left: Math.max(0, advanceFor(cur) - acc) };
    },
    getPace() { return Object.assign({}, PACE); },
    extraOf(i) { return extraSec[i] || 0; },
      // 由 Trigger 学到新速度时调用。
    //
    //  保存策略从"每 10 个样本存一次"改成"按时间节流" ——
    //  现场问题："速度测完再重打开插件，速度和保存前不一致"。
    //  原因是显示的是实时值，而只有第 10/20/30 个样本才写盘，
    //  最后几个样本算出来的值丢了。现在最多 2 秒就落一次盘，
    //  并且关闭面板/暂停时会强制写一次。
    applyLearnedPace(newCps) {
      if (!(newCps > PACE.MIN && newCps < PACE.MAX)) return;
      PACE.cps = newCps;
      PACE.byLang[PACE.lang] = newCps;
      if (PACE.learnedFrom === 'default') PACE.learnedFrom = 'learned';
      savePace(false);
    },
    flushPace() { savePace(true); },
    setMode(m) { PACE.mode = (m === 'manual') ? 'manual' : 'auto'; },
    getMode() { return PACE.mode; },
    // 速度来源：saved=用上次记住的，learned=本次学出来的，default=默认
    paceInfo() { return { cps: PACE.cps, lang: PACE.lang,
                          from: PACE.learnedFrom, byLang: Object.assign({}, PACE.byLang) }; },
    resetPace() {
      PACE.byLang = { zh: null, en: null, mix: null };
      PACE.cps = PACE.DEFAULT_CPS;
      PACE.learnedFrom = 'default';
      savePace();
    },
    getCur() { return cur; },
    getSents() { return sents; },
    getStats() { return stats; },
    markKnown(i) { st(i).marks = 1; paint(); },
    markAsked(i) { st(i).asked = 1; paint(); },
    // 人工真值标注（用于评估推断层准不准）
    setTruth(i, v) { st(i).truth = v; paint(); },
    setPred(i, state, ratio) { const v = st(i); v.pred = state; v.predRatio = ratio; },
    enterAt() { return this._enterAt; },
    // 给"已静默准备好讲解"的句子加个记号，让后台动作【看得见】
    // show=true 才打绿点标记。句长触发的准备是"静默缓存"，不打标记 ——
    //  否则约 40% 的句子都带标记，满屏绿点反而成了噪声，
    //  用户看到"啥也没操作却加了标记"会觉得莫名其妙。
    markPrepared(i, show) { if (show) { st(i).prep = 1; paint(); } },
    _sync() {
      const b = document.getElementById('btnPlay');
      b.textContent = playing ? '暂停' : '播放';
      b.classList.toggle('on', playing);
    },
  };
  return reader;
})();

/* ---------------------------------------------------------------------------
 *  ③ Trigger —— 只负责"判断该不该讲解"
 *  接口：Trigger.shouldExplain(sent, stats) -> {yes, reason}
 *
 *  现在只有一种触发：用户按空格（手动，reason='manual'）。
 *  将来要接"停留时长异常就静默准备"时，只需在这里加分支，
 *  Reader / Explainer / SidePanel 都不用改。
 * ------------------------------------------------------------------------- */
const Trigger = (() => {
  // ------------------------------------------------------------------
  //  阈值照搬 tools/cognitive_state.py（那套逻辑已用合成数据自测 6/6 通过）
  //
  //  判定采用【两条件同时满足】：
  //    ratio > T_BLOCKED  说明在这句花的处理量远超预期
  //    且 aux 非空        说明有"回去过 / 卡了很久 / 有操作事件"
  //  缺一不可，因为单独任一条件都会误判：
  //    · 只看 ratio 高  -> 把"这句本来就长、正常读完"判成受阻
  //    · 只看回看       -> 把"偶尔扫回上一句对照"判成受阻
  // ------------------------------------------------------------------
  const RULE = {
    T_SKIP: 0.35,          // 低于此比例且无回看 -> 跳过
    T_READ_LO: 0.50,       // 正常阅读下界
    T_READ_HI: 1.80,       // 正常阅读上界
    // 实测校准（手动模式 29 句标注）：
    //   阈值 2.0 -> 精确 0.21；2.6 -> 精确 0.38；4.0 -> 精确 1.00（样本太少）
    //   取 2.6：精确率比默认提高约 80%，召回保持 0.60
    //   注意本用法是【静默准备】，误报只是多缓存一条讲解，代价极低，
    //   所以宁可偏向高召回 —— 漏报会让用户按空格后干等。
    T_BLOCKED: 2.60,       // 高于此比例且满足辅助条件 -> 处理受阻
    T_PREPARE: 1.50,       // 仅用于状态显示（判定已改用句长启发式）
    // 句长启发式：句子长度 >= 本文章中位长度的这个倍数时就提前准备。
    //   1.3 大致对应「准备最长的 40%」，实测约覆盖 60% 的难句。
    PREP_UNITS_MULT: 1.30,
    MIN_PREP_OBS: 8,      // 至少观察这么多句才开始用句长启发式
    AUX_REVISIT_MIN: 2,    // 回看次数 >= 2
    AUX_LONG_VISIT_MULT: 2.0,
    AUTO_REVEAL_WINDOW_S: 30,
    AUTO_REVEAL_COUNT: 3,
    CPS_DEFAULT: 5.0,      // 字/秒，会随阅读实时校正
    SPEED_WINDOW: 60,    // 速度估计的滚动窗口（句）
    MIN_SPEED_SAMPLES: 6,// 至少这么多样本才开始用估计值
    CPS_MIN: 2.0,
    CPS_MAX: 14.0,
  };

  let cps = RULE.CPS_DEFAULT;

  // ------------------------------------------------------------------
  //  单位计数器由外部注入 —— 不让 Trigger 直接依赖 TextSource。
  //
  //  为什么：Trigger 是纯判定逻辑，越独立越好测。
  //  一开始我让它直接调 TextSource.units()，结果单测里抽不出 Trigger
  //  （TextSource 不在作用域内）—— 这就是耦合的代价。
  //  默认退化为字符数，App 里再注入真正的"中文按字/英文按词"计数器。
  // ------------------------------------------------------------------
  let countUnits = function (text) { return String(text || '').length; };
  function setUnitCounter(fn) { if (typeof fn === 'function') countUnits = fn; }
  const prepared = new Map();     // 句子文本 -> 已准备好的讲解
  const blockedAt = [];           // 受阻时刻，用于"30 秒内三次"的自动展开
  let lastAutoReveal = 0;

  function baseOf(sent) {
    // 同样要用【阅读单位】而不是字符数 —— 否则英文句子的 ratio 会系统性偏小
    // （因为分母按字母数算，虚高），永远判不出受阻。
    const u = countUnits(sent.text);
    return Math.max(u / cps, 0.3);
  }

  // 评估一句：返回状态与全部依据
  function evaluate(sent, st) {
    if (!sent || !st) return { state: 'off' };
    const base = baseOf(sent);
    const effort = st.dwell || 0;
    const ratio = effort / base;
    const revisit = Math.max((st.visits || 0) - 1, 0);
    const longest = st.longest || 0;

    // 退回次数（按 ← 回到这一句）是自动推进模式下【唯一有效】的信号：
    //   "停留时长"在自动模式下恒等于系统给的时间，没有信息量；
    //   而"我退回来了"说明这句给的时间不够 —— 这正是设计文档里的回看信号。
    const backs = st.backs || 0;
    const revisits = Math.max(revisit, backs);

    const aux = [];
    if (revisits >= RULE.AUX_REVISIT_MIN) aux.push('回看' + revisits + '次');
    if (base && longest > base * RULE.AUX_LONG_VISIT_MULT) {
      aux.push('单次' + longest.toFixed(1) + 's');
    }

    // 判定分两条路：
    //   ① 时间路（手动推进时有效）：ratio 高 且 有辅助条件
    //   ② 操作路（自动推进时有效）：退回次数 >= 2
    //  自动模式下时间路失效（ratio 恒等于系统给的时间），所以必须留操作路。
    let state;
    if (backs >= RULE.AUX_REVISIT_MIN) state = 'blocked';
    else if (ratio > RULE.T_BLOCKED && aux.length) state = 'blocked';
    else if (ratio < RULE.T_SKIP && revisits === 0) state = 'skipped';
    else state = 'reading';

    return { state, ratio, revisit: revisits, backs, base, effort, longest, aux };
  }

  // 用"正常读完"的句子校正阅读速度基线。
  //  这是整套判定的基础：不能假设所有人速度一样，
  //  否则读得慢的人会被全部判成受阻（设计文档里就强调过这点）。
  // ------------------------------------------------------------------
  //  基线（阅读速度）的估计
  //
  //  实测发现的错误：早先是"前 8 句建基线，之后只从判定为正常的句子学"。
  //  结果初期一旦定高就锁死了 —— 现场学到 2.35 单位/秒，
  //  而实际速度中位只有 1.54，基线偏高 53%，
  //  导致 ratio 系统性放大、出现 11 个误报（用户标"没问题"却判受阻）。
  //
  //  改成：用【最近若干句的实测速度中位数】持续自我校正。
  //  · 中位数天然抗离群 —— 少数难句（占比不到 20%）不会把基线拉偏
  //  · 滚动窗口让它能跟上速度变化（比如读久了变慢）
  //  · 不再依赖"先判对状态才能学习"，避免冷启动死锁
  // ------------------------------------------------------------------
  const speedWin = [];      // [{ units, dwell }]
  let paceSink = null;      // 学到新速度时的回调（由外部注入）

  function learn(sent, r) {
    if (!sent || !r) return;
    const cu = countUnits(sent.text);
    // 太短的片段（标题、单字）速度噪声大，不参与
    if (cu < 5 || r.effort < 0.8) return;
    const sp = cu / r.effort;
    if (!(sp > RULE.CPS_MIN && sp < RULE.CPS_MAX)) return;

    speedWin.push(sp);
    if (speedWin.length > RULE.SPEED_WINDOW) speedWin.shift();
    if (speedWin.length < RULE.MIN_SPEED_SAMPLES) return;

    const sorted = speedWin.slice().sort((x, y) => x - y);
    cps = sorted[Math.floor(sorted.length / 2)];      // 中位数

    // 学到的速度交给外部处理（保存/应用），Trigger 自己【不知道】PACE 是什么。
    //
    //  这里我又犯过一次耦合错误：最初直接写 PACE.byLang[...] = cps 和 savePace()，
    //  结果单测只抽出 Trigger 模块时 PACE 未定义、直接崩 ——
    //  和之前"Trigger 直接调 TextSource.units"是同一个毛病。
    //  凡是纯逻辑模块，对外部的需求都用注入解决。
    if (paceSink) paceSink(cps, speedWin.length);
  }

  // 由调用方注入：学到新速度时做什么（保存、应用等）
  function setPaceSink(fn) { paceSink = (typeof fn === 'function') ? fn : null; }

  // 重新测速：清空速度观察窗口，让基线从零开始重新建立
  function resetLearn() {
    speedWin.length = 0;
    prepUnits.length = 0;
  }

  // ------------------------------------------------------------------
  //  是否该静默准备讲解
  //
  //  这一版是【三轮实测之后改的】，理由有数据支撑：
  //
  //    句长 units        AUC 0.64
  //    停留 dwell        AUC 0.63     （与句长相关 r=0.77）
  //    ratio             AUC 0.53     （无用）
  //    三者组合          AUC 0.63     （没有超过单信号）
  //
  //  也就是说：整套行为推断，效果与「数句子长度」相当。
  //  而句长启发式还有三个额外好处：
  //    · 零延迟、不用等基线建立（第一句就能用）
  //    · 不依赖推进模式（自动模式下行为信号会被系统配速抹平）
  //    · 用户一看就懂（长句更容易难），便于解释
  //
  //  但行为信号里有一块【稀有但精确】的信息（实测退回时精确率 0.75），
  //  所以保留它做补充：一旦用户退回过某句，就一定为它准备。
  //
  //  代价核算（119 句标注）：准备最长的 50% 可覆盖 71% 的难句，
  //  误报 36 条 —— 按一次讲解约 0.002 元算，白花 0.07 元。可忽略。
  // ------------------------------------------------------------------
  const prepUnits = [];      // 观察到的句子长度，用于算本文的中位长度

  function noteSentenceUnits(sent) {
    if (!sent) return;
    const u = countUnits(sent.text);
    if (u > 0) {
      prepUnits.push(u);
      if (prepUnits.length > 400) prepUnits.shift();
    }
  }

  // 为什么该为这句准备讲解？返回原因字符串，或 null 表示不需要。
  //  与 shouldPrepare 分开的原因：shouldPrepare 会检查"是否已准备"，
  //  而界面需要知道"这句是否【属于会被准备的那类】"以便显示标记 ——
  //  已准备过的句子也应该显示标记，否则用户看不到它在工作。
  function prepReason(sent, r) {
    if (!sent) return null;

    // (1) 行为信号（稀有但精确）：退回或重复进入过 -> 一定准备
    if (r && ((r.backs || 0) >= 1 || (r.revisit || 0) >= 1)) return 'back';

    // (2) 句长启发式：比本文章的中位句长明显长 -> 准备
    //     用【本文章的中位长度】而不是绝对阈值 —— 不同文章的句长分布差很多
    //     （新闻短句多，论文长句多），绝对阈值没法通用。
    if (prepUnits.length >= RULE.MIN_PREP_OBS) {
      const sorted = prepUnits.slice().sort((a, b) => a - b);
      const med = sorted[Math.floor(sorted.length / 2)];
      const u = countUnits(sent.text);
      if (med > 0 && u >= med * RULE.PREP_UNITS_MULT) return 'long';
    }
    return null;
  }

  function shouldPrepare(sent, r) {
    if (!sent || prepared.has(sent.text)) return false;
    return prepReason(sent, r) !== null;
  }

  // 30 秒内受阻 3 次以上 -> 自动展开（带冷却，避免每帧触发）
  function shouldAutoReveal(now) {
    const t = now / 1000;
    while (blockedAt.length && t - blockedAt[0] > RULE.AUTO_REVEAL_WINDOW_S) blockedAt.shift();
    if (blockedAt.length < RULE.AUTO_REVEAL_COUNT) return false;
    if (t - lastAutoReveal < RULE.AUTO_REVEAL_WINDOW_S) return false;   // 冷却
    lastAutoReveal = t;
    return true;
  }

  function noteBlocked(now) { blockedAt.push(now / 1000); }

  // 手动触发的判定（空格）
  function shouldExplain(sent, stats, reason) {
    if (reason === 'manual') return { yes: true, reason: 'manual' };
    return { yes: false, reason: 'off' };
  }

  function stats_() {
    return { cps, samples: speedWin.length, prepared: prepared.size,
             prepObserved: prepUnits.length,
             bootstrapping: speedWin.length < RULE.MIN_SPEED_SAMPLES,
             window: speedWin.length };
  }

  // 冷启动期（基线还没建好）不做"受阻"判定 —— 此时判也不准，只会误导。
  function ready() { return speedWin.length >= RULE.MIN_SPEED_SAMPLES; }

  return {
    RULE, evaluate, learn, shouldPrepare, shouldAutoReveal, noteBlocked, setUnitCounter, ready,
    noteSentenceUnits, prepReason, setPaceSink, resetLearn,
    shouldExplain, prepared, stats: stats_,
  };
})();

/* ---------------------------------------------------------------------------
 *  ④ Explainer —— 只负责"建 prompt + 调 LLM + 缓存"
 *  接口：Explainer.explain(sent, ctxSents) -> Promise<string>
 *        Explainer.setProvider(cfg)
 *
 *  扩展点就在这里：以后想加"代码解释""教材辅导"等技能，
 *  只需在 SKILLS 里加一个 prompt 构造器，其余模块不动。
 * ------------------------------------------------------------------------- */
const Explainer = (() => {
  // ==================================================================
  //  讲解生成
  //
  //  三类后端：
  //    kind: 'builtin'  浏览器内置小模型（免费、无需 key、本地跑）
  //    kind: 'cloud'    OpenAI 兼容的云端 API（要 key，多数有几毛钱额度）
  //    kind: 'mock'     占位（不调用任何 API，用于验证界面）
  //
  //  为什么把内置模型放在第一位：
  //    这是唯一"零成本 + 零配置 + 不联网"的方案。
  //    Chrome / Edge 138+ 自带 Gemini Nano / Phi 一类的小模型，
  //    通过 LanguageModel 接口调用，模型文件由浏览器自己下载（一次性）。
  //    对于"解释一句话"这种短任务，小模型够用，而且没有 API 费用。
  //
  //  注意：供应商的价格与免费额度会变，界面里的说明只是"注册入口 + 大致定位"，
  //        真实价格请以各家控制台为准。代码里不写死价格。
  // ==================================================================
  const PROVIDERS = {
    builtin: {
      label: '浏览器内置模型（免费 · 无需 key · 本地）',
      kind: 'builtin',
      note: 'Chrome / Edge 138+ 自带。首次使用浏览器会下载模型文件（约 2GB，一次性）。' +
            '之后完全本地运行，不联网、不花钱。',
    },
    zhipu: {
      label: '智谱 GLM（Flash 系列有免费额度）',
      kind: 'cloud',
      url: 'https://open.bigmodel.cn/api/paas/v4/chat/completions',
      model: 'glm-4-flash',
      // 免费的那几个放最前面 —— 用户在下拉里一眼就能选到不要钱的。
      //  名单按智谱「模型广场」里标着「普惠模型，免费调用」的写。
      //  注意：名字是【模型广场里的显示名小写】，不是产品页上的名字。
      models: ['glm-4-flash', 'glm-4-flash-250414', 'glm-4.7-flash',
               'glm-4-plus', 'glm-4-air'],
      keyUrl: 'https://bigmodel.cn/usercenter/proj-mgmt/apikeys',
      note: 'Flash 系列历来有免费额度。' +
            '注册后到【个人中心 → 项目管理 → API Keys】新建一个（不在「模型广场」里）。',
    },
    siliconflow: {
      label: '硅基流动 SiliconFlow（部分模型免费）',
      kind: 'cloud',
      url: 'https://api.siliconflow.cn/v1/chat/completions',
      model: 'Qwen/Qwen2.5-7B-Instruct',
      models: ['Qwen/Qwen2.5-7B-Instruct', 'THUDM/glm-4-9b-chat',
               'deepseek-ai/DeepSeek-V3'],
      keyUrl: 'https://cloud.siliconflow.cn/account/ak',
      note: '模型广场里有免费模型（名字不带 Pro/ 前缀的多半免费）。',
    },
    doubao: {
      label: '豆包 Doubao（火山方舟，按量计费很便宜）',
      kind: 'cloud',
      url: 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
      model: '',
      models: [],
      keyUrl: 'https://console.volcengine.com/ark',
      note: '需要先在火山方舟控制台「开通模型」并创建「接入点」，' +
            '把接入点 ID（形如 ep-2024xxxx）或模型名填到「模型名」里。',
    },
    deepseek: {
      label: 'DeepSeek（便宜）',
      kind: 'cloud',
      url: 'https://api.deepseek.com/v1/chat/completions',
      model: 'deepseek-chat',
      models: ['deepseek-chat', 'deepseek-reasoner'],
      keyUrl: 'https://platform.deepseek.com/api_keys',
      note: '价格低，中文好。reasoner 更贵也更慢，讲解用 chat 就够。',
    },
    qwen: {
      label: '通义千问（DashScope 兼容模式）',
      kind: 'cloud',
      url: 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',
      model: 'qwen-turbo',
      models: ['qwen-turbo', 'qwen-plus', 'qwen-flash'],
      keyUrl: 'https://bailian.console.aliyun.com/',
      note: 'qwen-turbo / qwen-flash 是便宜档。',
    },
    moonshot: {
      label: 'Kimi（Moonshot）',
      kind: 'cloud',
      url: 'https://api.moonshot.cn/v1/chat/completions',
      model: 'moonshot-v1-8k',
      models: ['moonshot-v1-8k', 'moonshot-v1-32k'],
      keyUrl: 'https://platform.moonshot.cn/console/api-keys',
      note: '长上下文见长；讲解短句用 8k 就够。',
    },
    openai: {
      label: 'OpenAI',
      kind: 'cloud',
      url: 'https://api.openai.com/v1/chat/completions',
      model: 'gpt-4o-mini',
      models: ['gpt-4o-mini', 'gpt-4.1-mini'],
      keyUrl: 'https://platform.openai.com/api-keys',
      note: '需要能直连；mini 档便宜。',
    },
    gemini: {
      label: 'Google Gemini（有免费额度）',
      kind: 'cloud',
      url: 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions',
      model: 'gemini-2.0-flash',
      models: ['gemini-2.0-flash', 'gemini-2.0-flash-lite'],
      keyUrl: 'https://aistudio.google.com/apikey',
      note: '有免费额度（有速率上限）。国内访问可能需要代理。',
    },
    groq: {
      label: 'Groq（有免费额度，速度很快）',
      kind: 'cloud',
      url: 'https://api.groq.com/openai/v1/chat/completions',
      model: 'llama-3.3-70b-versatile',
      models: ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant'],
      keyUrl: 'https://console.groq.com/keys',
      note: '有免费额度，响应很快。国内访问可能需要代理。',
    },
    ollama: {
      label: '本地 Ollama（免费 · 本地 · 需要自己装）',
      kind: 'cloud',
      url: 'http://localhost:11434/v1/chat/completions',
      model: 'qwen2.5:7b',
      models: ['qwen2.5:7b', 'llama3.2', 'gemma2:9b'],
      keyUrl: 'https://ollama.com/download',
      note: '装好 Ollama 后 `ollama pull qwen2.5:7b`。Key 随便填（Ollama 不校验）。' +
            '注意：扩展页面访问 localhost 可能需要在浏览器里允许。',
    },
    custom: {
      label: '自定义（OpenAI 兼容）',
      kind: 'cloud',
      url: '',
      model: '',
      models: [],
      note: '填任何 OpenAI 兼容的 /v1/chat/completions 地址。',
    },
    mock: {
      label: '占位（不调用任何 API）',
      kind: 'mock',
      note: '用于验证界面与触发逻辑，返回假数据。',
    },
  };

  // ==================================================================
  //  术语查证
  //
  //  为什么不问 LLM：实测两轮都错在术语译名上
  //    panorama stitching   -> "图像拼贴"（应为 全景拼接）
  //    computer-vision tech -> "数字视觉技术"（应为 计算机视觉技术）
  //  它理解意思没问题（括号里的解释是对的），但给出的【名字】不是通用叫法。
  //  所以译名从外部查，查到了再作为权威对照交回给模型。
  //
  //  两级来源：
  //    ① 下面的离线术语表 —— 不联网可用，覆盖高频词
  //    ② Wikipedia 跨语言链接 —— 条目标题是编辑共识出来的，权威且免费
  //  都查不到就不注入任何东西，模型照常回答（查证失败不能阻塞讲解）。
  // ==================================================================
  const termCache = new Map();      // 术语 -> 中文译名（空串表示查过但没查到）

  // ------------------------------------------------------------------
  //  用户术语表：用户自己按 "english = 中文" 一行一条填，存 localStorage。
  //
  //  为什么需要它：任何内置词表都只顾得上一个领域，而用户
  //  （尤其是读自己专业文献的人）比任何词典都清楚自己领域的标准叫法。
  //  这是最省事、最可靠的领域适配方式。
  // ------------------------------------------------------------------
  const USER_TERM_KEY = 'rf_user_terms_v1';
  let userTerms = null;

  function loadUserTerms() {
    if (userTerms) return userTerms;
    userTerms = {};
    try {
      const raw = localStorage.getItem(USER_TERM_KEY) || '';
      raw.split('\n').forEach(line => {
        const t = line.trim();
        if (!t || t.startsWith('#')) return;
        const m = t.split('=');
        if (m.length < 2) return;
        const k = m[0].trim().toLowerCase();
        const v = m.slice(1).join('=').trim();
        if (k && v) userTerms[k] = v;
      });
    } catch (e) {
      console.warn('[reader] 读取用户术语表失败:', e && e.message);
    }
    return userTerms;
  }

  // 查一个术语的译名是哪来的。返回 { zh, from } 或 null。
  //  from: 'user'  你的术语表（最可信）
  //        'wiki'  外部查证（Wikipedia 跨语言链接）
  //        'model' 模型自己给的（未查证）
  //
  //  这个区分是"可信"这条线的核心：界面上要能一眼看出
  //  哪部分是有出处的、哪部分是模型自己说的。
  function termSourceOf(en) {
    const k = String(en || '').trim().toLowerCase();
    if (!k) return null;
    const ut = loadUserTerms();
    if (ut[k]) return { zh: ut[k], from: 'user' };
    // lookupTerm 会把查到的结果写进 termCache；这里只读缓存，不再发网络请求
    const cached = termCache.get(k);
    if (cached && !ut[k]) {
      // 缓存里有值但不是用户表来的 -> 是外部查证的结果
      return { zh: cached, from: 'wiki' };
    }
    return null;
  }

  // 把一条订正写进用户术语表。返回写入后的总条数。
  //  用户读到误译时一键加进来，下次（以及所有同术语的句子）就用这个了。
  function addUserTerm(en, zh) {
    const k = String(en || '').trim().toLowerCase();
    const v = String(zh || '').trim();
    if (!k || !v) return 0;
    const cur = loadUserTerms();
    cur[k] = v;
    const lines = Object.keys(cur).map(x => x + ' = ' + cur[x]);
    setUserTerms(lines.join('\n'));
    // 订正后旧讲解作废 —— 否则同一句还会显示错误的旧译名
    cache.clear();
    return Object.keys(cur).length;
  }

  function setUserTerms(text) {
    userTerms = null;
    try { localStorage.setItem(USER_TERM_KEY, String(text || '')); }
    catch (e) { console.warn('[reader] 保存用户术语表失败:', e && e.message); }
    termCache.clear();
  }

  function getUserTermsText() {
    try { return localStorage.getItem(USER_TERM_KEY) || ''; } catch (e) { return ''; }
  }
  // Wikipedia 查证的临时禁用。
  //  早先是一个布尔量，一次失败就【永久】关闭 —— 实测后果是
  //  "一次网络抖动之后，本次会话所有术语都不再有来源标记"（用户反馈）。
  //  改成带冷却时间：失败后停一会儿，时间到了自动恢复。
  let wikiDisabledUntil = 0;
  const WIKI_BACKOFF_MS = 3 * 60 * 1000;   // 冷却 3 分钟         // 连不上就本会话不再试，避免每次都等超时

  const TERM_STOP = new Set(('the a an and or of to in on for with by is are was were be been ' +
    'this that these those it its as at from into over under than then when where which who ' +
    'can could may might must shall should will would do does did done have has had not no ' +
    'but if so such only also more most less least very much many few some any all both ' +
    'we they he she you i one two three first second next last other another same new old ' +
    'example however therefore thus hence because although while since').split(' '));

  // 从句子里挑"可能是术语"的候选：连字符复合词、全大写缩写、2~3 个词的连续序列
  function termCandidates(text) {
    const out = new Set();
    const t = String(text || '');
    (t.match(/\b[A-Za-z]{3,}(?:-[A-Za-z]{2,})+\b/g) || []).forEach(x => {
      out.add(x.toLowerCase().replace(/-/g, ' '));
      out.add(x.toLowerCase());
    });
    (t.match(/\b[A-Z]{2,6}\b/g) || []).forEach(x => {
      const lx = x.toLowerCase();
      if (!TERM_STOP.has(lx)) out.add(lx);
    });
    const words = t.match(/[A-Za-z][A-Za-z-]{1,}/g) || [];
    for (let k = 2; k <= 3; k++) {
      for (let i = 0; i + k <= words.length; i++) {
        const seq = words.slice(i, i + k);
        const low = seq.map(w => w.toLowerCase());
        if (TERM_STOP.has(low[0]) || TERM_STOP.has(low[low.length - 1])) continue;
        if (seq.some(w => w.length < 3)) continue;
        out.add(low.join(' '));
      }
    }
    return Array.from(out);
  }

  // 查一个术语的中文译名：先离线表，再 Wikipedia（4 秒超时）
  async function lookupTerm(term) {
    // 键统一【小写】—— 早先这里用原样做键、termSourceOf 用小写读，
    //  两边对不上就永远命中不了，表现为"来源标记全没了"。
    const key = String(term || '').trim().toLowerCase();
    if (!key) return '';
    if (termCache.has(key)) return termCache.get(key);

    // 优先级：用户术语表 > 维基百科
    //  用户最清楚自己领域的叫法，所以放最前。
    const ut = loadUserTerms();
    if (ut[key]) { termCache.set(key, ut[key]); return ut[key]; }

    // 冷却期内不查（避免失败后每个词都去撞一次网）
    if (Date.now() < wikiDisabledUntil) return '';

    try {
      const ctl = new AbortController();
      const timer = setTimeout(() => ctl.abort(), 4000);
      const title = key.replace(/\b\w/g, c => c.toUpperCase());
      const url = 'https://en.wikipedia.org/w/api.php?action=query&format=json&origin=*' +
                  '&prop=langlinks&lllang=zh&redirects=1&titles=' + encodeURIComponent(title);
      const res = await fetch(url, { signal: ctl.signal });
      clearTimeout(timer);
      if (!res.ok) return '';
      const j = await res.json();
      const pages = (j && j.query && j.query.pages) || {};
      for (const kk in pages) {
        const ll = pages[kk] && pages[kk].langlinks;
        if (ll && ll.length && ll[0]['*']) {
          const got = String(ll[0]['*']).trim();
          // 只有【查到东西】才写缓存。
          //  早先无论成败都先 set(key, '') —— 等于把"查不到"永久写死。
          termCache.set(key, got);
          return got;
        }
      }
      return '';                       // 确实没有中文条目，不算失败
    } catch (e) {
      // 网络失败：进入冷却，且【不】写负面缓存，冷却结束后可以重来
      wikiDisabledUntil = Date.now() + WIKI_BACKOFF_MS;
      console.warn('[reader] Wikipedia 术语查证暂时不可用，' +
                   Math.round(WIKI_BACKOFF_MS / 1000) + ' 秒后自动重试：',
                   (e && e.message) || e);
      return '';
    }
  }

  // 为一句中的术语批量查证，返回 { 术语: 中文译名 }
  async function buildGlossary(sentText) {
    const cands = termCandidates(sentText);
    if (!cands.length) return {};
    cands.sort((a, b) => b.length - a.length);
    const pick = cands.slice(0, 12);
    const found = {};
    await Promise.all(pick.map(async (t) => {
      const zh = await lookupTerm(t);
      if (zh && zh.toLowerCase() !== t) found[t] = zh;
    }));
    return found;
  }

  let cfg = { provider: 'builtin', key: '', model: '', base: '' };
  const cache = new Map();      // 句子文本 -> 讲解（同一句不重复请求）
  let lastCall = null;          // 最近一次调用的信息（耗时、后端、错误），供界面显示
  let builtinState = 'unknown'; // 内置模型的可用性缓存

  // ---- 技能（prompt 策略）----
  // 加新技能只需在这里加一项，并在下面 pickSkill 里选它。
  const SKILLS = {
    explain: {
      name: '讲解',
      // ------------------------------------------------------------------
      //  prompt 是根据实测缺陷写的，不是凭空设计：
      //    实测（Edge 内置 Phi-mini）里出现「panorama stitching -> 图像拼贴」
      //    这种术语错译，以及大段重复和"这句话强调了……"式空话。
      //    判断是小模型扛不住 5 条并列要求，于是复述/总结（最好写）写满，
      //    术语准确性（最难）失守。
      //    所以改成 3 段固定结构 + 显式反例，降低指令复杂度。
      // ------------------------------------------------------------------
      // ================================================================
      //  ⚠️ 改这两套 prompt 时，【】只能用在三个输出标题上：
      //        【这句在说什么】【词】【难点】
      //
      //      别的地方一律用「」。
      //      原因：模型分不清"要它输出的标题"和"给它的说明" ——
      //      实测它照着我们写的说明，真的输出了 "【每段的标题】"
      //      这样的字符串，正文退化成英文复述。
      //
      //      这个坑已经踩过 4 次（每次都是顺手用【】做强调）。
      //      test-trust.js 第④块会当场拦住，改完记得跑：
      //          node tools/test-trust.js
      // ================================================================
      // 两套 prompt，按后端能力自动选。
      //
      //  为什么必须分两套：
      //    实测过 —— 763 字符、12 个【】标记的 prompt 会把小模型压崩，
      //    它分不清"元指令"和"要输出的标题"，真的输出了
      //    "【每段的标题】"这种字符串，正文退化成英文复述。
      //    压到 352 字符 / 3 个【】之后就正常了。
      //    但大模型能同时满足更多要求，砍掉那些提示反而浪费。
      //
      //  选择规则见 promptFor()。
      lite:
        '你是阅读辅助助手，帮读者看懂论文里的句子。\n' +
        '按三节输出，每节标题单独占一行：\n' +
        '\n' +
        '【这句在说什么】\n' +
        '用中文一句话讲清主干。\n' +
        '\n' +
        '【词】\n' +
        '列句子里的专业术语，一条一行，括号里给对应说法。例如：\n' +
        '__TERM_EX__\n' +
        '没有术语写"无"。\n' +
        '\n' +
        '【难点】\n' +
        '句子复杂时写主干与修饰成分，不复杂写"无"。',

      // 完整版：多两条对"可信"有用的约束，但仍然【只陈述、不命令】——
      //  上一版写成"不要编造""必须采用"这类句子，被模型原样抄进了输出。
      full:
        '你是阅读辅助助手，帮读者看懂论文里的句子。\n' +
        '按三节输出，每节标题单独占一行，全文不超过 180 字：\n' +
        '\n' +
        '【这句在说什么】\n' +
        '用中文一句话讲清主干（谁对谁做了什么）。\n' +
        '\n' +
        '【词】\n' +
        '只列真正的专业术语，最多 4 条，一条一行，括号里给对应说法。例如：\n' +
        '__TERM_EX__\n' +
        '没有术语写"无"。\n' +
        '\n' +
        '【难点】\n' +
        '句子复杂时写主干与修饰成分，不复杂写"无"。\n' +
        '\n' +
        '讲解只依据目标句和给定的上下文；材料里没有的细节不写。\n' +
        '拿不准的地方写"这句我不确定"。',

      build(target, before, after, gloss) {
        let s = '';
        // 用户消息里的分节也尽量不用【】，避免和"要输出的标题"混淆。
        //  （实测：混用之后模型会照着把说明文字也当成标题输出。）
        if (before.length) s += '上文：\n' + before.map(x => x.text).join('\n') + '\n\n';
        s += '目标句（用户读不懂的是这句）：\n' + target.text + '\n\n';
        if (after.length) s += '下文：\n' + after.map(x => x.text).join('\n') + '\n\n';
        // 这里【不再】注入术语对照。
        //  实测它反而把模型带乱了 —— 看到 "computer vision = 计算机视觉"
        //  之后，它开始输出 "（英文原词: real-time | 实时；计算机视觉 | 计算机视觉）"
        //  这种格式，还编出了 "OpenCV = 奥克拉夫视网膜"。
        //  改成：模型只负责解释意思，译名由界面侧查证后填入（见 SidePanel.termRow）。
        // 结尾也不要用【】—— 它是分节标题的语法，
        //  实测模型会照着"补"出一个以「目标句】」开头的输出。
        s += '请按上面的格式讲解「目标句」。直接输出三节内容，' +
             '不要重复上面的说明文字，不要输出「目标句」这几个字。';
        return s;
      },
    },
  };

  // 术语行的例子必须按【目标句的语言】选，而且只给一行。
  //
  //  实测（中英混排的论文）：源句是英文，模型却把术语写成
  //      "神经元振荡同步（neurotransmission synchronization）"
  //  —— 术语中文、括号英文，正好反了，对读英文的人没用。
  //  原因是 prompt 里同时给了中英两行例子，模型自己挑错了。
  //  所以由代码按句子语言决定，不给模型挑的机会。
  // 括号里要的是【解释】而不是译名。
  //  实测：写成纯译名（神经振荡同步）之后，用户反馈"有的词得有词语解释啊"。
  //  解释里自然带上中文叫法，一举两得。
  const TERM_EX_EN = '    neuronal oscillatory synchronization（神经振荡同步：大脑不同区域的活动节奏趋于一致）';
  const TERM_EX_ZH = '    神经振荡同步（大脑不同区域的活动节奏趋于一致，是工作记忆的基础）';

  function termExampleFor(text) {
    const t = String(text || '');
    const cjk = (t.match(/[\u4e00-\u9fff]/g) || []).length;
    // 比的是【英文单词数】而不是字母数 ——
    //  一个英文单词往往顶好几个汉字，按字母数会把
    //  "中文句子里嵌一个英文术语"误判成英文为主（实测就是这么错的）：
    //      研究还揭示了 neural oscillatory synchronization 这类机制的作用。
    //      汉字 14 个、字母 32 个 -> 按字母数判成英文，其实这是中文句子。
    const latWords = (t.match(/[A-Za-z]+/g) || []).length;
    return (cjk > latWords * 2) ? TERM_EX_ZH : TERM_EX_EN;
  }

  // 按后端能力选 prompt 版本。
  //  小后端（浏览器内置模型、本地 Ollama 的小模型）扛不住复杂指令，
  //  给它们精简版；云端大模型给完整版。
  //  判断依据是后端的 kind 与名字，不需要用户配置。
  // 注意：参数名不能省 —— 下面要用 sent.text 选术语例子。
  //  （早先这里写成 pickSkill(/* sent */)，参数被注释掉了；
  //    后来加"按语言选例子"时用了 sent，直接 ReferenceError，
  //    表现是每一句都"讲解失败：sent is not defined"。）
  function pickSkill(sent) {
    const key = cfg.provider;
    const p = providerOf(key);
    const isSmall = (p.kind === 'builtin') || (key === 'ollama');
    const raw = isSmall ? SKILLS.explain.lite : SKILLS.explain.full;
    // 把术语例子换成与目标句语言相符的那一行
    const sys = raw.replace(/__TERM_EX__/g, termExampleFor(sent && sent.text));
    return {
      name: SKILLS.explain.name,
      system: sys,
      build: SKILLS.explain.build,
      variant: isSmall ? 'lite' : 'full',
    };
  }

  function context(sents, i, beforeN = 2, afterN = 1) {
    const before = [], after = [];
    for (let k = Math.max(0, i - beforeN); k < i; k++) before.push(sents[k]);
    for (let k = i + 1; k <= Math.min(sents.length - 1, i + afterN); k++) after.push(sents[k]);
    return { before, after };
  }

  function mockText(target, before) {
    return '【占位讲解】当前是占位模式，这里是假数据，用于验证界面与触发逻辑。\n\n' +
      '· 目标句：' + target.text.slice(0, 60) + (target.text.length > 60 ? '…' : '') + '\n' +
      '· 携带上文 ' + before.length + ' 句、下文若干句作为上下文\n' +
      '· 句子长度 ' + target.text.length + ' 字\n\n' +
      '在右上角「API 设置」里选一个后端即可换成真实讲解 —— ' +
      '想完全不花钱就选「浏览器内置模型」。';
  }

  // ------------------------------------------------------------------
  //  内置模型（浏览器自带）
  // ------------------------------------------------------------------
  function builtinAPI() {
    // 各家/各版本的命名不一样，逐个试：
    //   Chrome 138+ / Edge 138+   LanguageModel
    //   早期 origin trial         window.ai.languageModel
    //   更早的 Chrome origin trial chrome.aiOriginTrial.languageModel
    try {
      if (typeof LanguageModel !== 'undefined' && LanguageModel) return LanguageModel;
      if (typeof ai !== 'undefined' && ai && ai.languageModel) return ai.languageModel;
      if (typeof chrome !== 'undefined' && chrome.aiOriginTrial &&
          chrome.aiOriginTrial.languageModel) return chrome.aiOriginTrial.languageModel;
    } catch (e) { void e; }
    return null;
  }

  // 浏览器到底暴露了什么 —— 用于把"没有接口"这句话拆成可操作的原因
  function builtinProbe() {
    const out = {
      names: [],
      ua: (typeof navigator !== 'undefined' && navigator.userAgent) || '',
      secure: (typeof window !== 'undefined') ? !!window.isSecureContext : false,
    };
    try {
      if (typeof LanguageModel !== 'undefined') out.names.push('LanguageModel');
      if (typeof ai !== 'undefined') out.names.push('ai');
      if (typeof chrome !== 'undefined' && chrome.aiOriginTrial) out.names.push('chrome.aiOriginTrial');
      if (typeof Summarizer !== 'undefined') out.names.push('Summarizer');
      if (typeof Translator !== 'undefined') out.names.push('Translator');
    } catch (e) { void e; }
    const m = /(Edg|Chrome)\/(\d+)/.exec(out.ua);
    out.brand = m ? m[1] : '?';
    out.major = m ? Number(m[2]) : 0;
    return out;
  }

  // 复位内置模型的可用性缓存。
  //  外面（App 的"重新检测"按钮）需要这个能力。但不能直接给
  //  Explainer 的私有变量赋值 —— 那样在非严格模式下不报错（隐式全局），
  //  却也【不会真的复位】，按钮点了等于没点。必须走导出的接口。
  function resetBuiltinState() { builtinState = 'unknown'; }

  async function builtinInfo() {
    const api = builtinAPI();
    if (!api) {
      return { api: null, state: 'unavailable',
               reason: '这个浏览器没有内置模型接口。' +
                       '两个办法：① 在 edge://flags 里搜索 ' +
                       '"Prompt API for on-device language model" 并设为 Enabled，重启浏览器；' +
                       '② 点【API 设置】换成任意云端后端。' };
    }
    try {
      const a = await api.availability();
      builtinState = a;
      return { api, state: a };
    } catch (e) {
      return { api, state: 'unavailable', reason: e && e.message };
    }
  }

  async function callBuiltin(messages, onProgress) {
    const info = await builtinInfo();
    if (!info.api) throw new Error(info.reason || '内置模型不可用');
    if (info.state === 'unavailable') throw new Error('浏览器内置模型不可用');

    // 注意：这里【不能】因为 downloadable / downloading 就退出。
    //  下载正是由下面的 create() 触发的 —— 提前返回等于把下载入口堵死，
    //  用户只会看到"说会自己下，但一直没动静"。
    //  create() 会在模型就绪后才 resolve，所以 await 它就覆盖了整个下载过程。

    const sys = messages.filter(m => m.role === 'system').map(m => m.content).join('\n');
    const usr = messages.filter(m => m.role !== 'system').map(m => m.content).join('\n');

    const opts = {};
    if (sys) opts.initialPrompts = [{ role: 'system', content: sys }];
    // 这里【故意不设】temperature / topK。
    //  上一版设了 temperature=0.2 + topK=3，结果 topK=3 太激进 ——
    //  只从 3 个候选里选，换行符几乎不可能被选中，输出挤成一整行，
    //  分节和术语行全部失效。
    //  而"小模型输出不稳定"这个问题，用卡片上的 ⟳ 重新生成就够了 ——
    //  不要为了一个没验证的改善，引入一个已验证的破坏。
    // 下载进度必须可见 —— 首次要下几百 MB 到 2GB，
    // 没有反馈的话用户分不清"在下载"和"卡死了"。
    opts.monitor = (m) => {
      try {
        m.addEventListener('downloadprogress', (e) => {
          const pct = e && typeof e.loaded === 'number' ? Math.round(e.loaded * 100) : 0;
          if (onProgress) onProgress(pct, e);
          builtinState = (pct >= 100) ? 'available' : 'downloading';
        });
      } catch (err) { void err; }
    };

    const session = await info.api.create(opts);
    try {
      const out = await session.prompt(usr);
      return String(out).trim();
    } finally {
      // 用完就销毁会话：讲解是单次任务，不需要保持上下文，
      // 否则每次都会把上一句的对话带上，白耗上下文。
      if (session && session.destroy) { try { session.destroy(); } catch (e) { void e; } }
    }
  }

  // 只把内置模型下载到本机，不提问。
  //
  //  为什么单独做这个入口：下载由 create() 触发，而首次 create() 要等
  //  几百 MB 到 2GB 下完才 resolve。如果只能靠"按空格"触发，
  //  用户会看着卡片静静地转很久，分不清是在下载还是卡死了。
  //  给一个独立的下载按钮，进度能显示出来，"等一下"就变得可接受。
  async function prepareBuiltin(onProgress) {
    const info = await builtinInfo();
    if (!info.api) throw new Error(info.reason || '这个浏览器没有内置模型接口');
    const st = String(info.state || '');
    if (st === 'unavailable') {
      throw new Error('浏览器没有提供内置模型（开关没生效或硬件不满足），下载也解决不了');
    }
    if (st === 'available') return true;

    const opts = {};
    opts.monitor = (m) => {
      try {
        m.addEventListener('downloadprogress', (e) => {
          const pct = e && typeof e.loaded === 'number' ? Math.round(e.loaded * 100) : 0;
          builtinState = (pct >= 100) ? 'available' : 'downloading';
          if (onProgress) onProgress(pct, e);
        });
      } catch (err) { void err; }
    };
    // create() 在模型就绪后才 resolve —— await 它就覆盖了整个下载过程
    const session = await info.api.create(opts);
    builtinState = 'available';
    if (session && session.destroy) { try { session.destroy(); } catch (e) { void e; } }
    return true;
  }

  // ------------------------------------------------------------------
  //  云端（OpenAI 兼容）
  // ------------------------------------------------------------------
  function providerOf(name) {
    return PROVIDERS[name] || PROVIDERS.mock;
  }

  function resolveEndpoint() {
    const p = providerOf(cfg.provider);
    const url = (cfg.provider === 'custom' && cfg.base) ? cfg.base : p.url;
    const model = cfg.model || p.model;
    return { p, url, model };
  }

  async function callCloud(messages) {
    const { p, url, model } = resolveEndpoint();
    if (!url) throw new Error('没填 API 地址');
    if (!model) throw new Error('没填模型名');
    if (p.kind !== 'cloud') throw new Error('不是云端后端');

    const res = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + (cfg.key || 'ollama'),
      },
      body: JSON.stringify({ model, messages, temperature: 0.3, max_tokens: 700 }),
    });
    if (!res.ok) {
      const t = await res.text().catch(() => '');
      let hint = '';
      if (res.status === 401) hint = '（key 不对或没填）';
      else if (res.status === 403) hint = '（没有权限／额度用尽）';
      else if (res.status === 404) hint = '（地址或模型名不对）';
      else if (res.status === 429) hint = '（请求太频繁，稍后再试）';
      throw new Error('HTTP ' + res.status + ' ' + hint + ' ' + t.slice(0, 160));
    }
    const j = await res.json();
    const c = j && j.choices && j.choices[0];
    const txt = c && (c.message ? c.message.content : c.text);
    if (!txt) throw new Error('返回内容为空');
    return String(txt).trim();
  }

  async function callLLM(messages, onProgress) {
    const p = providerOf(cfg.provider);
    if (p.kind === 'builtin') return callBuiltin(messages, onProgress);
    if (p.kind === 'cloud') return callCloud(messages);
    throw new Error('占位模式不调用 API');
  }

  // ------------------------------------------------------------------
  //  对外接口
  // ------------------------------------------------------------------
  // 小模型有时会把喂给它的输入复述回来（实测输出里出现了
  //   "### 上文：" 后面跟着我们给的原文）。它"没话可说"之后不会自己停。
  //  这类痕迹有明显特征，比要求它别抄更可靠 —— 直接切掉。
  const ECHO_MARKS = [
    /\n#{0,6}\s*上文\s*[:：]/,
    /\n#{0,6}\s*下文\s*[:：]/,
    /\n#{0,6}\s*目标句[（(]/,
    /\n#{0,6}\s*以下是已查证/,
  ];
  function trimEcho(t) {
    let out = String(t || '');
    let cut = -1;
    ECHO_MARKS.forEach(re => {
      const m = re.exec(out);
      if (m && (cut < 0 || m.index < cut)) cut = m.index;
    });
    if (cut > 0) out = out.slice(0, cut);
    // 兜底：prompt 要求 120~180 字，正常不会超过 2000 字符
    if (out.length > 2000) out = out.slice(0, 2000) + '…';
    return out.trim();
  }

  async function explain(target, sents, onProgress) {
    const key = target.text;
    if (cache.has(key)) return cache.get(key);

    const { before, after } = context(sents, target.idx);
    const skill = pickSkill(target);
    const p = providerOf(cfg.provider);

    // 术语查证（离线表 + Wikipedia）。查不到就返回空对象，不影响讲解。
    let gloss = {};
    try { gloss = await buildGlossary(target.text); } catch (e) { void e; }

    let out;
    const t0 = performance.now();
    if (p.kind === 'mock') {
      out = mockText(target, before);
      // 模拟网络延迟，让"静默准备"的状态可见
      await new Promise(r => setTimeout(r, 260));
      lastCall = { ok: true, ms: 260, backend: 'mock' };
    } else {
      try {
        out = await callLLM([
          { role: 'system', content: skill.system },
          { role: 'user', content: skill.build(target, before, after, gloss) },
        ], onProgress);
        lastCall = { ok: true, ms: Math.round(performance.now() - t0),
                     backend: p.kind + ':' + (cfg.model || p.model || '') };
      } catch (e) {
        lastCall = { ok: false, ms: Math.round(performance.now() - t0),
                     backend: p.kind, error: (e && e.message) || String(e) };
        throw e;
      }
    }
    // 返回对象而不是字符串：把【本次用上的术语对照】一起带出去，
    //  界面才能标出"这条译名有出处、那条是模型自己给的"。
    const res = {
      text: trimEcho(out),
      gloss: gloss || {},
      backend: lastCall && lastCall.backend,
      variant: skill.variant,
    };
    cache.set(key, res);
    return res;
  }

  // 测试连接 —— 这是之前一直没做的事：API 能不能通，从没验证过。
  // 返回 { ok, ms, msg, pending }，界面直接显示。
  async function test(onProgress) {
    const p = providerOf(cfg.provider);
    const t0 = performance.now();

    if (p.kind === 'mock') {
      return { ok: true, ms: 0, msg: '占位模式：不调用任何 API' };
    }
    if (p.kind === 'builtin') {
      const info = await builtinInfo();
      if (!info.api) return { ok: false, msg: info.reason };
      if (info.state === 'unavailable') return { ok: false, msg: '内置模型不可用' };
      // downloadable / downloading 都继续 —— 由 callBuiltin 里的 create() 触发下载。
      //  返回 pending 只会让用户以为"它自己会下"，而实际上永远不会开始。
    }
    if (p.kind === 'cloud') {
      const { url, model } = resolveEndpoint();
      if (!url) return { ok: false, msg: '没填 API 地址' };
      if (!model) return { ok: false, msg: '没填模型名' };
      if (!cfg.key && cfg.provider !== 'ollama') {
        return { ok: false, msg: '还没填 API Key' };
      }
    }

    try {
      const out = await callLLM([
        { role: 'system', content: '你是一个测试助手。无论用户说什么，只回复两个字：可用' },
        { role: 'user', content: '测试' },
      ], onProgress);
      const ms = Math.round(performance.now() - t0);
      return { ok: true, ms, msg: '连接成功（' + ms + 'ms）　返回：' + out.slice(0, 30) };
    } catch (e) {
      const ms = Math.round(performance.now() - t0);
      return { ok: false, ms, msg: '失败：' + ((e && e.message) || String(e)) };
    }
  }

  // 检测本机可用的后端。返回 [{name, status, detail, hint}]
  async function diagnose() {
    const rows = [];

    // ---- 内置模型 ----
    const probe = builtinProbe();
    const api = builtinAPI();
    if (api) {
      let st = 'unknown';
      try { st = await api.availability(); } catch (e) { st = 'error:' + (e && e.message); }
      const ok = (st === 'available');
      rows.push({
        name: '浏览器内置模型',
        status: ok ? 'ok' : (st === 'downloadable' ? 'warn'
                            : st === 'downloading' ? 'warn' : 'fail'),
        detail: '接口可用，状态：' + st +
                (ok ? '　（选它就不用 key、不花钱）' : ''),
        hint: st === 'downloadable'
              ? '模型可用但还没下载。点上面的「测试连接」会【开始下载】' +
                '（首次几百 MB 到 2GB，一次性，之后不再下载）'
            : st === 'downloading' ? '正在下载中，等它完成即可'
            : ok ? '' : '接口在但模型不可用',
      });
    } else {
      let hint;
      if (probe.major && probe.major < 138) {
        hint = '浏览器版本 ' + probe.brand + ' ' + probe.major +
               '，内置模型需要 138 及以上 —— 升级浏览器，或改用下面的云端后端';
      } else if (probe.brand === 'Edg') {
        hint = 'Edge 的内置模型接口目前需要手动开启：' +
               '地址栏输入 edge://flags，搜索 "Prompt API"，设为 Enabled，重启浏览器。' +
               '重启后首次调用会下载模型文件（约 2GB，一次性）。' +
               '若 flags 里没有这一项，说明该版本还没带，请改用云端后端';
      } else {
        hint = '地址栏输入 chrome://flags，搜索 "Prompt API"，设为 Enabled 后重启；' +
               '或升级到 Chrome 138+。也可以用下面的云端后端';
      }
      rows.push({
        name: '浏览器内置模型',
        status: 'fail',
        detail: '页面里没有语言模型接口（' + (probe.names.length ? '发现：' + probe.names.join(', ') : '什么都没发现') +
                '　' + probe.brand + ' ' + probe.major + '）',
        hint: hint,
      });
    }

    // ---- 云端后端：测网络可达性（不带 key，401/403 就说明通）----
    const keys = Object.keys(PROVIDERS).filter(k => PROVIDERS[k].kind === 'cloud' && PROVIDERS[k].url);
    for (const k of keys) {
      const p = PROVIDERS[k];
      const t0 = performance.now();
      let status = 'fail', detail = '';
      try {
        const ctl = new AbortController();
        const timer = setTimeout(() => ctl.abort(), 6000);
        const res = await fetch(p.url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ model: p.model || 'test',
                                 messages: [{ role: 'user', content: 'hi' }], max_tokens: 1 }),
          signal: ctl.signal,
        });
        clearTimeout(timer);
        const ms = Math.round(performance.now() - t0);
        if (res.status === 401 || res.status === 403) {
          status = 'ok';
          detail = '网络可达，返回 ' + res.status + '（正常：还没填 key 或 key 无效）　' + ms + 'ms';
        } else if (res.status === 400 || res.status === 404 || res.status === 422) {
          status = 'ok';
          detail = '网络可达，返回 ' + res.status + '（多半是模型名或地址要调整）　' + ms + 'ms';
        } else if (res.status === 429) {
          status = 'warn';
          detail = '网络可达，但被限流（429）　' + ms + 'ms';
        } else {
          status = 'warn';
          detail = '网络可达，返回 ' + res.status + '　' + ms + 'ms';
        }
      } catch (e) {
        const ms = Math.round(performance.now() - t0);
        const m = (e && e.name === 'AbortError')
          ? '超时（6 秒）—— 网络不通，或需要代理'
          : ('连不上：' + ((e && e.message) || e));
        detail = m + '　' + ms + 'ms';
      }
      rows.push({ name: p.label, status, detail, hint: p.keyUrl ? ('获取 key：' + p.keyUrl) : '' });
    }

    return rows;
  }

  function setProvider(c) { cfg = Object.assign({}, cfg, c); }
  function getProvider() { return Object.assign({}, cfg); }
  function clearCache() { cache.clear(); }
  // 只清一句 —— 重新生成时用，不影响其它句子已备好的结果
  function clearOne(text) { cache.delete(String(text || '')); }
  function lastInfo() { return lastCall; }
  function providerMeta(name) { return providerOf(name); }

  return {
    explain, test, diagnose, setProvider, getProvider, clearCache, clearOne,
    setUserTerms, getUserTermsText, addUserTerm, termSourceOf,
    PROVIDERS, SKILLS, lastInfo, providerMeta, builtinInfo,
  resetBuiltinState, prepareBuiltin,
  };
})();

/* ---------------------------------------------------------------------------
 *  ⑤ SidePanel —— 只负责"显示讲解卡片"
 *  接口：SidePanel.add(sent, text) / SidePanel.loading(sent) / SidePanel.clear()
 * ------------------------------------------------------------------------- */
const SidePanel = (() => {
  const cards = document.getElementById('cards');
  const counter = document.getElementById('cardN');

  function refreshN() {
    const n = cards.querySelectorAll('.card').length;
    counter.textContent = n + ' 条';
    if (!n) {
      cards.innerHTML = '<div class="empty">按 <kbd>空格</kbd> 讲解当前句<br>讲解会出现在这里</div>';
    }
  }

  function scrollBottom() { cards.scrollTop = cards.scrollHeight; }

  // ---- 讲解卡片的渲染 ----
  //  讲解文本是分节的（【这句在说什么】【词】【难点】），
  //  为了让"哪部分可信"看得见，【词】那一节要逐行解析并标来源。
  function el(tag, cls, txt) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined) e.textContent = txt;
    return e;
  }

  // 解析一条术语行。两种形态：
  //    "panorama stitching = 全景拼接（把多张照片拼成宽幅图）"   -> 有译名
  //    "computer vision（用计算机处理视觉信息的技术）"            -> 只有解释
  // 术语行的"词"部分：英文以字母开头；中文以汉字开头。
  //
  //  早先只允许英文字母开头 —— 中文论文的术语因此全部解析失败，
  //  退化成普通文本，看起来就是"干列了一串词、没有解释"（用户实测反馈）。
  //  用 RegExp 拼是为了把这一段的字符类写在一处，两条规则共用。
  const TERM_HEAD = "[A-Za-z\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff\\-\\s.'\u2019\\/&]{0,58}?";
  const RE_TERM_EQ = new RegExp('^(' + TERM_HEAD + ')\\s*=\\s*([\\s\\S]+)$');
  const RE_TERM_PAREN = new RegExp('^(' + TERM_HEAD + ')\\s*[（(]\\s*([\\s\\S]+?)\\s*[）)]?\\s*$');

  function parseTermLine(line) {
    const t = String(line || '').trim();
    if (!t) return null;
    // 形式一："panorama stitching = 全景拼接（解释）" / "神经振荡 = 神经元群的同步电活动"
    let m = RE_TERM_EQ.exec(t);
    if (m) return { en: m[1].trim(), rest: m[2].trim(), claimsZh: true };
    // 形式二："computer vision（用计算机处理视觉信息的技术）" / "神经振荡（神经元群的同步电活动）"
    //  右括号必须单独处理 —— 写成 (.+)$ 会把 ） 也吃进 rest 里
    m = RE_TERM_PAREN.exec(t);
    if (m) return { en: m[1].trim(), rest: m[2].trim(), claimsZh: false };
    return null;
  }

  // 把 "全景拼接（把多张照片拼成一张宽幅图）" 拆成
  //   { name: '全景拼接', note: ' （把多张照片拼成一张宽幅图）' }
  //  拆不开时整段当译名，note 为空。
  function splitZh(rest) {
    const m = /^([^（(]+?)\s*([（(][\s\S]*)?$/.exec(rest);
    if (!m) return { name: String(rest || '').trim(), note: '' };
    const name = m[1].trim();
    if (!m[2]) return { name: name, note: '' };
    const note = m[2].trim();
    // 全角括号按中文排版不加空格；半角括号前面留一个空格
    const sep = /^（/.test(note) ? '' : ' ';
    return { name: name, note: sep + note };
  }

  // 一条术语行 -> DOM。带来源标记与订正按钮。
  function termRow(p) {
    const row = el('div', 'term');
    row.appendChild(el('span', 'en', p.en));

    // 译名【只认外部查证】：你的术语表 > Wikipedia 跨语言链接。
    //  模型自己写的 "xxx = yyy" 一律丢弃 —— 实测它会编出
    //  "OpenCV = 奥克拉夫视网膜" 这种东西，而用户扫一眼就可能当真。
    //  所以：查到就给 "英文 = 标准译名（解释）"，查不到就只给 "英文（解释）"。
    const src = Explainer.termSourceOf(p.en);
    const parts0 = splitZh(p.rest);           // 模型的输出里可能带译名，这里只取解释
    const note = parts0.note || ('（' + parts0.name + '）');

    const zh = el('span', 'zh', '');
    if (src) {
      zh.textContent = ' = ' + src.zh + ' ' + note;
    } else {
      zh.textContent = ' ' + note;
    }
    row.appendChild(zh);

    let badge = null;
    if (src) {
      badge = el('span', 'badge');
      badge.textContent = (src.from === 'user') ? '✓ 你的术语表' : '✓ 外部查证';
      badge.dataset.src = (src.from === 'user') ? 'user' : 'wiki';
      badge.classList.add('ok');
      row.appendChild(badge);
    }

    const btn = el('button', 'fix', '订正');
    btn.title = '这个词的标准中文名应该是什么？填一次，以后所有文章都用它';
    btn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const cur = (src && src.zh) || '';
      const v = window.prompt('「' + p.en + '」的标准中文名是？\n' +
                              '（会存进你的术语表，以后所有文章都用这个）', cur);
      if (v === null || !v.trim()) return;
      Explainer.addUserTerm(p.en, v.trim());
      // 就地改这一行，不重新请求 API —— 用户马上能看到效果
      zh.textContent = ' = ' + v.trim() + ' ' + (parts0.note || ('（' + parts0.name + '）'));
      if (!badge) {
        badge = el('span', 'badge');
        row.insertBefore(badge, btn);
      }
      badge.textContent = '✓ 你的术语表';
      badge.className = 'badge ok';
      badge.dataset.src = 'user';
      btn.textContent = '已订正';
      setTimeout(() => { btn.textContent = '订正'; }, 1200);
      // 订正后旧讲解作废：Explainer 的缓存已由 addUserTerm 清掉，
      //  但"静默准备"的结果还存在外面（键是句子文本），必须一起清，
      //  否则同一句还会显示旧译文。
      const card2 = row.closest ? row.closest('.card') : null;
      if (card2 && card2.dataset && card2.dataset.t && SidePanel.onTermCorrected) {
        SidePanel.onTermCorrected(card2.dataset.t);
      }
      const card = row.closest ? row.closest('.card') : null;
      if (card) refreshSrc(card);
      scrollBottom();
    });
    row.appendChild(btn);
    return row;
  }

  // 底部来源统计：把"哪部分可信"从抽象变成可数的
  function refreshSrc(card) {
    const f = card.querySelector('.srcstat');
    if (!f) return;
    const nUser = card.querySelectorAll('.badge[data-src="user"]').length;
    const nWiki = card.querySelectorAll('.badge[data-src="wiki"]').length;
    const nModel = card.querySelectorAll('.badge[data-src="model"]').length;
    const total = nUser + nWiki + nModel;
    if (!total) { f.textContent = ''; f.style.display = 'none'; return; }
    f.style.display = '';
    const bits = [];
    if (nUser) bits.push('你的术语表 ' + nUser);
    if (nWiki) bits.push('外部查证 ' + nWiki);
    if (nModel) bits.push('模型给出 ' + nModel);
    f.textContent = '术语 ' + total + ' 条：' + bits.join(' · ');
    if (nModel) f.classList.add('warn');
    else f.classList.remove('warn');
  }

  // 这一节是不是"术语"节。放宽判断 —— 模型可能写成【词】【术语】【词汇】。
  function isTermSection(sec) {
    return /词|术语|词汇|term/i.test(String(sec || ''));
  }

  // 一行看起来是不是术语定义。
  //  在术语节里：只要 parseTermLine 解析出来就用。
  //  不在术语节里：要额外守卫，否则会把 "However (as noted above)" 这种
  //  以英文开头的正文误判成术语。
  const TERM_STOP_EN = new Set(('the a an and or of to in on for with by is are was were ' +
    'be been this that these those it its as at from into over under than then when where ' +
    'which who can could may might must shall should will would do does did done have has ' +
    'had not no but if so such only also more most less least very much many few some any ' +
    'all both we they he she you i however therefore thus hence because although while ' +
    'since example').split(' '));

  function looksLikeTerm(p) {
    if (!p) return false;
    const words = String(p.en || '').trim().split(/\s+/).filter(Boolean);
    if (!words.length || words.length > 6) return false;
    if (TERM_STOP_EN.has(words[0].toLowerCase())) return false;
    // 带 "=" 的基本可以确定是术语定义；只有括号解释的要求更短（名词短语）
    return p.claimsZh ? true : words.length <= 4;
  }

  // 把讲解文本渲染成分节结构。
  //
  //  容错点：模型经常把标题和内容写在同一行，
  //      【词】Application areas = 应用领域（…）
  //  所以标题识别不能在行尾要求 $，要把同行剩下的内容接下去继续处理。
  //  （就因为这个，之前术语标记和订正按钮全都没显示出来。）
  // 有些模型会把整段输出挤成一行（实测出现过：topK 设太小的时候）。
  //  分节和术语行全靠换行识别，一挤就全废 —— 所以在【xxx】前面补上换行。
  //  只在这一行几乎没有换行时才做，避免误伤正常输出。
  function ensureBreaks(text) {
    const t = String(text || '');
    // 早先只在"整段几乎没有换行"时才补。
    //  但实测模型会【把标题和正文挤在同一行、别的行又有换行】——
    //  "换行数不足"这个前提就不成立了，于是标题没被切开、整段挤成一坨。
    //  改成：只要【…】前后不是换行就补一个。这对正常输出是无副作用的。
    return t
      // 前面不是换行 -> 补一个
      .replace(/([^\n])([ \t]*)\u3010([^\u3011]{1,14})\u3011/g, '$1\n\u3010$3\u3011')
      // 后面不是换行 -> 补一个
      .replace(/\u3010([^\u3011]{1,14})\u3011([^\n])/g, '\u3010$1\u3011\n$2')
      // 行首残留的空白
      .replace(/\n[ \t]+/g, '\n')
      .replace(/\n{3,}/g, '\n\n')
      .trim();
  }

  // ------------------------------------------------------------------
  //  模型会把 prompt 里的话原样抄进输出。
  //  实测出现过：
  //      "只输出上面三节，不要重复我给你的内容。"
  //      "必须 工作记忆（高级认知功能）"、"不需要 理论挑战（…）"
  //  前一句是整行泄漏；后两句是把 prompt 里的「必须」「不要」抄成了术语前缀。
  //
  //  这类问题靠"把 prompt 写得更小心"只能减少，不能消除 ——
  //  所以渲染层必须兜住：凡是看得出是 prompt 原文的行，直接丢掉。
  // ------------------------------------------------------------------
  const PROMPT_LEAK = [
    /只输出上面三节/,
    /不要重复我给你的内容/,
    /不要重复上面的说明/,
    /说明文字用中文/,
    /英文术语保留/,
    /中文术语照原样/,
    /在括号里给解释/,
    /不要只列词不解释/,
    /^不要写\s*[“"]/,          // "不要写 "词 = 另一个词" 这种形式"
    /^讲解只依据/,
    /^拿不准的地方写/,
    /^材料里没有的细节/,
    /^每节标题单独占一行/,
    /^按三节输出/,
  ];
  function isPromptLeak(t) {
    const x = String(t || '').trim();
    if (!x) return false;
    // 太长的行不太可能是 prompt 泄漏（prompt 的句子都很短）
    if (x.length > 60) return false;
    for (let i = 0; i < PROMPT_LEAK.length; i++) {
      if (PROMPT_LEAK[i].test(x)) return true;
    }
    return false;
  }

  // 术语开头可能残留 prompt 里的语气词（必须/不需要/不要/需要/应该）。
  //  实测：「必须 工作记忆（高级认知功能）」「不需要 理论挑战（对现有观点提出反驳）」
  function stripModalPrefix(en) {
    let x = String(en || '').trim();
    for (let i = 0; i < 4; i++) {
      const y = x.replace(/^(必须|不需要|不要|需要|应该|应当|请|务必)\s*/, '').trim();
      if (y === x) break;
      x = y;
    }
    return x;
  }

  // 术语的"词"部分可能被模型用引号包起来（实测：「大脑动态平衡」「神经通质」）。
  //  解析时剥掉，界面上再统一按我们的样式显示。
  function stripTermQuotes(t) {
    const x = String(t || '')
      .replace(/^[\s「『“‘"'(（]+/, '')
      .replace(/[\s」』”’"'）)]+$/, '')
      .trim();
    return stripModalPrefix(x);
  }

  // 从【整节文字】里全局抽取「词（解释）」。
  //
  //  为什么不按行解析：模型可以用任何方式排版 ——
  //      一行一条 / 用分号隔开 / 词和解释分成两行 / 用引号把词包起来
  //  用户实测的截图里三种混在一起，按行解析只认出了第一条。
  //  这里用模式抽取，不管它怎么排。
  function extractTermsFromSection(sectionText) {
    const out = [];
    const re = new RegExp(
      '([A-Za-z\\u4e00-\\u9fff][A-Za-z0-9\\u4e00-\\u9fff\\-\\s.\'\u2019\\/&「」『』\u201c\u201d]{0,40}?)' +
      '\\s*[（(]\\s*([^）)]{1,160}?)\\s*[）)]', 'g');
    let m;
    while ((m = re.exec(sectionText))) {
      const en = stripTermQuotes(m[1]);
      const rest = m[2].trim();
      if (!en || !rest) continue;
      if (en.length > 40) continue;          // 太长的不像术语，多半是叙述
      out.push({ en: en, rest: rest, claimsZh: false });
    }
    return out;
  }

  // 是不是一个分节标题。
  //  模型写标题的形式实测有四种：【词】 / 词 / 词: / 【词】：
  //  所以"方括号、冒号"都要容忍，否则标题会被当成正文行。
  //
  //  放在模块层级（而不是 renderBody 内部）—— 它是纯函数，
  //  提出来测试才抽得到（测试按 2 空格缩进找函数结尾）。
  function headerOf(line) {
    const h = /^【(.{1,14}?)】\s*[:：]?\s*([\s\S]*)$/.exec(line);
    if (h) return { name: h[1].replace(/[:：]\s*$/, '').trim(), rest: h[2].trim() };
    const bare = /^(这句在说什么|词|术语|难点)\s*[:：]?\s*$/.exec(line);
    if (bare) return { name: bare[1], rest: '' };
    return null;
  }

  // 同一节名归一化：模型会写【词】【术语】【词汇】，都算同一节。
  function normSection(name) {
    const x = String(name || '');
    if (/词|术语|词汇/.test(x)) return '词';
    if (/难|结构/.test(x)) return '难点';
    if (/说|讲|意思|主干/.test(x)) return '这句在说什么';
    return x;
  }

  // 比较两段文字是否"基本是同一段话"。
  //  去掉空白与标点之后，一方是另一方的前缀（或反之）即算重复。
  //  用于两个场景：模型重复同一段解释、以及模型把源句抄成内容。
  function normForCompare(t) {
    return String(t || '')
      .replace(/[\s，。、；：！？,.;:!?"'\u201c\u201d\u2018\u2019（）()\[\]\u3010\u3011-]/g, '')
      .toLowerCase();
  }
  function looksSame(a, b) {
    const x = normForCompare(a), y = normForCompare(b);
    if (!x || !y) return false;
    if (x === y) return true;
    const n = Math.min(x.length, y.length);
    if (n < 12) return false;              // 太短不好判断，别误杀
    // 一方包含另一方（源句被抄成内容时常见）
    if (x.indexOf(y) >= 0 || y.indexOf(x) >= 0) return true;
    // 开头一段相同就算。
    //  不能要求"整个短句都是另一句的前缀" —— 那个判据太严：
    //  重复输出时模型只保持开头一致，后面会换措辞。
    //      心理反应性指的是一种厌恶动机的现象，比如…
    //      心理反应性指的是一种厌恶性的动机现象，比如…
    //  开头 12 个字相同，第 13 个字就分叉了。
    const head = Math.min(12, Math.floor(n / 2));
    if (head >= 10 && x.slice(0, head) === y.slice(0, head)) return true;
    return false;
  }

  function renderBody(bodyEl, text, srcText) {
    bodyEl.textContent = '';
    const recent = [];                  // 刚输出过的行，用于去重
    const source = String(srcText || '');
    const lines = ensureBreaks(text).split('\n');
    // 术语去重：小模型经常把同一个词列两遍
    const seenTerms = new Set();
    let section = '';
    let lastEmitted = '';     // 最近输出过的标题，用来抑制重复标题
    let sawFirstSection = false;   // 见过第一节标题没有（用于识别"整段重复"）
    let i = 0;

    function addTerm(p) {
      const key = p.en.toLowerCase();
      if (seenTerms.has(key)) return;
      seenTerms.add(key);
      bodyEl.appendChild(termRow(p));
    }

    while (i < lines.length) {
      let t = lines[i].trim();
      i++;
      if (!t) { bodyEl.appendChild(el('div', 'gap')); continue; }

      const h = headerOf(t);
      if (h) {
        const norm = normSection(h.name);
        // 模型有时会把整段输出重复好几遍（小模型的重复退化）。
        //  判据：第一节标题【这句在说什么】再次出现，说明它在从头循环。
        //  截图里见过整块重复 3~4 次、中间用 --- 隔开。
        if (norm === '这句在说什么' && sawFirstSection) {
          console.warn('[reader] 模型重复输出整段内容，已在第 ' + i + ' 行截断');
          break;
        }
        if (norm === '这句在说什么') sawFirstSection = true;
        section = norm;
        // 同一个标题只输出一次 —— 实测模型会在每条术语前都写一遍【词】
        if (section !== lastEmitted) {
          bodyEl.appendChild(el('div', 'sec', '【' + section + '】'));
          lastEmitted = section;
        }
        t = h.rest;
        if (!t) continue;
      }

      // prompt 原文被抄进输出的行，直接丢掉
      if (isPromptLeak(t)) continue;
      // 模型把【源句】抄成了内容（实测整句英文原文被抄进第一节）
      if (source && looksSame(t, source)) continue;
      // 同一段话被重复输出（实测连着四条"…指的是…"，措辞略不同）
      if (recent.some(x => looksSame(t, x))) continue;
      recent.push(t);

      // ---- 术语节：收集到下一个标题为止，整段抽取 ----
      //   这样"一行一条 / 分号隔开 / 词与解释分行"三种排版都能覆盖。
      if (isTermSection(section)) {
        const buf = [t];
        while (i < lines.length) {
          const nx = lines[i].trim();
          const nh = headerOf(nx);
          if (nh) {
            // 重复的同一个标题（模型每条术语前都写一遍）当分隔符跳过，继续收集
            if (normSection(nh.name) === section && !nh.rest) { i++; continue; }
            break;
          }
          if (isPromptLeak(nx)) { i++; continue; }
          buf.push(nx);
          i++;
        }
        const joined = buf.join(' ').replace(/\s+/g, ' ').trim();
        const terms = extractTermsFromSection(joined);
        if (terms.length) {
          terms.forEach(addTerm);
        } else if (joined && joined !== '无' && joined !== '无。') {
          // 抽不出术语就原样显示（可能是"无"，也可能是模型写了别的东西）
          bodyEl.appendChild(el('div', 'ln', joined));
        }
        continue;
      }

      // ---- 其它节：按行处理 ----
      if (isPromptLeak(t)) continue;
      const p = parseTermLine(t);
      if (p && looksLikeTerm(p)) { addTerm(p); continue; }
      bodyEl.appendChild(el('div', 'ln', t));
    }
  }

  // 给卡片上的 ⟳ 绑定重新生成。
  //  具体"怎么重新生成"由外部注入（SidePanel.regenerate），
  //  这里只管界面状态 —— 保持 SidePanel 不依赖 Reader / Explainer。
  function bindRegen(card) {
    const btn = card.querySelector('.regen');
    if (!btn) return;
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation();
      if (!card.__sent || !SidePanel.regenerate) return;
      if (btn.disabled) return;
      btn.disabled = true;
      btn.textContent = '\u22ef';
      const b = card.querySelector('.body');
      const old = b ? b.textContent : '';
      if (b) {
        b.textContent = '正在重新生成……';
        b.classList.add('loading');
        b.style.color = '';          // 清掉上一次失败留下的红色
      }
      try {
        const res = await SidePanel.regenerate(card.__sent);
        fill(card, res);
      } catch (e) {
        if (b) { b.classList.remove('loading'); b.textContent = old; b.style.color = ''; }
        console.warn('[reader] 重新生成失败:', e);
        if (typeof msg === 'function') msg('重新生成失败：' + ((e && e.message) || e), true);
      } finally {
        btn.disabled = false;
        btn.textContent = '\u27f3';
      }
    });
  }

  let d = null;   // 当前正在处理的卡片（订正回调里要用）

  function add(sent, result) {
    // result 可能是 { text, gloss }（新）或字符串（旧调用）
    const text = (typeof result === 'string') ? result : ((result && result.text) || '');
    const e = cards.querySelector('.empty');
    if (e) e.remove();
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML =
      '<div class="idx">第 ' + (sent.idx + 1) + ' 句' +
      '<button class="regen" title="重新生成（内置模型每次结果不一样，可以多摇几次）">\u27f3</button>' +
      '</div>' +
      '<div class="src"></div>' +
      '<div class="body"></div>' +
      '<div class="srcstat"></div>';
    card.querySelector('.src').textContent = sent.text;
    card.dataset.t = sent.text;    // 同上，供静默准备回填时定位
    card.__sent = sent;
    bindRegen(card);
    card.addEventListener('click', ev => {
      if (ev.target.classList.contains('src')) Reader.jump(sent.idx);
    });
    d = card;
    // 把源句一起传进去 —— renderBody 用它识别"模型把源句抄成了内容"
    renderBody(card.querySelector('.body'), text,
               (card.querySelector('.src') || {}).textContent || card.dataset.t || '');
    refreshSrc(card);
    cards.appendChild(card);
    refreshN();
    scrollBottom();
    d = null;
    return card;
  }

  function loading(sent) {
    const e = cards.querySelector('.empty');
    if (e) e.remove();
    const d = document.createElement('div');
    d.className = 'card';
    d.innerHTML =
      '<div class="idx">第 ' + (sent.idx + 1) + ' 句' +
      '<button class="regen" title="重新生成（内置模型每次结果不一样，可以多摇几次）">\u27f3</button>' +
      '</div>' +
      '<div class="src"></div>' +
      '<div class="body loading" style="color:">正在生成讲解……</div>' +
      '<div class="srcstat"></div>';
    // data-t 让"静默准备完成时补进正在看的卡片"能定位到这张卡
    d.dataset.t = sent.text;
    d.__sent = sent;
    bindRegen(d);
    d.querySelector('.src').textContent = sent.text;
    cards.appendChild(d);
    refreshN();
    scrollBottom();
    return d;
  }

  function fill(card, result) {
    const text = (typeof result === 'string') ? result : ((result && result.text) || '');
    const b = card.querySelector('.body');
    b.classList.remove('loading');
    // 清掉 fail() 留下的内联红色。
    //  内联样式写上去就一直生效，而 fill 只改文字 ——
    //  不清的话"失败过一次之后这一句永远是红的"。
    b.style.color = '';
    d = card;
    renderBody(b, text,
               (card.querySelector('.src') || {}).textContent || card.dataset.t || '');
    if (!card.querySelector('.srcstat')) {
      card.appendChild(el('div', 'srcstat'));
    }
    refreshSrc(card);
    d = null;
    scrollBottom();
  }

  function fail(card, msg) {
    const b = card.querySelector('.body');
    b.classList.remove('loading');
    b.style.color = '#ff6b6b';
    b.textContent = '讲解失败：' + msg;
  }

  function clear() { cards.innerHTML = ''; refreshN(); }

  // onTermCorrected：订正术语后由外部挂上来（用来清掉那一句的预备讲解）。
  //  用回调而不是直接调 Trigger，保持模块之间不互相依赖。
  // regenerate：外部注入的"重新生成"实现；all：导出用，取当前所有卡片
  function all() { return Array.prototype.slice.call(cards.querySelectorAll('.card')); }

  // 把一张渲染好的卡片序列化成 Markdown。
  //
  //  为什么不能直接读 .body 的 textContent：
  //    .body 里是一堆块级 div（.sec / .term / .ln / .gap），
  //    textContent 会把它们【不加换行地连起来】—— 导出结果整段挤成一行；
  //    而且术语行里的「订正」按钮和「✓ 你的术语表」标记也会被读进去。
  //  按结构走一遍，既拿得回分段，又能把术语写成 Markdown 列表。
  function cardToMarkdown(card) {
    const out = [];
    const idxEl = card.querySelector('.idx');
    if (idxEl) {
      const t = idxEl.textContent.replace(/\u27f3|\u22ef/g, '').trim();
      if (t) out.push('## ' + t);
    }
    const src = card.querySelector('.src');
    if (src && src.textContent.trim()) {
      out.push('');
      out.push('> ' + src.textContent.trim().replace(/\n+/g, ' '));
    }
    const body = card.querySelector('.body');
    if (body) {
      const kids = Array.prototype.slice.call(body.children);
      kids.forEach(el => {
        const cls = el.className || '';
        if (cls.indexOf('gap') >= 0) { out.push(''); return; }
        if (cls.indexOf('sec') >= 0) {
          out.push('');
          out.push(el.textContent.trim());
          return;
        }
        if (cls.indexOf('term') >= 0) {
          // 术语行：英文 + 译名 + 解释，来源标记放到行尾
          const en = el.querySelector('.en');
          const zh = el.querySelector('.zh');
          const badge = el.querySelector('.badge');
          let line = '- ' + ((en && en.textContent) || '').trim();
          if (zh && zh.textContent.trim()) line += ' ' + zh.textContent.trim();
          if (badge && badge.textContent.trim()) line += '　`' + badge.textContent.trim() + '`';
          out.push(line);
          return;
        }
        const t = el.textContent.trim();
        if (t) out.push(t);
      });
    }
    const stat = card.querySelector('.srcstat');
    if (stat && stat.textContent.trim()) {
      out.push('');
      out.push('*' + stat.textContent.trim() + '*');
    }
    return out.join('\n').replace(/\n{3,}/g, '\n\n').trim();
  }

  return { add, loading, fill, fail, clear, all, cardToMarkdown,
           onTermCorrected: null, regenerate: null };
})();

/* ---------------------------------------------------------------------------
 *  接线：把五个模块连起来（这里是唯一知道"谁调谁"的地方）
 * ------------------------------------------------------------------------- */
const App = (() => {
  const $ = id => document.getElementById(id);

  // 安全绑定：某个元素在特定路径下不存在时，跳过它而不是让整个初始化崩掉。
  //  这样即使扩展模式替换了部分 DOM，其余功能仍然可用。
  function on(id, evt, fn) {
    const el = $(id);
    if (!el) { console.warn('[reader] 缺少元素 #' + id + '，跳过绑定 ' + evt); return null; }
    el.addEventListener(evt, fn);
    return el;
  }

  // ------------------------------------------------------------------
  //  新手引导（模块层级）
  //
  //  为什么放在这里而不是 bindUI 里面：
  //    initInner 也要调用 checkOnboard()。写在 bindUI 里的话，
  //    两个平级函数互相看不到 —— 实测报 "checkOnboard is not defined"，
  //    而 initInner 一抛异常，后面全部不执行，界面就停在"粘贴文本"那一屏。
  // ------------------------------------------------------------------
  // ------------------------------------------------------------------
  //  新手引导
  //
  //  默认后端是浏览器内置模型。没开实验室开关的用户第一次按空格
  //  只会看到一句"没有内置模型接口"，然后没有下文 ——
  //  普通人到这一步就卸载了。所以主动把两条路摆出来。
  // ------------------------------------------------------------------
  const ob = document.getElementById('onboard');
  function hideOnboard() { if (ob) ob.classList.remove('on'); }

  // 判断当前后端到底能不能用，返回给引导条用的文案。
  //
  //  早先只判断"内置模型"，于是引导条只在那一种情况下出现。
  //  现在按【当前后端的实际可用性】判断：
  //    · 用户选了云端却忘了填 key  -> 说清楚要填什么、去哪申请
  //    · 内置模型没开实验室功能    -> 教怎么开
  //    · 都就绪                    -> 隐藏
  //  这既是真功能，也顺带让引导条【可以按需触发】——
  //  切换到任意云端后端并清空 key，它就出现；切回去，它就消失。
  //  （用户反馈"一个人不好测新手引导"，这是解法之一。）
  async function backendStatus() {
    // 【必须走 Explainer.getProvider()】
    //  cfg 是 Explainer 模块内部的变量（let cfg = ... 在那边），
    //  App 模块看不到它 —— 早先这里直接写 cfg，第一行就 ReferenceError。
    //  这类"两个 IIFE 互相看不到"的问题静态检查看不出来，只能靠这条注释提醒。
    const c = Explainer.getProvider();
    if (c.provider === 'builtin') {
      let info = null;
      try { info = await Explainer.builtinInfo(); } catch (e) { info = { api: null }; }
      if (info && info.api) {
        const st = String(info.state || '');
        if (st === 'available') return { ok: true };
        // downloadable / downloading：能用，但得先下模型。
        //  这两种【单独处理】，不混进下面的 unavailable ——
        //  因为对策完全不同：
        //    unavailable  -> 开关没开或硬件不够，下载也没用
        //    downloadable -> 只需要下载，给个明确的下载入口就好
        //  早先这两种都当成"可用"直接放行，于是用户第一次按空格会
        //  静静地等很久（在下载几百 MB），分不清是在下载还是卡死了。
        if (st === 'downloadable' || st === 'downloading') {
          return {
            ok: false,
            title: '内置模型还没下载到本机。',
            detail: st === 'downloading'
              ? '正在下载，需要等一会儿。'
              : '首次使用需要下载模型文件（几百 MB 到 2GB，一次性），之后完全离线运行。',
            how: '点下面的【开始下载】。下载期间可以继续读文章，不影响高亮和翻句。',
            useCfg: false,
            download: true,
          };
        }
      }
      return {
        ok: false,
        title: '当前后端是「浏览器内置模型」，但这个浏览器没有把它打开。',
        detail: info && info.api
          ? '内置模型接口存在，但当前状态是：unavailable —— ' +
            '说明功能开关没生效（或硬件不满足要求），下载也解决不了。'
          : '需要 Edge 或 Chrome 138 以上，并且手动打开实验室开关。',
        how: '① 地址栏输入 <code>edge://flags</code>（Chrome 用 <code>chrome://flags</code>）<br>' +
             '② 搜索 <code>Prompt API for on-device language model</code>，设为 <b>Enabled</b><br>' +
             '③ <b>完全退出浏览器再启动</b> —— 这条最容易漏：' +
             '关掉窗口不算，Edge 常驻后台，要用「退出」或任务管理器确认它真的关了<br>' +
             '④ 回到这里点【重新检测】<br>' +
             '<span style="color:#a99b78">另外：这个开关是<b>按浏览器配置存的</b>，' +
             '换一个配置（比如新建的用户）要重新开一次。</span>',
        useCfg: true,
      };
    }

    const p = Explainer.providerMeta(c.provider);
    if (p.kind === 'cloud' && !String(c.key || '').trim()) {
      return {
        ok: false,
        title: '当前后端是「' + p.label + '」，但还没有填 API key。',
        detail: '填上 key 就能用了。key 只存在你自己浏览器里，不会上传。',
        how: (p.keyUrl ? '申请地址：<code>' + p.keyUrl + '</code><br>' : '') +
             '填好后点【保存】，这条提示会自动消失。',
        useCfg: true,
      };
    }
    if (c.provider === 'ollama' && !String(c.base || '').trim()) {
      return {
        ok: false,
        title: '当前后端是「本地 Ollama」，但还没有填服务地址。',
        detail: '默认地址是 http://localhost:11434。',
        how: '确认 Ollama 已在运行，再在下面填上地址。',
        useCfg: true,
      };
    }
    if (c.provider === 'custom' && (!String(c.base || '').trim())) {
      return {
        ok: false,
        title: '当前后端是「自定义」，但还没有填 Base URL。',
        detail: '需要填一个 OpenAI 兼容的接口地址。',
        how: '形如 <code>https://your-host/v1/chat/completions</code>。',
        useCfg: true,
      };
    }
    return { ok: true };
  }

  // 按当前后端状态刷新引导条。
  //  title/detail 按具体原因填，两个按钮的显示也跟着变 ——
  //  选了云端没填 key 的时候，"怎么开启内置模型"是答非所问。
  async function checkOnboard() {
    if (!ob) return;
    let st2 = null;
    try {
      st2 = await backendStatus();
    } catch (e) {
      // 检测本身出错时【不能当成"可用"】——
      //  那样引导条永远不显示，用户只看到讲解失败，还以为扩展坏了。
      //  把错误摆出来，至少能定位。
      console.warn('[reader] 后端检测失败：', e);
      st2 = {
        ok: false,
        title: '没法确认当前后端能不能用（检测本身出错了）。',
        detail: String((e && e.message) || e),
        how: '这通常意味着扩展有 bug，而不是你没配好。可以把这条信息反馈一下。',
        useCfg: true,
      };
    }
    if (st2 && st2.ok) { hideOnboard(); return; }
    if (!st2) { hideOnboard(); return; }
    const st = st2;

    const tEl = document.getElementById('obTitle');
    const dEl = document.getElementById('obDetail');
    if (tEl) tEl.innerHTML = st.title || '还不能讲解';
    if (dEl) dEl.innerHTML = st.detail || '';
    ob.__how = st.how || '';
    // 已经有 key 的后端不该出现"换成云端后端"
    const bCfg = document.getElementById('obCfg');
    if (bCfg) bCfg.style.display = st.useCfg ? '' : 'none';
    // 只有"模型还没下载"时才显示下载按钮 —— 开关没开时下载也没用
    const bDl = document.getElementById('obDl');
    if (bDl) {
      bDl.style.display = st.download ? '' : 'none';
      bDl.disabled = false;
      bDl.textContent = '开始下载';
    }
    ob.classList.add('on');
  }

  // 手动触发内置模型下载。
  //  为什么值得单独做：下载由 create() 触发，而首次 create() 要等
  //  几百 MB 到 2GB 下完才 resolve。如果只能靠"按空格"触发，
  //  用户会看着卡片转很久，分不清是在下载还是卡死了。
  on('obDl', 'click', async () => {
    const bDl = document.getElementById('obDl');
    const dEl = document.getElementById('obDetail');
    if (bDl) { bDl.disabled = true; bDl.textContent = '正在下载…'; }
    try {
      await Explainer.prepareBuiltin((pct) => {
        if (dEl) dEl.textContent = '正在下载模型：' + pct + '%（可以继续读文章，不影响高亮）';
        if (bDl) bDl.textContent = pct + '%';
      });
      if (dEl) dEl.textContent = '模型已就绪。';
      if (typeof msg === 'function') msg('内置模型已下载完成');
      await checkOnboard();
    } catch (e) {
      if (bDl) { bDl.disabled = false; bDl.textContent = '重试下载'; }
      if (dEl) dEl.textContent = '下载失败：' + ((e && e.message) || e);
      console.warn('[reader] 内置模型下载失败：', e);
    }
  });

  on('obCfg', 'click', () => {
    const c = document.getElementById('cfg');
    if (c) c.classList.add('on');
  });

  on('obHow', 'click', () => {
    const det = document.getElementById('obDetail');
    if (!det || !ob) return;
    det.innerHTML = ob.__how || '把当前后端的配置补全即可。';
  });

  on('obRetry', 'click', async () => {
    // 【通过导出的接口复位】
    //  早先这里直接写 `builtinState = 'unknown';` —— 而 builtinState 是
    //  Explainer 模块内部的变量，App 看不到它。
    //  非严格模式下这不会报错（会创建一个隐式全局），所以一直没被发现；
    //  但后果是【Explainer 里的缓存根本没被清掉】，
    //  "重新检测"按钮点了等于没点。
    Explainer.resetBuiltinState();
    await checkOnboard();
    if (ob && !ob.classList.contains('on')) msg('后端可以用了');
    else msg('还是不可用 —— 也可以换成别的后端', true);
  });

  function bindUI() {
    on('btnLoad', 'click', () => {
      const ie3 = $('input');
      if (ie3) ie3.value = SAMPLE;
      start();
    });
    on('btnStart', 'click', start);

    // ---- 打开本地文件（浏览器原生文件选择器，不需要任何权限）----
    on('btnFile', 'click', () => $('file').click());
    on('file', 'change', async ev => {
      const f = ev.target.files && ev.target.files[0];
      if (!f) return;
      msg('读取中…');
      try {
        const raw = await f.text();
        const isHTML = /\.html?$/i.test(f.name) || /<html|<body|<article/i.test(raw.slice(0, 400));
        const text = isHTML ? TextSource.fromHTML(raw) : raw;
        if (!text.trim()) { msg('这个文件里没提取到文字', true); return; }
        const ie2 = $('input');
        if (ie2) ie2.value = text;
        msg('已读取 ' + f.name + '（' + text.length + ' 字）');
        start();
      } catch (e) {
        msg('读取失败: ' + e.message, true);
      }
    });

    // ---- 抓取网址 ----
    on('btnUrl', 'click', fetchUrl);
    on('url', 'keydown', ev => {
      if (ev.key === 'Enter') { ev.preventDefault(); fetchUrl(); }
    });
    on('btnPlay', 'click', () => {
      Reader.toggle();
      // 暂停意味着"这一段读完了"，把学到的速度落盘
      if (!Reader.isPlaying()) Reader.flushPace();
    });
    on('btnMode', 'click', () => {
      const m = Reader.getMode() === 'auto' ? 'manual' : 'auto';
      Reader.setMode(m);
      const b = $('btnMode');
      if (b) {
        b.textContent = m === 'auto' ? '自动模式' : '手动模式';
        b.classList.toggle('on', m === 'manual');
      }
      msg(m === 'manual'
        ? '已切到手动模式：按 → 翻句，停留时长会反映真实阅读'
        : '已切到自动模式：系统按句长推进（此时只有退回/求助等操作信号有效）', false);
      updateStateHud();
    });
    on('btnNext', 'click', () => Reader.next());
    on('btnPrev', 'click', () => Reader.prev());
    on('btnRemeasure', 'click', () => {
      // 重新测速：清掉记住的速度 + 清掉学习窗口，从头观察。
      //
      //  注意这里【不能】调 setSpeed() —— 它会调 notePace() 把当前值立刻存回去，
      //  等于"清除"完马上又写入（下次打开会显示"上次记住的"而不是"默认值"）。
      //  滑块只做显示同步即可。
      Reader.resetPace();
      Trigger.resetLearn();
      const sp = $('speed'), lab = $('speedVal');
      if (sp) sp.value = Reader.getSpeed();
      if (lab) lab.textContent = Reader.getSpeed().toFixed(1);
      msg('已清除记住的速度。接下来按你的实际阅读重新测定，读十几句就稳定了', false);
      updateStateHud();
    });

    on('btnKnow', 'click', () => {
      const i = Reader.getCur();
      if (i >= 0) { Reader.markKnown(i); Reader.next(); }
    });
    on('speed', 'input', e => {
      const v = parseFloat(e.target.value);
      $('speedVal').textContent = v.toFixed(1);
      Reader.setSpeed(v);
    });
    on('btnClear', 'click', () => SidePanel.clear());

    on('btnSide', 'click', e => {
      $('right').classList.toggle('hide');
      e.target.classList.toggle('on', !$('right').classList.contains('hide'));
    });
    on('btnExport', 'click', exportCSV);

    // ---- API 设置 ----
    // ------------------------------------------------------------------
    //  API 设置界面
    //
    //  之前这里有个明显缺口：**API 从来没被验证过**。
    //  填了 key 也不知道对不对、模型名对不对、网络通不通 ——
    //  只有真的按空格求助才发现报错，而且错误淹没在讲解卡片里。
    //  所以加了「测试连接」：点一下就知道通不通、多快、错在哪。
    // ------------------------------------------------------------------

    // 下拉项从 Explainer 的注册表生成，避免两处维护同一份名单
    function renderProviderOptions() {
      const sel = $('cfgProvider');
      if (!sel) return;
      const keep = sel.value;
      sel.innerHTML = '';
      Object.keys(Explainer.PROVIDERS).forEach(k => {
        const o = document.createElement('option');
        o.value = k;
        o.textContent = Explainer.PROVIDERS[k].label;
        sel.appendChild(o);
      });
      if (keep) sel.value = keep;
    }

    // 切换后端时：更新说明、模型候选、placeholder、是否需要 key
    function syncProviderUI(autoFillModel) {
      const sel = $('cfgProvider');
      if (!sel) return;
      const key = sel.value;
      const p = Explainer.providerMeta(key);
      const note = $('cfgNote');
      if (note) {
        let t = p.note || '';
        if (p.keyUrl) t += (t ? '　' : '') + '获取 key：' + p.keyUrl;
        note.textContent = t;
      }
      const kf = $('cfgKeyReq');
      const kh = $('cfgKeyHelp');
      const needsKey = (p.kind === 'cloud' && key !== 'ollama');
      if (kf) kf.textContent = (p.kind === 'builtin') ? '（这个后端不需要）'
                            : needsKey ? '（必填）' : '（随便填）';
      if (kh) {
        if (p.kind === 'builtin') kh.textContent = '选内置模型不需要 key，也不用联网。';
        else if (key === 'ollama') kh.textContent = 'Ollama 不校验 key，留空即可。';
        else kh.textContent = '只保存在本机浏览器（localStorage），不会上传到任何服务器。';
      }
      // 模型候选
      const dl = $('cfgModelList');
      if (dl) {
        dl.innerHTML = '';
        (p.models || []).forEach(m => {
          const o = document.createElement('option');
          o.value = m;
          dl.appendChild(o);
        });
      }
      const mi = $('cfgModel');
      if (mi) mi.placeholder = p.model ? ('留空则用 ' + p.model) : '留空则用默认';
      if (autoFillModel && mi && p.model && !mi.value.trim()) mi.value = p.model;
      const bi = $('cfgBase');
      if (bi) bi.disabled = (key !== 'custom');
    }

    // ---- 浮层模式 ----
    //  在浮层里运行时（?overlay=1），界面占了页面右侧，必须给一个关闭入口。
    //  关闭不能直接删节点（宿主在页面里、本页只是个 iframe），要走消息。
    const IS_OVERLAY = /[?&]overlay=1/.test(location.search);

    function closeOverlay() {
      if (!hasExt()) { msg('当前不在扩展里，无法关闭浮层', true); return; }
      chrome.runtime.sendMessage({ type: 'closeOverlay' }, (resp) => {
        const err = chrome.runtime.lastError;
        if (err) msg('关闭失败：' + err.message, true);
        else if (resp && resp.ok === false) msg('关闭失败：' + (resp.error || '未知'), true);
      });
    }

    if (IS_OVERLAY) {
      const cb = $('btnCloseOverlay');
      if (cb) cb.style.display = '';
      on('btnCloseOverlay', 'click', closeOverlay);
    }

    renderProviderOptions();

    on('btnCfg', 'click', () => {
      const c = Explainer.getProvider();
      $('cfgProvider').value = c.provider || 'builtin';
      $('cfgKey').value = c.key || '';
      $('cfgModel').value = c.model || '';
      $('cfgBase').value = c.base || '';
      $('cfgMsg').textContent = '';
      const ta = $('cfgTerms');
      if (ta) ta.value = Explainer.getUserTermsText();
      syncProviderUI(false);
      $('cfg').classList.add('on');
    });

    on('cfgProvider', 'change', () => {
      // 换后端时把模型名清掉，避免把上一个后端的模型名带过来
      const mi = $('cfgModel');
      if (mi) mi.value = '';
      $('cfgMsg').textContent = '';
      syncProviderUI(true);
    });

    on('btnCfgClose', 'click', () => $('cfg').classList.remove('on'));

    on('btnCfgTest', 'click', async () => {
      const m = $('cfgMsg');
      const b = $('btnCfgTest');
      // 用界面上的当前值测试（不要求先保存，否则改完要先点保存很别扭）
      Explainer.setProvider({
        provider: $('cfgProvider').value,
        key: $('cfgKey').value.trim(),
        model: $('cfgModel').value.trim(),
        base: $('cfgBase').value.trim(),
      });
      if (b) { b.disabled = true; b.textContent = '测试中…'; }
      if (m) { m.style.color = 'var(--dim)'; m.textContent = '正在请求…'; }
      let lastPct = -1;
      try {
        const r = await Explainer.test((pct, ev) => {
          if (pct === lastPct || !m) return;
          lastPct = pct;
          const mb = (ev && typeof ev.total === 'number' && ev.total > 0)
            ? ('　' + (ev.loaded * ev.total / 1048576).toFixed(0) + ' / ' +
               (ev.total / 1048576).toFixed(0) + ' MB')
            : '';
          m.style.color = 'var(--accent)';
          m.textContent = '正在下载内置模型 ' + pct + '%' + mb +
                          '（一次性，之后不再下载；下载期间请勿关闭此面板）';
        });
        if (m) {
          m.style.color = r.ok ? '#4ade80' : (r.pending ? 'var(--accent)' : '#f87171');
          m.textContent = (r.ok ? '✓ ' : (r.pending ? '… ' : '✗ ')) + r.msg;
        }
      } catch (e) {
        if (m) { m.style.color = '#f87171'; m.textContent = '✗ ' + ((e && e.message) || e); }
      } finally {
        if (b) { b.disabled = false; b.textContent = '测试连接'; }
      }
    });

    on('btnCfgDiag', 'click', async () => {
      const m = $('cfgMsg');
      const b = $('btnCfgDiag');
      if (b) { b.disabled = true; b.textContent = '检测中…'; }
      if (m) { m.style.color = 'var(--dim)'; m.textContent = '正在逐个检测（每个最多 6 秒）…'; }
      try {
        const rows = await Explainer.diagnose();
        // 结果用列表显示，带原因和建议 —— 只给一句"不可用"没法处理
        const esc = (t) => String(t).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
        let html = '<div style="margin-top:4px">';
        rows.forEach(r => {
          const mark = r.status === 'ok' ? '\u2713' : (r.status === 'warn' ? '\u2026' : '\u2717');
          const col = r.status === 'ok' ? '#4ade80' : (r.status === 'warn' ? 'var(--accent)' : '#f87171');
          html += '<div style="margin:0 0 6px;line-height:1.5">' +
                  '<span style="color:' + col + '">' + mark + '</span> <b>' + esc(r.name) + '</b><br>' +
                  '<span style="color:var(--dim);font-size:12px">' + esc(r.detail) + '</span>' +
                  (r.hint ? '<br><span style="color:var(--accent);font-size:12px">→ ' + esc(r.hint) + '</span>' : '') +
                  '</div>';
        });
        html += '</div>';
        if (m) { m.style.color = ''; m.innerHTML = html; }
      } catch (e) {
        if (m) { m.style.color = '#f87171'; m.textContent = '检测失败：' + ((e && e.message) || e); }
      } finally {
        if (b) { b.disabled = false; b.textContent = '检测可用后端'; }
      }
    });

    on('btnCfgSave', 'click', () => {
      const c = {
        provider: $('cfgProvider').value,
        key: $('cfgKey').value.trim(),
        model: $('cfgModel').value.trim(),
        base: $('cfgBase').value.trim(),
      };
      Explainer.setProvider(c);
      const ta2 = $('cfgTerms');
      if (ta2) Explainer.setUserTerms(ta2.value);
      Explainer.clearCache();          // 换后端后旧缓存失效
      try { localStorage.setItem('rf_cfg', JSON.stringify(c)); }
      catch (e) {
        // 隐私模式或存储满时会失败。不影响本次使用，只影响"下次记住"。
        console.warn('[reader] 配置保存失败（仅影响下次自动载入）:', e && e.message);
      }
      const m = $('cfgMsg');
      if (m) {
        m.style.color = '#4ade80';
        m.textContent = '已保存（仅存本机）';
        setTimeout(() => { if (m.textContent === '已保存（仅存本机）') m.textContent = ''; }, 1600);
      }
    });

    // 保存后：刷新"后端状态"那一行，并同步引导条。
    //  这样用户在设置里改完后端（或清空 key）能立刻看到后果，
    //  不用关掉面板、按空格、才发现不对。
    async function refreshBackendStatus() {
      const el2 = document.getElementById('cfgStatus');
      if (!el2) return;
      let st = null;
      try {
        st = await backendStatus();
      } catch (e) {
        st = { ok: false, title: '检测出错：' + ((e && e.message) || e) };
      }
      if (st && st.ok) {
        el2.innerHTML = '<span style="color:#4ade80">可以用</span>';
      } else {
        el2.innerHTML = '<span style="color:#f87171">还不行</span>' +
                        '<span style="color:var(--dim)">　' +
                        String(st.title || '').replace(/<[^>]*>/g, '') + '</span>';
      }
      checkOnboard();
    }
    on('btnCfgSave', 'click', () => {
      setTimeout(refreshBackendStatus, 60);
    });
    on('btnCfgClose', 'click', () => {
      setTimeout(refreshBackendStatus, 60);
    });

    // ---- 键位 ----
    document.addEventListener('keydown', ev => {
      const tag = (ev.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      // M / N：人工标注这句"确实难" / "没问题"，作为评估推断层的真值。
      //  为什么要单独的键：空格既是"求助"又是系统信号，混在一起就没法评估了。
      // 0：清除记住的阅读速度，下次重新学
      if (ev.key === '0') {
        Reader.resetPace();
        setSpeed(Reader.getSpeed());
        msg('已清除记住的阅读速度，将重新学习', false);
        return;
      }

      if (ev.key === 'm' || ev.key === 'M') {
        const i = Reader.getCur();
        if (i >= 0) {
          Reader.setTruth(i, 1);
          msg('已标注第 ' + (i + 1) + ' 句：确实难（真值）', false);
        }
        return;
      }
      if (ev.key === 'n' || ev.key === 'N') {
        const i = Reader.getCur();
        if (i >= 0) {
          Reader.setTruth(i, 0);
          msg('已标注第 ' + (i + 1) + ' 句：没问题（真值）', false);
        }
        return;
      }

      if (ev.key === ' ') {
        ev.preventDefault();
        onSpace();
      } else if (ev.key === 'ArrowRight') { ev.preventDefault(); explaining = false; Reader.next(); }
      else if (ev.key === 'ArrowLeft') { ev.preventDefault(); explaining = false; Reader.prev(); }
      // 注意：↑↓ 调"阅读速度"（字/秒），↑ 变慢、↓ 变快
      else if (ev.key === 'ArrowUp' || ev.key === 'ArrowDown') {
        ev.preventDefault();
        const d = (ev.key === 'ArrowUp') ? -0.5 : 0.5;
        setSpeed(Math.min(15, Math.max(2, Reader.getSpeed() + d)));
      } else if (ev.key === 'h' || ev.key === 'H') {
        $('right').classList.toggle('hide');
      }
    });
  }

  function setSpeed(v) {
    const sl = $('speed'), lab = $('speedVal');
    if (sl) sl.value = v;
    if (lab) lab.textContent = v.toFixed(1);
    Reader.setSpeed(v);
    updateStateHud();
  }

  // ------------------------------------------------------------------
  //  推断层接线：评估刚读完的句子 -> 校正基线 -> 按需静默准备
  //
  //  "静默准备"是关键：在后台把讲解生成好、缓存起来，
  //  界面上【什么都不显示】—— 不打扰阅读。
  //  用户按空格时若已准备好，就能【瞬间】看到，而不是等 API 返回。
  // ------------------------------------------------------------------
  let _prevIdx = -1;
  let _curEval = null;          // 当前句的评估结果
  let _lastEval = null;         // 最近一次【已读完句子】的评估结果（状态栏显示它）

  function evaluateSentence(i) {
    const sents = Reader.getSents();
    const stats = Reader.getStats();
    const sent = sents[i];
    const st = stats[i];
    if (!sent || !st) return null;

    const r = Trigger.evaluate(sent, st);
    Trigger.learn(sent, r);                       // 用正常读完的句子校正速度基线
    if (r.state === 'blocked') Trigger.noteBlocked(performance.now());

    const why = Trigger.prepReason(sent, r);
    if (why && !Trigger.prepared.has(sent.text)) silentPrepare(sent, why);
    return r;
  }

  // ------------------------------------------------------------------
  //  提前准备：一边读第 i 句，一边把第 i+1 句的讲解生成好。
  //
  //  为什么不在这里评估"当前句要不要准备"就完事：
  //    · 当前句可能刚进入，它的讲解还没开始生成 -> 现在按空格就要等
  //    · 提前一句就有"整句停留时间"的提前量（几秒到十几秒），
  //      足够 API 返回，用户按空格时才是真的"秒出"
  //
  //  每句只准备一次（Trigger.prepared 里记着），所以总量不变，只是更早。
  // ------------------------------------------------------------------
  function prepareAhead(curIdx) {
    const sents = Reader.getSents();
    const stats = Reader.getStats();
    const cands = [curIdx, curIdx + 1];
    for (let n = 0; n < cands.length; n++) {
      const k = cands[n];
      const sent = sents[k];
      if (!sent) continue;
      if (Trigger.prepared.has(sent.text)) continue;   // 已准备或在途
      const st = stats[k];
      if (!st) continue;
      let why = null;
      try { why = Trigger.prepReason(sent, Trigger.evaluate(sent, st)); } catch (e) { void e; }
      if (why) silentPrepare(sent, why);
    }
  }

  function silentPrepare(sent, reason) {
    if (Trigger.prepared.has(sent.text)) return;
    // 只有"因为你的操作而准备"才值得一提（显示标记）；
    // 纯按句长准备的只是预热缓存，不打扰视觉。
    const showMark = (reason === 'back');
    // 占位标记，避免同一句被重复请求
    Trigger.prepared.set(sent.text, null);
    Explainer.explain(sent, Reader.getSents())
      .then(res => {
        // 存 { text, gloss } 而不是纯字符串 —— 术语来源要跟着一起存，
        //  否则从缓存取出来时"哪条译名有出处"就丢了。
        Trigger.prepared.set(sent.text, res);
        // 用【对象引用】找下标，不要用文字匹配 ——
        //  文字相同但位置不同的句子会把标记打到错的句子上。
        const arr = Reader.getSents();
        let k = arr.indexOf(sent);
        if (k < 0) k = arr.findIndex(x => x.text === sent.text);
        if (k >= 0) Reader.markPrepared(k, showMark);
        // 状态栏要能反映"准备完成"这件事，否则用户看不到它从"准备中"变成"已备好"
        if (typeof updateStateHud === 'function') updateStateHud();
        // 恰好用户正在看这一句，就补上（不弹出，只是填充）
        // 恰好用户正在看这一句，就把内容补进去（不弹窗、只是填充）
        //  这段之前一直是死代码：卡片从没设过 data-t，选择器永远匹配不到。
        let card = null;
        try {
          card = document.querySelector('.card[data-t="' + cssEsc(sent.text) + '"]');
        } catch (e) { void e; }
        if (card) {
          const b = card.querySelector('.body');
          if (b && b.classList.contains('loading')) {
            SidePanel.fill(card, res);
          } else {
            SidePanel.fill(card, res);
          }
        }
      })
      .catch((err) => {
        Trigger.prepared.delete(sent.text);
        console.warn('[reader] 提前准备失败（不影响按需讲解）:', (err && err.message) || err);
        if (typeof updateStateHud === 'function') updateStateHud();
      });
  }

  // 把推断层状态显示在状态栏（只在角落更新，不打断阅读）
  function updateStateHud() {
    const el = $('stat');
    if (!el) return;
    const sents = Reader.getSents();
    const i = Reader.getCur();
    if (i < 0 || !sents[i]) return;
    const stats = Reader.getStats();
    const tn = Trigger.stats();

    // 显示"本句给多少秒 / 大概需要多少秒"，让自适应过程看得见
    const give = Reader.advanceFor(i);
    const u = TextSource.units(sents[i].text);
    const pace = Reader.getPace();
    const unitDesc = (u.cjk && u.words) ? (u.cjk + ' 字 + ' + u.words + ' 词')
                   : u.words ? (u.words + ' 词') : (u.cjk + ' 字');
    const manual = Reader.getMode() === 'manual';
    let txt = '第 ' + (i + 1) + '/' + sents.length + ' 句';
    if (manual) {
      // 手动模式：显示【已经停留】多久，这才是推断层真正用的量
      const el2 = Reader.progress();
      txt += '　本句 ' + unitDesc + '　已停留 ' + (el2 ? el2.elapsed.toFixed(1) : '0.0') + 's';
    } else {
      txt += '　本句 ' + unitDesc + ' / 给 ' + give.toFixed(1) + 's';
    }
    // 倒计时：这是"系统在按句长计算"最直观的证据
    const pr = Reader.progress();
    if (pr) txt += '（还剩 ' + pr.left.toFixed(1) + 's）';
    // 本句若因"退回过"而加过时间，显示出来（让"退回只影响这一句"看得见）
    const ex = Reader.extraOf(i);
    if (ex > 0.05) txt += '【本句+' + ex.toFixed(1) + 's】';
    const pi = Reader.paceInfo();
    const ts2 = Trigger.stats();
    if (ts2.bootstrapping) {
      txt += '　（正在建立基线 ' + ts2.window + '/' + Trigger.RULE.MIN_SPEED_SAMPLES + '）';
    }
    const srcTag = pi.from === 'saved' ? '上次记住的'
                 : pi.from === 'learned' ? '本次学习' : '默认值';
    const langTag = pi.lang === 'zh' ? '中文' : pi.lang === 'en' ? '英文' : '混排';
    txt += '　速度 ' + pi.cps.toFixed(1) + ' 单位/秒（' + langTag + '·' + srcTag + '）';

    // ------------------------------------------------------------------
    //  显示"上一句"的判定，而不是当前句。
    //
    //  现场反馈："感觉不出来" —— 因为状态栏显示的是当前句，
    //  而当前句刚进入，停留时长必然是 0、ratio 恒为 0.00，永远显示"略读"。
    //  有意义的判定只存在于【已经读完的那一句】上。
    //
    //  同时给出本句的实时停留（秒），这样"读得越久数字越大"是看得见的。
    // ------------------------------------------------------------------
    const prev = _lastEval;
    if (prev) {
      const mark = prev.state === 'blocked' ? '受阻'
                 : prev.state === 'skipped' ? '略读' : '正常';
      txt += '　上一句 ' + mark + ' ' + (prev.ratio !== undefined ? prev.ratio.toFixed(2) + '×' : '');
      if (prev.aux && prev.aux.length) txt += '（' + prev.aux.join('，') + '）';
    }

    // 让判定依据可见：本句是否属于"会被提前准备"的那类，依据是什么。
    //
    // 这里修过一个 bug：原先是空 catch 包住的，而里面用错了变量名
    // （写成 st，实际是 stats），于是每帧抛 ReferenceError 又被静默吞掉，
    // 界面上什么都不显示 —— 用户反馈"没显示啊"。
    // 教训：**空 catch 会把错误变成沉默**。至少要在控制台留一行。
    {
      const sti = stats[i] || {};
      const reason = Trigger.prepReason(sents[i], Trigger.evaluate(sents[i], sti));
      const obs = Trigger.stats().prepObserved;
      // 关键：这里必须查【真实状态】，不能只看 prepReason。
      //   之前只看 prepReason 就显示"已提前准备"，而那时其实还没开始生成 ——
      //   状态栏在撒谎，用户按空格发现并没有变快，就是这个原因。
      const v0 = Trigger.prepared.get(sents[i].text);
      const ready = !!(v0 && typeof v0 === 'object' && v0.text);
      const readyLegacy = typeof v0 === 'string' && v0.length > 0;
      const pending = Trigger.prepared.has(sents[i].text) && !ready;
      if (obs < Trigger.RULE.MIN_PREP_OBS) {
        txt += '　（观察句长 ' + obs + '/' + Trigger.RULE.MIN_PREP_OBS + '）';
      } else if (ready || readyLegacy) {
        txt += (reason === 'back') ? '　【已备好·你退回过】' : '　【已备好·长句】';
      } else if (pending) {
        txt += '　【正在准备讲解…】';
      } else if (reason) {
        txt += '　【准备中·排队】';
      }
    }

    let backs = 0;
    Object.keys(stats).forEach(k => { backs += (stats[k].backs || 0); });
    if (backs) txt += '　累计退回 ' + backs + ' 次';
    if (tn.prepared) txt += '　已备 ' + tn.prepared;
    el.textContent = txt;
  }

  // 自动展开：30 秒内受阻 3 次以上就把侧栏打开（内部带冷却）
  // 定时刷新状态栏 —— 倒计时必须持续更新，否则看不出系统在计算。
  //  只在播放时刷新，暂停时不浪费。
  setInterval(() => {
    if (Reader.isPlaying && Reader.isPlaying()) updateStateHud();
  }, 100);

  // ------------------------------------------------------------------
  //  强制落盘的三个时机。为什么需要它们：
  //    现场问题"速度测完再重打开插件，速度和保存前不一致" ——
  //    原因是只按样本数（每 10 个）存盘，最后几个样本算出来的值丢了。
  //    现在改成按时间节流（最多 2 秒一次）再加上这几个强制时机，
  //    保证"你看到的速度"就是"下次读到的速度"。
  // ------------------------------------------------------------------
  window.addEventListener('beforeunload', () => {
    try { Reader.flushPace(); } catch (e) { void e; }
  });
  // 面板被隐藏/切走（侧栏关闭、切换标签页）时也该落盘
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      try { Reader.flushPace(); } catch (e) { void e; }
    }
  });
  // 注：这里没有"关闭"按钮 —— 浮层的关闭按钮在 content.js 的模板里，
  //     那个文件有自己的界面实现。本文件的三种落盘时机已够用：
  //     暂停、页面隐藏、beforeunload。

  function checkAutoReveal() {
    if (!Trigger.shouldAutoReveal(performance.now())) return;
    const right = $('right');
    if (right && right.classList.contains('hide')) {
      right.classList.remove('hide');
      const btn = $('btnSide');
      if (btn) btn.classList.add('on');
    }
  }

  function cssEsc(t) {
    return String(t).replace(/["\\]/g, '\\$&').slice(0, 80);
  }

  // 空格：第一次 = 暂停 + 讲解当前句；第二次 = 继续，并从下一句往下读。
  //
  //  现场反馈："这个完了再按空格应直接继续下一句，现在这个有问题"。
  //  早先的实现只做了前一半（暂停 + 讲解），再按空格还是停在同一句，
  //  于是每讲完一句就得手动按 → 才走得下去。这里补上"继续"那一半。
  let explaining = false;

  async function onSpace() {
    if (!Reader.getSents().length) return;

    if (explaining) {
      // 第二次：结束讲解状态，跳到下一句并恢复播放
      explaining = false;
      Reader.next();          // next() 内部会重置计时
      Reader.start();
      return;
    }

    const i = Reader.getCur();
    if (i < 0) return;
    explaining = true;
    Reader.pause();
    const sent = Reader.getSents()[i];
    const sents = Reader.getSents();
    const v = Reader.getStats()[i] || {};

    const decision = Trigger.shouldExplain(sent, Reader.getStats(), 'manual');
    if (!decision.yes) return;

    Reader.markAsked(i);          // 给这句加"已求助"标记（波浪下划线）

    // 已经静默准备好就直接用 —— 用户感觉是"秒出"
    const cached = Trigger.prepared.get(sent.text);
    if (cached && (cached.text || typeof cached === 'string')) {
      SidePanel.add(sent, cached);
      _events.push({ idx: sent.idx + 1, text: sent.text, at: Date.now(),
                     cause: 'manual-cached', dwell: v.dwell || 0, visits: v.visits || 0 });
      return;
    }

    // 手动求助：明确的用户信号，准备后也打标记（复用已有的 asked 标记）
    const card = SidePanel.loading(sent);
    try {
      const res = await Explainer.explain(sent, sents);
      SidePanel.fill(card, res);
      // 记录一次"求助"事件，供后续分析触发准确率
      _events.push({
        idx: sent.idx + 1, text: sent.text, at: Date.now(),
        cause: decision.reason, dwell: v.dwell || 0, visits: v.visits || 0,
      });
    } catch (e) {
      SidePanel.fail(card, e.message || String(e));
      // 失败也要保留"已进入讲解状态"，这样再按一次空格就能继续往下读，
      // 不会因为一次网络失败把整个阅读卡死。
    }
  }

  const _events = [];

  // ------------------------------------------------------------------
  //  提示函数 —— 必须能容忍"提示元素不存在"
  //
  //  现场崩溃：Cannot set properties of null (setting 'textContent')
  //     at msg (reader_flow.js:672)
  //     at loadFromTab (...)
  //  原因：扩展模式会把 #setup 的内容整体替换掉，于是 #loadMsg 不存在了，
  //  而 loadFromTab 里还在调 msg()，直接崩在赋值上。
  //
  //  这类"某个元素在另一条执行路径下不存在"的问题，靠记住哪条路径很不可靠，
  //  所以这里做成：找不到就自己建一个提示条。
  // ------------------------------------------------------------------
  let msgBar = null;

  function ensureMsgBar() {
    if (msgBar && msgBar.isConnected) return msgBar;
    const host = $('setup') || document.body;
    const bar = document.createElement('div');
    bar.id = 'rf-msgbar';
    bar.style.cssText = 'margin-top:10px;font-size:13px;min-height:1.5em;color:var(--dim)';
    host.appendChild(bar);
    msgBar = bar;
    return bar;
  }

  function msg(t, isErr) {
    // 优先用页面里已有的提示元素（网页版），没有就用动态提示条（扩展模式等）
    let el = $('loadMsg');
    if (!el) el = ensureMsgBar();
    if (!el) return;                       // 极端情况下连 body 都不可用，静默忽略
    el.textContent = t || '';
    el.style.color = isErr ? '#ff6b6b' : 'var(--dim)';
  }

  // 抓取网址正文。
  //  限制说明：浏览器有【同源策略】，普通网页无法读取别的网站的内容。
  //  这里用 fetch 直接取 HTML，能不能成功取决于对方的 CORS 头 ——
  //  很多新闻/博客站允许，很多应用型站点不允许。
  //  真要做到"读任意当前页面"，必须做成浏览器扩展（用 activeTab 权限）。
  async function fetchUrl() {
    const urlEl = $('url');
    let u = urlEl ? String(urlEl.value || '').trim() : '';
    if (!u) { msg('请先填网址', true); return; }
    if (!/^https?:\/\//i.test(u)) u = 'https://' + u;
    msg('抓取中…');
    try {
      // ------------------------------------------------------------------
      //  走【本机服务器】代抓，而不是浏览器直接 fetch。
      //
      //  为什么：浏览器有同源策略，网页里直接 fetch 别的站点会被 CORS 拦掉
      //  （现场报错就是"抓取失败（多半是跨域限制）"）。
      //  服务器端没有同源限制，所以由 tools/serve.js 的 /__fetch 代抓，
      //  页面只请求本机这个接口 —— 这样任意网站都能取到。
      //
      //  代价：必须通过本地服务器打开页面（node tools/serve.js）。
      //  直接双击 HTML 用 file:// 打开时这个接口不存在，会走到下面的降级提示。
      // ------------------------------------------------------------------
      const res = await fetch('/__fetch?url=' + encodeURIComponent(u));
      let html = await res.text();
      if (!res.ok) throw new Error('HTTP ' + res.status);

      // 代理在失败时会回一段 JSON，识别出来给出可读提示
      if (html.trim().startsWith('{')) {
        let j = null;
        try { j = JSON.parse(html); }
      catch (e) {
        // 不是 JSON 就当作正常 HTML，无需告警（探测式解析）
        j = null;
      }
        if (j && j.ok === false) throw new Error(j.error || '抓取失败');
      }
      const text = TextSource.fromHTML(html, u);
      if (!text.trim() || text.trim().length < 40) {
        msg('这个页面没提取到正文（可能是脚本渲染的动态页面，或需要登录）', true);
        return;
      }
      const ie = $('input');
      if (ie) ie.value = text;
      msg('已抓取 ' + text.length + ' 字');
      start();
    } catch (e) {
      // 跨域失败是最常见的情况，给出可操作的提示
      msg('抓取失败：' + (e.message || e) +
          '　→ 请确认页面是通过 node tools/serve.js 打开的（本地服务器代抓），' +
          '或改用 Ctrl+A 复制页面文字粘贴', true);
    }
  }

  // ------------------------------------------------------------------
  //  启动一次阅读会话 —— 所有入口（粘贴 / 本地文件 / 抓网址 / 扩展取正文）
  //  都走这里，避免各写一遍、漏掉判空。
  //
  //  修过的崩溃：Cannot read properties of null (reading 'value')
  //     at start (reader_flow.js:762)
  //  原因是扩展模式下 #input（粘贴框）已被替换掉，而 start() 还在读它的 value。
  //  现在改成：能拿到就用，拿不到就提示用户，绝不崩。
  // ------------------------------------------------------------------
  function beginSession(sents) {
    if (!sents || !sents.length) { msg('没有解析出句子', true); return false; }
    const setup = $('setup');
    if (setup) setup.style.display = 'none';
    const doc = $('doc');
    if (doc) doc.style.display = '';
    Reader.load(sents);
    // 注意顺序：先 load（它会套用记住的速度），再把滑块【同步到】那个速度。
    //  反过来做的话，滑块上的默认值会覆盖掉记住的速度 —— 等于每次都要重学。
    const sp = $('speed');
    if (sp) {
      const cps = Reader.getSpeed();
      sp.value = cps;
      const lab = $('speedVal');
      if (lab) lab.textContent = cps.toFixed(1);
    }
    Reader.start();
    SidePanel.clear();
    _events.length = 0;
    return true;
  }

  function start() {
    const inp = $('input');
    const text = inp ? String(inp.value || '').trim() : '';
    if (!text) {
      msg('请先把要读的文本粘贴到上面的文本框（或用「打开本地文件」「抓取网址」）', true);
      return;
    }
    const src = TextSource.load(text);
    if (!beginSession(src.sents)) return;
    msg('');
  }

  function exportCSV() {
    const sents = Reader.getSents(), stats = Reader.getStats();
    if (!sents.length) { alert('还没有内容'); return; }
    const rows = [['句号', '预测状态', 'ratio', '停留秒', '退回次数', '进入次数',
                   '阅读单位', '真值(1=难 0=没问题 空=未标)', '句子']];
    // 模式记在注释里 —— 自动/手动两种模式的数据不能混在一起分析
    rows.unshift(['# 推进模式=' + Reader.getMode() + '　阅读速度=' +
                  Reader.getSpeed().toFixed(2) + '单位/秒　导出时间=' +
                  new Date().toISOString()]);
    sents.forEach((s, i) => {
      const v = stats[i] || {};
      const u = TextSource.units(s.text);
      rows.push([
        i + 1,
        v.pred || '',
        v.predRatio !== null && v.predRatio !== undefined ? v.predRatio.toFixed(3) : '',
        (v.dwell || 0).toFixed(2),
        v.backs || 0,
        v.visits || 0,
        u.units,
        v.truth === null || v.truth === undefined ? '' : v.truth,
        '"' + String(s.text).replace(/"/g, '""') + '"',
      ]);
    });

    // 求助事件与人工标注也一并导出，便于交叉核对
    const ev = [['', '', '', '', '', '', '', '', ''],
                ['事件', '类型', '句号', '原因/值', '停留秒', '', '', '', '']];
    _events.forEach(e => ev.push(['', '求助', e.idx, e.cause, (e.dwell || 0).toFixed(2), '', '', '', '']));
    sents.forEach((s, i) => {
      const v = stats[i] || {};
      if (v.truth === 1 || v.truth === 0) {
        ev.push(['', '标注', i + 1, v.truth === 1 ? '难' : '没问题', '', '', '', '', '']);
      }
    });

    const csv = rows.concat(ev).map(r => r.join(',')).join('\n');
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const a2 = document.createElement('a');
    a2.href = URL.createObjectURL(blob);
    a2.download = 'reading_flow_' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.csv';
    document.body.appendChild(a2);
    a2.click();
    a2.remove();

    // 顺便算一下当前标注的覆盖情况，提示用户够不够评估
    let labeled = 0, hard = 0;
    sents.forEach((s, i) => {
      const v = stats[i] || {};
      if (v.truth === 1 || v.truth === 0) { labeled++; if (v.truth === 1) hard++; }
    });
    msg('已导出　标注 ' + labeled + '/' + sents.length + ' 句（其中"确实难" ' + hard + ' 句）' +
        (labeled < 20 ? '　建议至少标注 20 句再评估' : '　可以跑 tools/eval_trigger.py 评估了'));
    updateStateHud();
  }

  // ------------------------------------------------------------------
  //  扩展模式：由侧栏以 panel.html?extract=1 打开时启用。
  //  此时不再要求用户粘贴 —— 直接向扩展后台要「当前标签页的正文」。
  //  取正文这件事由 content.js 在目标页面的上下文里完成，所以：
  //    · 没有跨域问题（这是扩展相比普通网页的根本优势）
  //    · 拿到的是渲染后的真实 DOM，动态站点也能取
  //    · 段落结构照原样保留（每段一条记录）
  // ------------------------------------------------------------------
  //  扩展模式的判定有三条依据，任一满足即可：
  //    ① 查询串里带 extract=1（普通 iframe 引用时用）
  //    ② 处于扩展上下文（有 chrome.runtime）—— document.write 写进来的
  //       同源 iframe 没有查询串，但确实在扩展里，靠这条识别
  //    ③ 父窗口是扩展页面（panel.html 的 URL 以 chrome-extension:// 开头）
  // 构建标记：排查时用来确认"跑的是不是刚改的那一版"。
  //  之前吃过亏 —— 不确定用户加载的是新代码还是旧的，来回猜。
  //  每次有实质改动就把它改一下。
  const BUILD = 'ob-2026-10-11a';

  const IS_EXT = true;   // 插件版强制为扩展模式（由 tools/sync_plugin.py 注入）
  // 这里【故意不保留】原来的判定：独立模式在扩展里没有意义，留着只是给判定出错留退化出口。

  // ------------------------------------------------------------------
  //  带超时的 sendMessage
  //
  //  为什么必须加超时：扩展的消息通道在某些情况下会【既不回消息、也不报错】
  //  （服务工作进程刚被唤醒、after 注入失败、receiving end 不存在……）。
  //  原来的写法直接 new Promise 等回调，于是界面永远停在"正在读取当前页面"，
  //  看起来像卡死，实际是在无休止地等一个不会来的响应。
  //  加上超时后，至少能把"到底哪一步没回来"显示给用户。
  // ------------------------------------------------------------------
  // 扩展 API 是否可用。注意：这个页面【必须】运行在扩展上下文里才有 chrome.* ——
  //  早先把 panel.html 直接 iframe 到 http://127.0.0.1:8765/...，
  //  那个 iframe 的来源是本地服务器而非扩展，于是 chrome 是 undefined，
  //  报错是 "Cannot read properties of undefined"（现场 Console 就是这个）。
  //  现在 panel.html 把本文件读回来、写进【同源】的空白 iframe，才有扩展 API。
  function hasExt() {
    return typeof chrome !== 'undefined' && chrome.runtime &&
           typeof chrome.runtime.sendMessage === 'function';
  }

  // ------------------------------------------------------------------
  //  把"当前读到第几句"同步到【网页原文】上高亮。
  //
  //  只在扩展模式下有意义（网页版没有"目标页面"）。
  //  做成 fire-and-forget：高亮失败绝不能影响阅读主流程，
  //  所以不处理返回值、也不阻塞换句。
  // ------------------------------------------------------------------
  let _lastSync = -1;
  //  只传句子文本，不传编号 —— content.js 直接拿文本去原文里找。
  //  编号方案（句子号/段落号/标记值）在交界处反复错位，已弃用。
  let _lastSyncText = '';
  function syncHighlight(text) {
    if (!IS_EXT || !hasExt()) return;
    const t = String(text || '').trim();
    if (!t || t === _lastSyncText) return;
    _lastSyncText = t;
    try {
      chrome.runtime.sendMessage({ type: 'highlight', text: t },
        () => { void chrome.runtime.lastError; });
    } catch (e) { /* 忽略 */ }
  }

  function sendMsg(msg, timeoutMs) {
    return new Promise(resolve => {
      if (!hasExt()) {
        resolve({ ok: false, error: '当前上下文没有扩展 API（页面不是以扩展页面打开的）' });
        return;
      }
      let done = false;
      const t = setTimeout(() => {
        if (done) return;
        done = true;
        resolve({ ok: false, error: '扩展没有在 ' + ((timeoutMs || 8000) / 1000) +
                                    ' 秒内响应（服务工作进程可能未启动或已失效）' });
      }, timeoutMs || 8000);
      try {
        chrome.runtime.sendMessage(msg, resp => {
          if (done) return;
          done = true;
          clearTimeout(t);
          let le = null;
          try { le = chrome.runtime && chrome.runtime.lastError; } catch (e2) { le = null; }
          if (le) { resolve({ ok: false, error: '消息通道错误：' + le.message }); return; }
          resolve(resp || { ok: false, error: '空响应' });
        });
      } catch (e) {
        if (done) return;
        done = true;
        clearTimeout(t);
        resolve({ ok: false, error: '发送失败：' + ((e && e.message) || String(e)) });
      }
    });
  }

  let pickTabId = null;          // 用户在扩展模式下手动选的标签页

  // 从 PDF 取正文。失败要给出可操作的原因（扫描件 / 登录页 / 解析失败）。
  async function loadFromPdf(url, interactive) {
    msg('这是 PDF，正在下载并解析…');
    try {
      const out = await PdfSource.fromUrl(url, (p, total) => {
        if (p === 1 || p % 3 === 0 || p === total) {
          msg('正在解析 PDF 第 ' + p + '/' + total + ' 页…');
        }
      });
      const src = TextSource.fromParas(out.paras || [], out.title);
      if (!src.sents.length) {
        msg('PDF 里没解析出文字 —— 多半是【扫描件/图片型 PDF】，' +
            '这种需要 OCR，扩展做不了。可以试试换一个文字版 PDF。', true);
        return false;
      }
      if (!beginSession(src.sents)) return false;
      // 把"多少段 / 分了多少组"打出来 —— 面板按段落分组显示，这两个数直接反映分段是否正常
      const groups = new Set(src.sents.map(x => x.para)).size;
      console.log('[reader] PDF 读取完成：' + src.sents.length + ' 句，' +
                  (out.paras || []).length + ' 个段落，' + groups + ' 个显示分组');
      msg('已从 PDF 读取 ' + src.sents.length + ' 句　' +
          (out.paras || []).length + ' 段　' + (out.title || '').slice(0, 30));
      return true;
    } catch (e) {
      msg('PDF 解析失败：' + ((e && e.message) || e), true);
      console.warn('[reader] PDF 解析失败:', e);
      return false;
    }
  }

  async function loadFromTab(interactive) {
    if (!hasExt()) {
      msg('当前上下文没有扩展 API —— 请从扩展侧栏打开（而不是直接打开这个网页）', true);
      return false;
    }
    msg('正在读取当前页面…');

    // 先 ping：能区分"后台没起来"和"后台起来了但取正文失败"
    const pong = await sendMsg({ type: 'ping' }, 4000);
    if (!pong || !pong.ok) {
      msg('连不上扩展后台：' + ((pong && pong.error) || '无响应') +
          '　→ 到扩展管理页点一下"重新加载"，并点开"服务工作进程"看日志', true);
      return false;
    }

    // ------------------------------------------------------------------
    //  先问一下当前标签页是什么。
    //  如果是 PDF，DOM 提取必然拿不到正文（PDF 渲染在阅读器自己的文档里），
    //  得走"抓文件 + pdf.js 解析"这条路。
    // ------------------------------------------------------------------
    const info = await sendMsg({ type: 'tabInfo', tabId: pickTabId }, 8000);
    const tabUrl = (info && info.url) || '';
    const looksPdf = /\.pdf(\?|#|$)/i.test(tabUrl) || /\.pdf(\?|#|$)/i.test(location.href);
    if (looksPdf) {
      const okPdf = await loadFromPdf(tabUrl || location.href, interactive);
      if (okPdf) return true;
      // PDF 路径失败就继续试 DOM（有些站点把 PDF 嵌在网页里，DOM 里可能有文字）
    }

    const resp = await sendMsg({ type: 'extract', tabId: pickTabId }, 20000);
    if (!resp || !resp.ok) {
      msg('读取失败：' + ((resp && resp.error) || '未知原因'), true);
      return false;
    }

    const paras = resp.paras || [];
    if (!paras.length) {
      // DOM 里没东西时，如果 URL 像 PDF 就再试一次 PDF 路径
      if (!looksPdf && /\.pdf/i.test(tabUrl)) {
        const okPdf = await loadFromPdf(tabUrl, interactive);
        if (okPdf) return true;
      }
      msg('这个页面没提取到正文（可能是 PDF、应用型页面、需要登录、或正文太短）' +
          (tabUrl ? '　当前地址：' + tabUrl.slice(0, 70) : ''), true);
      return false;
    }
    const src = TextSource.fromParas(paras, resp.title);
    if (!src.sents.length) {
      msg('没有解析出句子', true);
      return false;
    }
    if (!beginSession(src.sents)) return false;
    msg('已读取 ' + src.sents.length + ' 句　' + (resp.title || '').slice(0, 40));
    return true;
  }

  function init() {
    // 整段包一层：init 里有很多步（读配置、绑定界面、注册回调、按模式准备界面），
    //  任何一步抛异常都会让【后面全部不执行】——
    //  界面就停在一半，比如还留着"粘贴文本"那个界面，
    //  而且既不报错也不提示，看起来就是"功能坏了"。
    //  加了兜底之后，真出问题会看到具体报错。
    try {
      initInner();
    } catch (e) {
      console.error('[reader] 启动失败：', e);
      try {
        const st = document.getElementById('setup');
        if (st) {
          st.style.display = '';
          st.innerHTML =
            '<h1 style="color:#f87171">启动失败</h1>' +
            '<p style="color:var(--dim);line-height:1.7">' +
            '界面在初始化时出错了，功能不会正常工作。把这行报错反馈即可定位。</p>' +
            '<pre style="white-space:pre-wrap;background:#1a1f2a;color:#f87171;' +
            'padding:10px;border-radius:6px;font:12px/1.6 Consolas,monospace;' +
            'max-height:320px;overflow:auto">' +
            String((e && e.stack) || e).replace(/[<>&]/g, function (c) {
              return { '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c];
            }).slice(0, 1500) +
            '</pre>';
          const docEl = document.getElementById('doc');
          if (docEl) docEl.style.display = 'none';
        }
      } catch (e2) { void e2; }
    }
  }

  // init 的实际内容（上面那层只负责出错时把它显示出来）
  function initInner() {
    try {
      const saved = JSON.parse(localStorage.getItem('rf_cfg') || 'null');
      if (saved) Explainer.setProvider(saved);
    } catch (e) {
      console.warn("[reader] 读取上次的 API 配置失败，本次用默认设置:", e && e.message);
    }
    bindUI();
    // 手动纠正 -> 推断层的"回看"证据。
    //  这是自动推进模式下唯一有效的信号：退回某句说明那句给的时间不够，
    //  也就是"这句难"。它与你设的速度无关，所以不受自动推进影响。
    // 重新生成：清掉这一句的所有缓存（Explainer 的 + 静默准备的），再跑一次。
    //  内置模型每次结果不一样，所以要让用户能"再摇一次"。
    SidePanel.regenerate = async (sent) => {
      Explainer.clearOne(sent.text);
      Trigger.prepared.delete(sent.text);
      return await Explainer.explain(sent, Reader.getSents());
    };

    // 导出所有讲解为 Markdown。
    //  访谈里提到"笔记散落各处难以收纳"，讲解本身就是读书笔记，得能带走。
    on('btnExportCards', 'click', () => {
      const list = SidePanel.all();
      if (!list.length) { msg('还没有讲解可以导出', true); return; }
      const title = (Reader.getSents()[0] && Reader.getSents()[0].text) || '阅读讲解';
      const lines = ['# 讲解记录', '',
                     '来源：' + (document.title || '') , 
                     '时间：' + new Date().toLocaleString(), ''];
      list.forEach(card => {
        lines.push(SidePanel.cardToMarkdown(card));
        lines.push('');
        lines.push('---');
        lines.push('');
      });
      const blob = new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = '讲解_' + new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-') + '.md';
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      msg('已导出 ' + list.length + ' 条讲解（Markdown）');
    });

    // 订正术语后，把那一句的"预备讲解"作废，下次会重新生成
    SidePanel.onTermCorrected = (sentText) => {
      Trigger.prepared.delete(sentText);
      if (typeof updateStateHud === 'function') updateStateHud();
    };

    // 注入真正的单位计数器（中文按字、英文按词，空格不计）
    Trigger.setUnitCounter(t => TextSource.units(t).units);

    // 注入"学到新速度后做什么" —— 由 App 决定保存策略，Trigger 不关心
    // 保存由 Reader 内部按时间节流，Trigger 只报"学到新速度了"
    Trigger.setPaceSink((cps) => Reader.applyLearnedPace(cps));

    Reader.onCorrection = (kind, idx) => {
      if (kind === 'back' && idx >= 0) {
        const v = Reader.getStats()[idx];
        if (v) {
          // 只记"退回"这件事本身。
          //  【不要】在这里也给 visits 加一 —— go(target,'back') 已经算过一次新访问了，
          //  两处都加会把一次退回记成两次回看，进而误触发"受阻"判定。
          v.backs = (v.backs || 0) + 1;
        }
        _lastEval = {
          state: 'blocked', ratio: undefined,
          aux: ['退回' + (v ? v.backs : 1) + '次'],
          back: true,
        };
        updateStateHud();
      }
    };

    // 每次换句：
    //   ① 把当前句同步到网页原文高亮（扩展模式下生效）
    //   ② 评估【上一句】—— 它已经读完，此时停留时长才完整
    Reader.onAdvance = (sent, reason, idx) => {
      if (sent) {
        syncHighlight(sent.text);
        Trigger.noteSentenceUnits(sent);   // 喂给句长启发式（算本文中位长度）
        prepareAhead(idx);                 // 一边读这句，一边准备下一句
      }
      // 只有【自然读完】才评估刚离开的那句。
      //
      //  修过的错误：按 ← 退回时也会评估刚离开的句子，
      //  于是"我退回去看上一句"被当成"当前句有问题"，
      //  当前句被打上"已提前准备讲解"的绿点标记 —— 用户反馈这是不对的。
      //
      //  语义上：退回说明【上一句】需要更多时间（那个信号由 onCorrection 处理），
      //  而不说明【刚离开的这句】难。它根本没读完，停留时长也不完整。
      const leftNaturally = (reason !== 'back');
      if (leftNaturally && _prevIdx >= 0 && _prevIdx !== idx) {
        _lastEval = evaluateSentence(_prevIdx);
        // 把此刻的判定固化下来，供事后评估用。
        //  必须在【离开这句时】记录，不能事后重算 —— 否则会用上后来才产生的信息
        //  （比如后面又退回了几次），评估就不公平了。
        if (_lastEval) Reader.setPred(_prevIdx, _lastEval.state, _lastEval.ratio);
      }
      _prevIdx = idx;
      updateStateHud();
      checkAutoReveal();
    };

    // 每次开始阅读都重新判断一次后端可用性（用户可能刚配置好）。
    //  这里【不 await】—— 它只是界面提示，不该阻塞启动流程；
    //  而且这块代码不在 async 函数里，await 会直接语法错误。
    checkOnboard().catch(function (e) { console.warn('[reader] 引导检查失败：', e); });

    // 工具栏上显示版本号。
    //
    //  为什么【正常时只显示版本号】：
    //    早先这里常显 "扩展模式 · ob-2026-10-10d"，那是开发期的排查工具。
    //    放进商店截图里，一串 "ob-2026-10-10d" 看起来像没做完的东西 ——
    //    已发布的扩展应该显示版本号。
    //
    //  但排查能力不能丢，所以改成【只在异常时报警】：
    //    · 正常（扩展模式）      -> v1.0.0        （安静、专业）
    //    · 异常（独立模式）      -> 橙色"独立模式"  （一眼看见不对）
    //    这正是我们要的效果：正常时闭嘴，出问题时喊出来。
    //    完整构建标记仍在 console 和打包输出里，开发时照样能对。
    try {
      const tag = document.getElementById('modeTag');
      if (tag) {
        if (IS_EXT) {
          tag.textContent = 'v1.0.0';
          tag.style.color = 'var(--dim)';
          tag.style.borderColor = 'var(--line)';
          tag.title = '按句读 v1.0.0' + '（构建 ' + BUILD + '）';
        } else {
          tag.textContent = '独立模式 · ' + BUILD;
          tag.style.color = '#f5a623';
          tag.style.borderColor = 'rgba(245,166,35,.4)';
          tag.title = '当前显示的是网页版，不是浏览器扩展。' +
                      '如果在侧栏里看到这个，说明扩展的判断出了问题。';
        }
      }
    } catch (e) { void e; }
    console.log('[reader] 按句读 v1.0.0　构建标记 ' + BUILD +
                '　模式 ' + (IS_EXT ? '扩展' : '独立'));

    // 独立模式下把判定依据画出来。
    //  独立模式只该出现在"直接用浏览器打开 demo/reader_flow.html"时；
    //  如果它出现在侧栏里，就说明 IS_EXT 判错了 ——
    //  而侧栏的 DevTools 很难打开，所以把依据直接摆在界面上，
    //  截图就能定位。
    if (!IS_EXT) {
      try {
        const hasRt = (typeof chrome !== 'undefined') &&
                      !!(chrome.runtime && chrome.runtime.id);
        const info = document.createElement('div');
        info.style.cssText = 'margin-top:18px;padding:8px 10px;border-radius:6px;' +
          'background:#1a1f2a;color:#9aa0a6;font:11.5px/1.7 Consolas,monospace;' +
          'word-break:break-all';
        info.textContent = '独立模式 · ' + BUILD +
          '\nprotocol = ' + location.protocol +
          '\nsearch   = ' + (location.search || '(空)') +
          '\nchrome.runtime = ' + (hasRt ? '有' : '无') +
          '\ninIframe = ' + (window.top !== window.self) +
          '\nreferrer = ' + (document.referrer || '(空)');
        const st = document.getElementById('setup');
        if (st) st.appendChild(info);
        console.log('[reader] 独立模式判定依据：', {
          build: BUILD, protocol: location.protocol, search: location.search,
          hasRuntime: hasRt, inIframe: window.top !== window.self,
          referrer: document.referrer,
        });
      } catch (e) { void e; }
    }

    // 扩展模式：自动取正文，并隐藏"粘贴/抓取"那套输入界面
    if (IS_EXT) {
      // 页面在扩展源里，但扩展 API 不可用 ——
      //  典型场景：在 edge://extensions 点了"重新加载"，
      //  而这个侧栏页面还是加载之前那一份（上下文已失效）。
      //  这时显示粘贴界面毫无意义（用户在侧栏里没法选页面），
      //  所以直接说清楚该怎么办。
      if (typeof chrome === 'undefined' || !(chrome.runtime && chrome.runtime.id)) {
        document.getElementById('setup').innerHTML =
          '<h1>请重新打开侧栏</h1>' +
          '<p style="color:var(--dim);line-height:1.7">' +
          '扩展刚刚被重新加载过，这个侧栏页面还是旧的那一份，已经连不上扩展了。<br>' +
          '关掉侧栏再点一次工具栏图标即可。</p>';
        return;
      }
      // 扩展模式的启动界面：显示进度 + 可选的标签页选择器。
      //  为什么给选择器：侧栏可能以独立标签页打开，此时"当前标签页"未必是用户
      //  想读的那篇文章；让用户能明确指定目标页，比猜更可靠。
      document.getElementById('setup').innerHTML =
        '<h1 id="extTitle">正在读取当前页面…</h1>' +
        '<p id="extmsg" style="color:var(--dim);min-height:1.6em"></p>' +
        '<div class="row">' +
        '  <button id="btnRe">重新读取</button>' +
        '  <button id="btnPick">选择标签页</button>' +
        '</div>' +
        '<div class="row" id="pickRow" style="display:none">' +
        '  <select id="tabSel" style="flex:1;background:#12151c;color:var(--fg);' +
        '          border:1px solid var(--line);border-radius:6px;padding:7px 9px;font-size:13px">' +
        '  </select>' +
        '  <button id="btnReadSel">读取这个</button>' +
        '</div>';
      const re = document.getElementById('btnRe');
      if (re) re.addEventListener('click', () => loadFromTab(true));

      const pick = document.getElementById('btnPick');
      if (pick) pick.addEventListener('click', async () => {
        const row = document.getElementById('pickRow');
        const sel = document.getElementById('tabSel');
        row.style.display = '';
        sel.innerHTML = '<option>读取中…</option>';
        const r = await sendMsg({ type: 'listTabs' }, 8000);
        if (!r || !r.ok) {
          sel.innerHTML = '<option>' + ((r && r.error) || '取标签页列表失败') + '</option>';
          return;
        }
        sel.innerHTML = '';
        r.tabs.forEach(t => {
          const o = document.createElement('option');
          o.value = t.id;
          o.textContent = (t.active ? '● ' : '　') + (t.title || '').slice(0, 46) +
                          '　—　' + (t.url || '').replace(/^https?:\/\//, '').slice(0, 34);
          sel.appendChild(o);
        });
        if (!r.tabs.length) sel.innerHTML = '<option>没有可读取的网页标签</option>';
      });

      const readSel = document.getElementById('btnReadSel');
      if (readSel) readSel.addEventListener('click', () => {
        const sel = document.getElementById('tabSel');
        pickTabId = sel.value ? Number(sel.value) : null;
        loadFromTab(true);
      });

      loadFromTab(false);
    }
  }

  const SAMPLE =
`这是用于验证自适应阅读辅助的一段说明文字。请按平时的习惯阅读，不需要刻意放慢或加快。

系统的目标是判断你是否在某一句上"处理受阻"，也就是读起来觉得卡住、需要反复看才能理解。判断依据不是"你看了多久"，因为看得久也可能只是这句内容本来就多。真正的依据是"是否反复回到同一句"。

为了让系统能工作，需要先建立一个基线：你读完一句平均需要多少时间。系统会在你读前几句时估计这个值，之后每一句都拿自己的实际用时与这个基线比较。

读不懂的时候按空格，系统会把这一句连同上下文一起送去讲解，结果显示在右侧。你可以继续按空格往下读，也可以点侧栏卡片里的原文跳回那一句重读。`;

  return { init };
})();

App.init();