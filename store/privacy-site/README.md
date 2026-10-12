# 隐私政策站点 —— 三步发布

这个目录就是要上传的内容。**只有 `index.html` 是必须的**，其余是说明。

---

## 为什么要单独建一个仓库

商店表单里的「隐私政策网址」是必填项，而且**必须能公开访问**。
最省事、免费、稳定的做法是 GitHub Pages。

**不要**把政策放在扩展的更新日志里、也不要只给一个 md 文件链接 ——
审核要的是一个能直接打开的网页。

---

## 三步

### ① 建一个公开仓库

名字随意，建议 `sentence-reader-privacy`（不要和扩展代码仓库混在一起）。

```
GitHub → New repository → 名字填 sentence-reader-privacy
→ 选 Public → Create
```

### ② 把这个目录的内容传上去

**要注意：`index.html` 必须在仓库根目录**（不是套一层文件夹），
否则 Pages 打开的是目录列表而不是政策页面。

命令行做法：

```bash
cd store/privacy-site
git init
git add index.html .nojekyll
git commit -m "privacy policy"
git branch -M main
git remote add origin https://github.com/<你的用户名>/sentence-reader-privacy.git
git push -u origin main
```

**或者**在 GitHub 网页上用 `Add file → Upload files`，把 `index.html`
和 `.nojekyll` 拖进去即可（`.nojekyll` 是隐藏文件，上传时注意别漏）。

### ③ 打开 Pages

```
仓库 → Settings → Pages
→ Source 选 "Deploy from a branch"
→ Branch 选 main，目录选 / (root)
→ Save
```

等一两分钟，访问地址是：

```
https://<你的用户名>.github.io/sentence-reader-privacy/
```

**把这个网址填进商店表单的「隐私政策网址」。**

---

## 上传前替换占位符

`index.html` 里的联系方式是占位符，要换成真实的：

```
__CONTACT_URL__    联系方式链接（比如你的 GitHub 仓库 issues 页面）
__CONTACT_TEXT__   链接上显示的文字
```

替换办法（在项目根目录跑）：

```bash
python tools/prepare_privacy_site.py --repo https://github.com/<你的用户名>/<扩展仓库名>
```

它会：
- 把两个占位符换成该仓库的 issues 页面
- 顺手检查还有没有残留的 `__` 占位符
- 打印发布地址

**也可以用 `--email 你的邮箱` 换成邮箱链接。**

---

## 检查清单

上传前：

- [ ] 用浏览器直接打开 `store/privacy-site/index.html`，内容显示正常
- [ ] 没有任何 `__PLACEHOLDER__` 残留
- [ ] 联系方式是真的能用的
- [ ] 内容和扩展的实际行为一致（对照 `plugin/manifest.json` 里的权限）

上传后：

- [ ] 用**无痕窗口**打开那个网址（确认不需要登录就能看）
- [ ] 手机上也打开看看（审核可能用窄屏）
- [ ] 把这个网址填进商店表单

---

## 关于 .nojekyll

GitHub Pages 默认用 Jekyll 处理，会忽略以下划线开头的文件。
这个页面用不到，但放一个 `.nojekyll` 可以避免以后加资源时踩坑，**成本为零**。

---

## 如果不想用 GitHub

任何静态托管都行，要求只有两条：

```
① 公开可访问，不需要登录
② 内容就是这个政策
```

其它选择：Cloudflare Pages、Netlify、Vercel、对象存储的静态网站功能。
**但不要用会插广告或要求登录的免费空间** —— 审核看到广告页会直接拒。
