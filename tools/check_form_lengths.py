# -*- coding: utf-8 -*-
r'''
量一遍 Edge 表单里六段 justification 的字数，超 1000 的改短。

起因：用户截图显示 Host permission justification 顶到 1000/1000，
      而且被截断在半句话上（"the AI service the user configured them" 后面没了）。

      这比"填得不好"更糟 —— 审核看到的是一句没说完的话。

六栏都是 1000 上限。所以不只改那一栏，全部量一遍。

顺带把这一条记进 store/edge-privacy-form.md：
**填之前先数字数**，别等截断了才发现。
'''
import io
import re
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# ---- 六个字段的文案（Host 那栏已经改短）----
FIELDS = {}

FIELDS['Single purpose'] = """Sentence Reader helps readers understand the sentence they are stuck on, while reading articles or PDFs in the browser.

It does exactly one thing: it splits the main text of the current page into sentences, highlights them one at a time as the reader moves through the article, and, when the reader presses Space on a sentence they do not understand, shows an explanation of that single sentence (its main clause, its technical terms and its structure) in the browser side panel.

The extension does not modify page content, does not inject ads, does not track browsing, and does not collect personal information."""

FIELDS['scripting'] = """Used to inject the sentence-splitting and highlighting script into the tab the user is reading.

The manifest declares no content_scripts, so the extension never runs automatically on any page. Injection happens only after the user clicks the toolbar icon or presses "Reload" in the side panel, and the target is the current tab only."""

FIELDS['tabs'] = """Used for two things:

(1) To check whether the current tab is a readable web page, so the extension can show a clear message on chrome:// pages, extension pages and the new tab page instead of failing silently after injection.

(2) To list candidate tabs in the side panel. The side panel can be opened as its own tab, in which case the "active tab" is not necessarily the article the user wants to read. The panel lists tabs (title and URL only) so the user can pick the right one.

Tab content is not read for either purpose, and no browsing history is recorded."""

FIELDS['activeTab'] = """Grants temporary access to the current page when the user clicks the toolbar icon.

This is the minimal-permission path: even without host permissions, a click on the icon is enough authorisation to process the current page."""

FIELDS['sidePanel'] = """The explanation is displayed in the browser side panel.

This is essential to the single purpose: the reader must be able to see the article and the explanation at the same time. A popup closes as soon as the user clicks elsewhere, and opening a separate tab would require switching back and forth and would lose the reading position. The side panel is the only surface that keeps both visible without covering the article."""

FIELDS['Host permission'] = """The extension works on "the article the user is currently reading", and that article can be on any website: publisher sites, arXiv, course pages, personal blogs. It cannot know in advance which site the user will open, so it must declare all sites.

Declaring is not the same as reading:
- The manifest declares no content_scripts, so it never runs on any page unless the user clicks the toolbar icon.
- Only then does it call chrome.scripting.executeScript, for the current tab only.
- The injected script only locates article text, splits it into sentences and adds highlighting. It does not read forms, cookies, or unrelated DOM.
- The extension has no server of its own.

Outbound requests happen only when the user explicitly asks for an explanation (the current sentence plus a little context goes to the AI service the user configured) or looks up a term (only the term string goes to Wikipedia). With the default built-in model, nothing leaves the device."""

print('=' * 70)
print('Edge 表单 justification 字数（上限 1000）')
print('=' * 70)
over = []
for k, v in FIELDS.items():
    n = len(v)
    flag = '  !! 超了 %d' % (n - 1000) if n > 1000 else ('  （余量 %d）' % (1000 - n))
    print('  %-16s %4d%s' % (k, n, flag))
    if n > 1000:
        over.append(k)

print()
if over:
    print('  超限的：' + '，'.join(over))
else:
    print('  全部在 1000 以内 ✓')

# ---- 把改短后的 Host 那栏写回文档 ----
P = r'D:\projects\gaze-project\store\edge-privacy-form.md'
s = io.open(P, encoding='utf-8').read()
start = s.index('## 6. Host permission justification')
end = s.index('## 7. Are you using remote code?')
new_sec = ('## 6. Host permission justification ★\n\n'
           '**⚠️ 这一栏最关键** —— 申请了全部站点，必须把理由说透，否则直接被拒。\n'
           '**也最容易超长**：上限 1000 字符，填之前先数一下。\n\n'
           '```\n' + FIELDS['Host permission'] + '\n```\n\n'
           '**踩过的坑**：第一版写长了，表单把它截断在半句话上\n'
           '（`...the AI service the user configured them` 后面就没了）。\n'
           '**审核看到一句没说完的话**，比写得简略更糟 ——\n'
           '所以这栏宁可少写两句，也要保证句子完整。\n\n'
           '---\n\n')
s = s[:start] + new_sec + s[end:]
io.open(P, 'w', encoding='utf-8', newline='').write(s)
print()
print('  已把改短后的版本写回 store/edge-privacy-form.md')
