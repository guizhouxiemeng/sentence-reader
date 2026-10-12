# 提交时的最后一页：credentials 与审核备注

> ### 这个文件要留着，别删
>
> 表单上写着：*Certification notes must be provided with every submission,
> even if similar information was provided previously.*
>
> **以后每次更新版本都要重新贴一遍。** 删了就得重写。

**这一页容易卡在最后一步** —— 因为核心功能（讲解）在审核环境里可能跑不起来，
而"核心功能无法验证"是最常见的被拒理由之一。

---

## 问题一：Does a tester need credentials...?

### 选 **Yes**

**实际情况是这样的：**

```
扩展本身      不需要任何账号、不需要登录 ✓
原文高亮      不需要后端，装上就能用 ✓
讲解功能      需要【内置模型开启】或【一个 API key】
              而内置模型依赖一个 flag —— 我们控制不了测试环境有没有开
```

**选 No 的风险**：审核环境如果没开 flag，他们按空格只看到引导条，
**核心功能一次都没跑起来** → 可能被判"无法验证核心功能"。

**选 Yes 并给一个免费 key**，就绕开了这个不确定性。

---

## 问题二：Notes for certification（<2000 字符）

**下面这段直接复制。把 `<在这里粘一个智谱的 key>` 换成真的 key。**

```
Sentence Reader highlights a web page or PDF sentence by sentence, and when the reader presses Space on a sentence they do not understand, it shows an explanation of that single sentence in the side panel.

HOW TO TEST (about 2 minutes)

1. Open any English article, for example:
   https://cacm.acm.org/practice/real-time-computer-vision-with-opencv/
2. Click the extension icon. A reading panel opens on the right side of the page.
3. Press Space. An explanation card appears.

BACKEND — please read this part

The default backend is the browser's built-in model (Edge 138+ with the experimental "Prompt API for on-device language model" flag). If that flag is enabled in your environment, no credentials are needed at all and no content leaves the device.

If the flag is NOT enabled, the side panel shows a guidance banner instead of an error. In that case, to exercise the explanation feature, please switch to the free cloud backend:

  Open API 设置 (the settings button in the toolbar)
  Backend: 智谱 GLM  (the second entry in the dropdown)
  API key: <在这里粘一个智谱的 key>
  Model:   glm-4-flash        (free tier — this costs nothing)

Then press Space again. You can also click 测试连接 (test connection) to confirm that the key works before pressing Space.

Everything else — sentence highlighting, next/previous sentence, PDF support, term source labels, exporting explanations as Markdown, the reading progress bar — works without any backend at all.

OTHER NOTES

- The extension has no server of its own and collects no personal data.
- It declares no content_scripts: it never runs on any page until the user clicks the icon.
- Privacy policy: https://guizhouxiemeng.github.io/sentence-reader-privacy/
```

---

## 关于那个 key：用智谱 GLM-4-Flash

**为什么选它**：

```
· glm-4-flash 历来有免费额度 —— 审核测试不会产生费用
· 申请只要注册一个账号，不用实名认证
· 我们已经内置了这个后端（下拉列表第二项）
```

**申请地址**：https://bigmodel.cn/usercenter/proj-mgmt/apikeys

**注意事项**：

```
· 用一个【专门的】key，不要用你平时开发那个
  —— 它会被写进审核表单，虽然不是公开的，但也没必要共用
· 审核通过后可以把它删掉/换掉
· 万一额度被刷完，重新生成一个即可，不影响已上架的扩展
```

---

## 这个 Notes 为什么这么写

**① 先给"两分钟怎么测"** —— 审核员时间有限，步骤越短越可能真的去试。

**② 把 flag 的事说在前面** —— 与其让他自己撞上引导条然后困惑，
不如直接告诉他"可能看到引导条，那不是坏了，那是设计"。

**③ 主动说明"其余功能不需要后端"** —— 万一 key 出问题，
至少让他们知道高亮、翻句、PDF、导出这些都验证得了。

**④ 给一个具体文章链接** —— 省掉他找素材的时间。**这一步比看起来有用。**

---

## 填完这一页，就可以提交了

```
✅ 包（桌面 sentence-reader-1.0.0.zip）
✅ 文案（listing.md / 两个 txt）
✅ 权限理由（edge-privacy-form.md 六栏）
✅ 隐私政策 URL
✅ 数据使用勾选（Website content）
✅ 商店 logo + 两张宣传图
✅ 截图 1280×800
✅ 分类 Productivity
✅ 搜索词 7 个
✅ 这一页：Yes + Notes
```
