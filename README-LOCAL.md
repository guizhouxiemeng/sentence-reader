# Gaze Collector · 本地运行说明

## 一句话

**必须用本地服务器打开**（不能双击 html 文件）：

```
node tools/serve.js
```

然后浏览器访问：

| 页面 | 地址 |
|---|---|
| 采集器 | **http://127.0.0.1:8765/collector.html** |
| 交互 Demo | **http://127.0.0.1:8765/demo** |

设置页会显示资源状态：看到 **"本地资源就绪（离线可用）"** 就说明一切正常，此后**完全不需要代理**。

> ⚠ **为什么不能双击打开**：`file://` 页面的 origin 是 `null`，浏览器会拦截动态
> `import()` 与 `fetch()`。表现为"MediaPipe 加载失败"，极易被误判成网络/CDN 问题。
> 两个页面现在都会在检测到 `file://` 时直接弹出提示，而不是让你去猜。
> （这个坑在项目早期真实发生过：第一版采集器报"脚本没加载成功"，当时的归因是
> "CDN 被墙"，实际原因是本地文件协议。后来即使把依赖全部本地化，`file://` 依然不行。）

---

## 为什么要改成这样

采集器原本直接从 jsdelivr 和 Google 加载 MediaPipe。你打开时它报了"脚本没加载成功"，排查过程如下：

| 发现 | 说明 |
|---|---|
| 系统代理挂在 `127.0.0.1:7897` | 你能正常上网靠的是它 |
| 但 `www.google.com:443` 不通、国内源通 | 代理对海外流量没生效 |
| curl 报 `schannel: SEC_E_NO_CREDENTIALS` | 沙箱撤销了凭据存储访问，**沙箱内无法建立任何 TLS 连接** |
| Node 的 https 却返回 200 | Node 用自带 OpenSSL，不走 schannel，所以可用 |

结论：不是你的网络坏了，是**依赖了一个你没在用的 CDN**。所以直接把全部资源本地化，永久解决。

## vendor/ 里是什么（共 21.9 MB，已就位）

```
vendor/vision_bundle.js                       134 KB   MediaPipe 任务库（ESM）
vendor/face_landmarker.task                   3.76 MB  人脸 478 关键点模型
vendor/wasm/vision_wasm_internal.js           207 KB
vendor/wasm/vision_wasm_internal.wasm         9.42 MB  SIMD 加速版
vendor/wasm/vision_wasm_nosimd_internal.js    207 KB
vendor/wasm/vision_wasm_nosimd_internal.wasm  9.28 MB  无 SIMD 兜底版
```

两个坑，已避开：

1. **npm 包里没有 `vision_bundle.js`**，只有 ESM 格式的 `vision_bundle.mjs`（下载时改名为 `.js`）。
   因为是纯 ESM 且**没有任何全局变量**，只能用 `await import()` 加载，`<script src>` 那套永远拿不到 `FaceLandmarker`。
   已验证包内导出名正确：`export{... hh as FaceLandmarker, Co as FilesetResolver ...}`。
2. **该包零相对路径依赖**（不含 `import(` / `require(` / 硬编码 `.wasm`），所以扒下来放本地不会断链。

## 重新获取资源

```
node tools/gaze-research/fetch-vendor.js
```

只用 Node 内置 `https`，不依赖代理（npmmirror 直连已验证可下）。脚本会自动跳过已存在的文件。

## 加载优先级

采集器**本地优先，CDN 兜底**：

1. 先 `import('vendor/vision_bundle.js')`，成功就走 `vendor/wasm` + `vendor/face_landmarker.task`
2. 失败才回退 jsdelivr / Google（此时需要代理）
3. 两边都失败时，"开始采集"会给出具体原因，而不是笼统的"多半是被墙"

---

## 已验证 / 未验证

**已验证**

- 静态服务器全部资源返回 200，MIME 正确（`.wasm` → `application/wasm`，这是 `WebAssembly.instantiateStreaming` 的硬要求）
- 目录穿越被拒（`/../` → 404）
- 两段内联 JS 通过 `node --check`
- vendor 文件大小与 npm 包内条目逐一吻合
- 模型文件 3758596 字节，与官方模型一致

**未验证：真实浏览器里的运行**。沙箱禁止启动 Edge（crashpad 被拒），所以页面加载必须由你确认。

## 打开后请确认这 4 件事

1. 设置页显示 **"本地资源就绪（离线可用）"**
2. 点"开始采集"后，**摄像头权限弹窗**出现并允许
3. 3 秒倒计时后白点出现，右下角预览里**红点（虹膜）跟着白点动**
4. 结束后"平均误差 / 视口对角线"有数字

## 常见故障对照

| 现象 | 原因 | 处理 |
|---|---|---|
| 资源状态显示"已回退 CDN" | `vendor/` 不完整 | `node tools/gaze-research/fetch-vendor.js` |
| 报 CORS / 跨源 | 直接双击了 html（`file://`） | 用 `node tools/serve.js` |
| 拿不到摄像头 | 非 localhost 的安全上下文 | 必须用 `http://127.0.0.1:8765` |
| 预览里红点不动 | 光照不足 / 脸太小 / 眯眼 | 靠近摄像头、补正面光 |
| 误差特别大 | 屏幕宽高填错 | 全屏后重新读一次宽高 |

## 工具区（可删）

| 文件 | 用途 |
|---|---|
| `tools/serve.js` | 零依赖静态服务器，**必须保留** |
| `tools/gaze-research/fetch-vendor.js` | 重新下载 vendor 资源，建议保留 |
| `tools/gaze-research/smoke.js` | 对服务器做一次 HTTP 冒烟测试 |
| `tools/gaze-research/probe-browser.js` | 无头浏览器验证脚本（本沙箱内跑不起来，本地可用） |
| `tools/gaze-research/inspect-tgz.js` | 查看 npm 包内条目，排障用 |
| `tools/probe.js` | 最早的连通性探测脚本，已无用，可删 |
