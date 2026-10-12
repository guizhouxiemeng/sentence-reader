# 商店上架材料

> **状态：已上架（1.0.0）**
> 直链 <https://microsoftedge.microsoft.com/addons/detail/npbppgdpikakaldohlglkccjfomfkoob>　Store ID `0RDCKFW W37BV`

这个目录里的东西**不进扩展包**，是提交到商店时填表用的。

```
listing.md            商店文案（名称 / 简介 / 详细描述 / 分类 / 搜索词）
permissions.md        每条权限的理由（审核表单会逐条问，必须写得具体）
privacy.md            隐私政策的纯文本版（商店表单如果要"粘贴文本"就用它）
privacy-site/         隐私政策的网页版 —— 【要发布到 GitHub Pages 的那份】
    index.html          政策页面本身
    .nojekyll           让 Pages 跳过 Jekyll（空文件，有名字就行）
    README.md           三步发布说明
checklist.md          提交前逐项核对
```

**只保留一份网页版**（`privacy-site/index.html`）——
早先 `privacy.html` 和它内容重复，改一处漏一处，挂到网上的可能是旧版本。

---

## 上架前需要你补的两处

材料里有 `<你的仓库地址>` 这样的占位符，提交前替换掉：

```bash
# 在 store/ 目录里搜索占位符
grep -rn "<你的" store/
```

| 占位符 | 换成什么 | 用在哪 |
|---|---|---|
| `<你的仓库地址>` | 你的 GitHub 仓库地址 | 隐私政策里的联系方式 |
| 政策 URL | **https://guizhouxiemeng.github.io/sentence-reader-privacy/**（已发布 ✅） | 商店表单的「隐私政策网址」必填项 |

**隐私政策必须有一个可访问的 URL。** 最省事的做法：

1. 新建一个公开仓库（例如 `sentence-reader-privacy`）
2. 把 `privacy-site/index.html` 和 `privacy-site/.nojekyll` 传到仓库**根目录**
   （不要套一层文件夹，否则打开的是目录列表）
3. 在仓库设置里开启 **GitHub Pages**（Settings → Pages → Deploy from a branch）
4. 得到的网址形如 `https://<用户名>.github.io/sentence-reader-privacy/`

详细步骤见 `privacy-site/README.md`。
发布前记得跑一次占位符替换：

```bash
python tools/prepare_privacy_site.py --repo https://github.com/<你>/<仓库>
```

它会检查权限说明与 manifest 是否一致、有没有残留占位符，并打印发布地址。

---

## 提交步骤概览

详细的逐项核对见 `checklist.md`。总体是：

```
① 打包（node tools/package.js）—— 会在桌面生成 zip
② 到 Edge 加载项 / Chrome 应用商店注册开发者账号（Edge 免费，Chrome 一次性 $5）
③ 新建扩展条目，上传 zip
④ 填商店文案（listing.md）、权限理由（permissions.md）、隐私政策 URL
⑤ 上传至少 1 张截图（1280×800 或 640×400）
⑥ 提交审核
```

---

## 关于审核的两个已知风险

**① `host_permissions` 申请了全部网站**

一个"阅读辅助"要访问所有网站，审核会重点看。`permissions.md` 里写了理由，
提交时**务必把那一段填进表单**，不要留空 —— 留空是最常见的被拒原因。

如果被要求收窄：技术上可以改成 `activeTab` + 用户点击时才注入，
代价是"记住上次读的文章"这类功能会受限。**先按现在的提交，被要求改再改。**

**② 依赖实验性浏览器功能**

默认后端用的是 Edge/Chrome 的内置模型（Prompt API），微软自己的说明写着
"Exploratory APIs are designed for local prototyping only"。

所以：
- **不要把"内置模型"写成唯一卖点** —— 商店文案里把它描述成"其中一种后端"
- 用户必须能走通"换成云端后端"这条路，`新手引导`就是干这个的
- 审核员如果没开那个 flag，会看到引导条而不是报错 —— 这是加分项，可以主动在审核备注里说明

**审核备注建议这样写：**

> 本扩展默认使用浏览器内置模型（Prompt API）。若审核环境未开启该功能，
> 扩展会在侧栏显示一条引导，提示用户开启 flag 或改用其它后端，不会报错退出。
> 需要复现讲解功能时，可在「API 设置」里填入任意 OpenAI 兼容后端的地址与 key。
