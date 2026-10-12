# Edge 商店「Privacy」页 —— 逐项填法

**这一页是审核最看重的地方**，也是"留空会被拒"的高发区。
下面每一段都可以直接复制粘贴（都是英文，表单是英文的；中文也接受，但英文更稳）。

---

## 1. Single purpose description ★

> 要求：单一、明确、好懂。不要写成一堆功能的清单。

```
Sentence Reader helps readers understand the sentence they are stuck on, while reading articles or PDFs in the browser.

It does exactly one thing: it splits the main text of the current page into sentences, highlights them one at a time as the reader moves through the article, and — when the reader presses Space on a sentence they do not understand — shows an explanation of that single sentence (its main clause, its technical terms and its structure) in the browser side panel.

The extension does not modify page content, does not inject ads, does not track browsing, and does not collect personal information.
```

**为什么不列一堆功能**：这一栏问的是"单一用途"。
列"支持 PDF、支持术语表、支持导出"会被当成多个用途 —— 那些都是**同一件事的不同实现方式**，
所以上面只用一句话概括核心，其余当细节。

---

## 2. scripting justification ★

```
Used to inject the sentence-splitting and highlighting script into the tab the user is reading.

The manifest declares no content_scripts, so the extension never runs automatically on any page. Injection happens only after the user clicks the toolbar icon or presses "Reload" in the side panel, and the target is the current tab only.
```

---

## 3. tabs justification ★

```
Used for two things:

(1) To check whether the current tab is a readable web page, so the extension can show a clear message on chrome:// pages, extension pages and the new tab page instead of failing silently after injection.

(2) To list candidate tabs in the side panel. The side panel can be opened as its own tab, in which case the "active tab" is not necessarily the article the user wants to read. The panel lists tabs (title and URL only) so the user can pick the right one.

Tab content is not read for either purpose, and no browsing history is recorded.
```

---

## 4. activeTab justification ★

```
Grants temporary access to the current page when the user clicks the toolbar icon.

This is the minimal-permission path: even without host permissions, a click on the icon is enough authorisation to process the current page.
```

---

## 5. sidePanel justification ★

```
The explanation is displayed in the browser side panel.

This is essential to the single purpose: the reader must be able to see the article and the explanation at the same time. A popup closes as soon as the user clicks elsewhere, and opening a separate tab would require switching back and forth and would lose the reading position. The side panel is the only surface that keeps both visible without covering the article.
```

---

## 6. Host permission justification ★

**⚠️ 这一栏最关键** —— 申请了全部站点，必须把理由说透，否则直接被拒。
**也最容易超长**：上限 1000 字符，填之前先数一下。

```
The extension works on "the article the user is currently reading", and that article can be on any website: publisher sites, arXiv, course pages, personal blogs. It cannot know in advance which site the user will open, so it must declare all sites.

Declaring is not the same as reading:
- The manifest declares no content_scripts, so it never runs on any page unless the user clicks the toolbar icon.
- Only then does it call chrome.scripting.executeScript, for the current tab only.
- The injected script only locates article text, splits it into sentences and adds highlighting. It does not read forms, cookies, or unrelated DOM.
- The extension has no server of its own.

Outbound requests happen only when the user explicitly asks for an explanation (the current sentence plus a little context goes to the AI service the user configured) or looks up a term (only the term string goes to Wikipedia). With the default built-in model, nothing leaves the device.
```

**踩过的坑**：第一版写长了，表单把它截断在半句话上
（`...the AI service the user configured them` 后面就没了）。
**审核看到一句没说完的话**，比写得简略更糟 ——
所以这栏宁可少写两句，也要保证句子完整。

---

## 7. Are you using remote code? ★

**选 `No, I am not using remote code`** ✅（截图里已经选中了）

**这是对的**，理由：

```
· 所有 JS 都在包里（content.js / background.js / reader_flow.js / panel.js）
· pdf.js 也是打包进去的（vendor/pdf/），不是从 CDN 加载
· manifest 里没有指向外部文件的 <script>
· 没有 eval()、没有 new Function() 去执行外部字符串
· 唯一的外部请求是 fetch 到 AI 服务 / Wikipedia 拿【数据】，
  不是拿【代码】来执行 —— 这不属于 remote code
```

---

## 8. Justification（remote code 下面的那一栏）

**留空** —— 它只在上面选 `Yes` 时才需要填。

---

## 9. Data usage —— ⚠️ 这里需要你做个判断

### 我的建议：勾 **`Website content`**，其余不勾

```
☐ Personally identifiable information    不勾
☐ Health information                     不勾
☐ Financial and payment information      不勾
☐ Authentication information             不勾
☐ Personal communications                不勾
☐ Location                               不勾
☐ Web history                            不勾（不读浏览历史，也不记录）
☐ User activity                          不勾（阅读进度只存在本机）
☑ Website content                        ← 勾这一个
```

### 为什么勾它

表单问的是"你打算从用户那里**收集**什么数据"，而 `Website content` 举的例子就是
**"text, images, sounds, videos, or hyperlinks"** —— 正是我们发送的东西：

```
· 用户按空格求助时，当前那一句【正文】会发给他自己配置的 AI 服务
· 术语查证时，术语【字符串】会发给 Wikipedia
```

**在"勾了会不会吓到用户"和"勾了才和隐私政策一致"之间，我建议选后者。**
理由是：

1. **政策和表单必须一致。** 隐私政策第 3 节已经写明了"内容会离开你的电脑"，
   而表单这里是给审核看的 —— 两边矛盾比什么都糟。
2. **这个项目的立身之本就是"不糊弄"。** 访谈里最强烈的反馈是"用户不信 AI"。
   如果连数据披露都含糊，卖点就站不住了。
3. **不勾的后果可能更严重**：审核发现实际行为和申报不符，那是政策违规，不是退回重填。

### 但这条最终由你决定

**如果你不想勾**，那至少要保证隐私政策里把这件事讲清楚（现在已经讲清楚了）。
**风险和收益都摆在这里，你判断。**

---

## 10. Privacy policy URL ★

```
https://guizhouxiemeng.github.io/sentence-reader-privacy/
```

（已验证 HTTP 200，无痕窗口可访问）

---

## 11. I certify that the following disclosures are true ★

**三条全勾** ✅

```
☑ I do not sell or transfer user data to third parties, outside of the approved use cases
☑ I do not use or transfer user data for purposes that are unrelated to my item's single purpose
☑ I do not use or transfer user data to determine creditworthiness or for lending purposes
```

**三条都是事实**：

```
· 不卖数据，也没有服务器经手
· 唯一的对外传输就是为了【这一个用途】——帮你读懂那一句
· 和信贷无关
```

> 第一条里的 "approved use cases" 包含"为用户提供扩展的核心功能"。
> 我们把句子发给他自己配置的 AI 服务属于这一类，而且是他主动触发的。

---

## 填完自查

- [ ] 六个 justification 栏**都填了**，没有留空
- [ ] remote code 选了 No，下面的 Justification 留空
- [ ] Privacy policy URL 能打开（用无痕窗口试）
- [ ] 三条 certify 都勾了
- [ ] **表单里勾的数据类型，和隐私政策里写的一致**
