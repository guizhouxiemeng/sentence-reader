# 商店文案

直接复制粘贴到商店表单对应字段。

---

## 名称（name）

```
按句读 · 阅读辅助
```

> 商店对名称有长度限制（Chrome 45 字符以内）。这个名字 9 个字符，安全。
> 英文名用 `Sentence Reader`（已在 `_locales/en` 里配好，随浏览器语言自动切换）。

---

## 简介（summary）

### 长度上限（**硬性，超了会被商店直接拒收**）

| 字段 | Chrome | Edge | 本项目按 |
|---|---|---|---|
| `description`（即简介） | **132** 字符 | 190 字符 | **132** |
| `name` | 45 字符 | 45 字符 | 45 |

**按 132 卡** —— 一份 zip 两个店都能用，不必维护两份文案。

长度按**字符数**算，不是字节数。中文一个字算一个字符，
所以中文的空间比看上去大得多（下面那条 46 字，离 132 还很远）。

> 这条曾经踩过：英文简介写了 **212 字符**，上传后被拒：
> `The translation for field Description in locale en is too long:
> It exceeds maximum size limit of 190 characters.`
> 现在 `node tools/package.js` 会直接打印各语言的字符数，不用等上传才发现。

### 中文（zh_CN，46 / 132）

```
按句高亮网页与 PDF，读不懂按空格就地讲解。术语译名只采用外部查证结果，查不到就如实说明。
```

### 英文（en，129 / 132）

```
Highlights articles and PDFs by sentence. Press Space for an in-place explanation. Terms are externally verified, never invented.
```

> 英文这条只剩 3 个字符余量。要改的话记得跑一次打包自检 ——
> 它会告诉你超没超。

**这两条已经写进 `plugin/_locales/{zh_CN,en}/messages.json`，zip 里带的就是它们，
不用在商店表单里再填一遍。** 这里列出来只是为了方便核对。

---

## 商店表单里的"详细描述"（与上面不同，长度不限）

> 上面两条中，**把"不编造"放进简介是有意的** —— 见文末说明。

---

## 详细描述（description）

**商店列表里要单独填这一栏，而且【分语言】。**
它和 manifest 里那 132 字符的简介是两回事：

```
manifest 的 description  ->  搜索结果里显示的一行（有 132 字符硬上限）
商店的 Description 栏      ->  商店页面上那段长文（上限约 10000，分语言）
```

**两种语言的结构必须一致** —— 审核会对照着看，一边写了一边没写就是 Incomplete。

### 中文（Chinese (China)）

```
读论文时最常见的卡顿，是「每个词都认识，连起来不知道在说什么」。
这一句卡住了，后面的论证就全跟不上了。

这个扩展解决这一件事。

────────────────

■ 它做什么

· 把文章按句切开，逐句高亮 —— 网页和 PDF 都支持
· 读到读不懂的句子，按一下空格
· 就地给出这一句的讲解：主干是什么、术语什么意思、结构难在哪
· 讲解出现在侧栏，原文继续高亮着，不用来回切换

■ 怎么用（键盘）

· 空格 —— 讲解当前这一句（自动带上前后文）
· ← → —— 上一句 / 下一句
· ↑ ↓ —— 调阅读速度（0.5 一档，范围 2~15；↑ 变慢、↓ 变快）
· H —— 显示 / 隐藏讲解侧栏
· 0 —— 清掉记住的阅读速度，下次重新测定

■ 界面上的东西

· 【开始】【暂停】—— 自动推进的控制
· 【自动模式】—— 开着是按你的速度自动推进；关掉就是纯手动，你自己按 → 翻句
· 【重新测速】—— 清掉学到的速度，重新从你的实际阅读里测一遍
   （它会在你读前几句时估计你的速度，之后按这个估计给每句分配时间）
· 【标记已懂】—— 把这句标成已读，之后不再为它提前准备讲解
· 【阅读速度】滑块 —— 2~15 单位/秒。中文按字算、英文按词算，空格和标点不计
· 讲解卡片右上角的 ⟳ —— 重新生成这一句（内置模型每次结果不一样，可以多摇几次）
· 拖动面板左边缘 —— 调面板宽度
· 【导出讲解】—— 把已经看过的讲解全存成一个 Markdown 文件，可直接贴进笔记软件
· 【API 设置】—— 换后端、填 key、维护你自己的术语表（填了就以你的为准）
· 工具栏上的细线 —— 阅读进度，读到哪就是哪

■ 关于速度

不用一开始就调对。系统会一边读一边测，你只要觉得太快或太慢就按 ↑↓ 改，
它会重新学。想从头来过就按 0 或点【重新测速】。

■ 它不做什么（这是重点）

市面上不少 AI 阅读工具会在你还没问的时候，就信心十足地给你一段解释。
问题是：你没法判断那是原文的意思，还是它自己编的。

所以这个扩展在几个地方刻意「少做一点」：

· 术语的译名只采用外部查证的结果（你自己的术语表 > Wikipedia）
  查不到就只给英文原词和意思说明，不会给你编一个中文名
· 它自己写的「某某 = 某某」一律丢弃
  实测中它编出过 "OpenCV = 奥克拉夫视网膜" 这种东西
· 拿不准的时候，允许它写「这句我不确定」
· 每条术语都标出来源：你的术语表 / 外部查证

■ 讲解从哪来（三种后端，自己选）

1. 浏览器内置模型（默认，免费，内容不出本机）
   需要 Edge 或 Chrome 138+，并开启实验室功能。
   没开启的话，侧栏会给出开启步骤，不会只给你一句报错。

2. 本地 Ollama（免费，内容不出本机）

3. 任意 OpenAI 兼容的云端 API（自填 key，速度快、质量高）
   内容会发给你选择的那个服务商，扩展本身不经手。

■ 隐私

不收集任何个人数据，没有自己的服务器。
只有你主动按空格时，那一句正文才会发给你自己配置的服务。
术语查证只发送术语本身，不发送句子。

完整隐私政策：https://guizhouxiemeng.github.io/sentence-reader-privacy/

■ 适合谁

· 需要读英文论文的学生和研究者
· 读中文文献但被术语卡住的人
· 不相信「AI 说什么就是什么」的人

■ 已知限制

· 扫描版 PDF（纯图片）读不了，会明确提示
· 浏览器内置模型能力有限，同一句可以点 ⟳ 重新生成，结果会不一样
· 免费路线依赖浏览器实验性功能，厂商随时可能改动
```

### 英文（English）

```
The most common stall when reading a paper is this: you know every word, but you cannot tell what the sentence is saying. Once that sentence is lost, the rest of the argument is lost with it.

This extension solves that one thing.

LANGUAGE NOTE

Explanations are written in Chinese. This tool is built for Chinese readers working through English papers. It is not an English-language reading assistant — if you are looking for explanations in English, this extension is not for you.

WHAT IT DOES

- Splits the article into sentences and highlights them one at a time — works on web pages and PDFs
- When you hit a sentence you do not understand, press Space
- It explains that single sentence in place: what the main clause is, what the technical terms mean, where the structure is difficult
- The explanation appears in the side panel while the article stays highlighted — no switching back and forth

HOW TO USE (keyboard)

- Space — explain the current sentence (context is included automatically)
- Left / Right — previous / next sentence
- Up / Down — adjust reading speed in 0.5 steps, range 2-15 (Up = slower)
- H — show / hide the explanation panel
- 0 — forget the learned reading speed and measure it again

ON SCREEN

- Start / Pause — controls for automatic advance
- Auto mode — when on, it advances at your measured pace; when off, you turn sentences yourself
- "重新测速" (re-measure) — clears the learned speed and measures it again from your actual reading. While you read the first few sentences it estimates your pace, then allocates time to each sentence from that estimate.
- "标记已懂" (mark as understood) — marks this sentence as read; it will no longer be prepared in advance
- Reading speed slider — 2 to 15 units per second. One unit is one Chinese character or one English word; spaces and punctuation are not counted.
- The refresh icon on a card — regenerate that explanation (the built-in model gives a different result each time, so it is worth trying a few times)
- Drag the panel's left edge — resize the panel
- "导出讲解" (export) — saves everything explained so far as a single Markdown file, ready to paste into a notes app
- "API 设置" (settings) — switch backend, enter a key, keep your own glossary (yours always wins)
- The thin line in the toolbar — reading progress

ABOUT THE SPEED

You do not have to get it right at the start. The extension measures your pace while you read; whenever it feels too fast or too slow, press Up/Down and it re-learns. To start over, press 0 or click "重新测速".

WHAT IT DELIBERATELY DOES NOT DO

Many AI reading tools will confidently hand you an explanation before you even ask. The problem is that you have no way to tell whether that was what the paper meant, or something the model made up.

So this extension deliberately does less in a few places:

- Term translations come only from external sources (your own glossary first, then Wikipedia). If nothing is found, it gives you the original English term and a plain-language description — it will not invent a Chinese name for you.
- Any "term = translation" line the model produces on its own is discarded. In testing it produced things like "OpenCV = 奥克拉夫视网膜", which is not a thing.
- When it is unsure, it is allowed to write "I am not certain about this sentence."
- Every term is labelled with its source: your glossary / external verification.

WHERE THE EXPLANATION COMES FROM (three backends, your choice)

1. Browser built-in model (default; free; nothing leaves your machine)
   Requires Edge or Chrome 138+ with the experimental feature enabled.
   If it is not enabled, the side panel shows you how to turn it on instead of just failing.

2. Local Ollama (free; nothing leaves your machine)

3. Any OpenAI-compatible cloud API (bring your own key; faster and stronger)
   The sentence is sent to the provider you choose. The extension itself never handles it.

PRIVACY

No personal data is collected. There is no server of ours.
Only when you press Space is the current sentence sent to the service you configured yourself.
Term lookups send the term string only — never the sentence.

Full privacy policy: https://guizhouxiemeng.github.io/sentence-reader-privacy/

WHO IT IS FOR

- Students and researchers reading English papers
- Anyone reading Chinese literature who keeps getting stuck on terminology
- Anyone who does not believe "the AI said so, so it must be true"

KNOWN LIMITATIONS

- Scanned PDFs (images only) cannot be read; the extension says so clearly
- The browser built-in model is small; press the refresh button on a card to regenerate, and you will get a different result
- The free path depends on an experimental browser feature, which the vendor may change at any time
```

---

## Extension logo（商店列表图标）

**两种语言都要上传。** 用 `plugin/icons/icon128.png`（128×128）。

Edge 要求这个位置是 128×128 的 PNG。如果以后想换更好看的，
改 `tools/make-icons.js` 里的画法重新生成即可 —— 图标是代码画出来的，不是手工做的。

---


```
读论文时最常见的卡顿，是「每个词都认识，连起来不知道在说什么」。
这一句卡住了，后面的论证就全跟不上了。

这个扩展解决这一件事。

──────────────

■ 它做什么

· 把文章按句切开，逐句高亮 —— 网页和 PDF 都支持
· 读到读不懂的句子，按一下空格
· 就地给出这一句的讲解：主干是什么、术语什么意思、结构难在哪
· 讲解出现在侧栏，原文继续高亮着，不用来回切换

■ 它不做什么

这是重点。

市面上不少 AI 阅读工具会在你还没问的时候，就信心十足地给你一段解释。
问题是：你没法判断那是原文的意思，还是它自己编的。

所以这个扩展在几个地方刻意「少做一点」：

· 术语的译名只采用外部查证的结果（你自己的术语表 > Wikipedia）
  查不到就只给英文原词和意思说明，不会给你编一个中文名
· 它自己写的「某某 = 某某」一律丢弃
  实测中它编出过 "OpenCV = 奥克拉夫视网膜" 这种东西
· 拿不准的时候，允许它写「这句我不确定」
· 每条术语都标出来源：你的术语表 / 外部查证

■ 讲解从哪来（三种后端，自己选）

1. 浏览器内置模型（默认，免费，内容不出本机）
   需要 Edge 或 Chrome 138+，并手动开启实验室功能。
   装上扩展后如果没有开启，侧栏会给出开启步骤。

2. 本地 Ollama（免费，内容不出本机）

3. 任意 OpenAI 兼容的云端 API（自填 key，速度快、质量高）
   内容会发给你选择的那个服务商，扩展本身不经手。

■ 隐私

不收集任何个人数据。没有自己的服务器。
只有你主动按空格时，那一句正文才会发给你自己配置的服务。
术语查证只发送术语本身，不发送句子。

完整隐私政策：https://guizhouxiemeng.github.io/sentence-reader-privacy/

■ 适合谁

· 需要读英文论文的学生和研究者
· 读中文文献但被术语卡住的人
· 不相信「AI 说什么就是什么」的人

■ 已知限制

· 扫描版 PDF（纯图片）读不了，会明确提示
· 浏览器内置模型能力有限，同一句多按几次 ⟳ 重新生成，结果会不一样
· 免费路线依赖浏览器实验性功能，微软随时可能改动
```

---

## 分类

```
Chrome / Edge 分类：生产工具（Productivity）
```

备选：`无障碍（Accessibility）` —— 如果商店允许，这个分类的竞争更小，
但本扩展的主要场景是读论文，还是归到生产工具更准确。

---

## 搜索词 / 关键词

```
阅读 论文 文献 英文 翻译 讲解 高亮 术语 PDF 助手
reading assistant research paper explain highlight terminology
```

---

## 语言

```
主要语言：中文（简体）
`_locales` 里同时提供了 en，英文环境会显示 Sentence Reader
```

### 关于"要不要留英文"（这是个产品判断，不是技术必需）

**技术事实**：删掉 `en` locale 的话，Edge 会回退到 `default_locale`（`zh_CN`），
英文用户看到的是中文列表 —— 他们看不懂，也就不会装。**这本身是诚实的，不是缺陷。**

**保留英文的理由**：挂着 `Incomplete` 可能在审核时被问；而且不少中国用户浏览器是英文的。

**无论留不留，英文描述里必须写清楚"讲解是中文的"** ——
已在上面 `LANGUAGE NOTE` 一节写明。否则英文用户会以为这是给英语读者的工具，
装上才发现输出是中文，那才是误导。

---

## 设计这份文案时的两个判断

**① 把"不编造"放进 132 字符的简介里**

简介那一行是搜索页唯一会显示的文字。多数工具会在这里写"AI 智能讲解"，
但访谈里最强烈的反馈是：

> "AI 幻觉率太高，且不老实地告诉你'我没查到'。"
> "宁愿用一个看起来不太智能，但不会瞎编、会老实说'我不会'的 AI。"

**所以差异点不是"更聪明"，是"更诚实"。** 简介里就该写这个。

**② 主动写出"已知限制"**

听起来像自曝其短，但这类工具最大的问题是**用户不信任**。
主动列出做不到的事（扫描版 PDF、内置模型能力有限），
比让用户自己撞上去然后怀疑"它是不是在糊弄我"要好。

这也是访谈结论的直接应用。
