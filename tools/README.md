# tools/ —— 工具说明

## 目录结构

```
tools/                          当前工作流用到的工具（12 个）
    verify_all.py               交付前一键校验 —— 改完代码先跑这个
    sync_plugin.py              网页版 -> 插件版同步（含内联脚本抽取）
    check_html_modules.py       静态核对跨模块调用 / DOM id / 可疑残留
    check_module_refs.py        跨文件模块引用核对
    eval_trigger.py             用实测 CSV 评估推断层（混淆矩阵 / 阈值扫描）
    test-units.js               阅读单位计数自测（中文按字、英文按词）
    test-trigger.js             推断层判定逻辑自测（8 个场景）
    test-overlay-parse.js       浮层 HTML 解析自测
    textfeat.py                 文本特征 vs 行为信号的区分力对比
    test_combined_signal.py     组合模型的留一交叉验证
    heuristic_value.py          句长启发式的覆盖率与代价核算
    serve.js                    本地服务器（网页版用；插件不需要）

tools/gaze-research/            早期眼动研究阶段的脚本（36 个）
    README.md                   说明这些脚本对应哪些结论

tools/gaze-research/archive/    更早的一次性脚本（33 个）
```

## 版本管理：tools/snap.js

这台机器**没装 git**，所以做了一个针对本项目的小工具，解决一个具体问题：

> 排查"原文高亮突然没了"时发现，**原来能用的 `content.js` 已经被直接覆盖**，
> 既没法对比改动前后、也没法回退，只能靠记忆猜，前后多花了十几轮。

```bash
node tools/snap.js save "改了什么"     # 存一份快照（内容没变就不存）
node tools/snap.js list                # 看所有快照
node tools/snap.js diff                # 对比最近两次，逐行列出改动
node tools/snap.js diff 3 5            # 对比指定两份
node tools/snap.js restore 4           # 回退到某份（回退前会自动存一份当前状态）
node tools/snap.js show 4 plugin/content.js   # 看某份快照里的某个文件
```

**跟踪的文件**：`plugin/`、`demo/`、`tools/`、根目录文档。
**不跟踪**：`vendor/`、`data/`（下载来的依赖与样本，又大又不该改）。

快照存在 `.snapshots/`，当前保留最近若干份。

**用法约定**：每次改动源码之前先 `save` 一次，说明写"准备做什么"。
这样出问题时 `diff` 能立刻告诉我到底动了什么 —— 而不是像上次那样靠猜。

## 常用命令

```bash
# 交付前必跑 —— 会依次做：同步插件 -> 一致性 -> JS 语法 -> Python 语法
#                       -> 三个自测 -> 浮层解析 -> 静态核对
python tools/verify_all.py

# 用实测数据评估推断层
python tools/eval_trigger.py .ghcache/reading_flow_xxx.csv --scan

# 文本特征 vs 行为信号
python tools/textfeat.py
python tools/test_combined_signal.py
python tools/heuristic_value.py

# 本地服务器（看网页版）
node tools/serve.js 8765
```

## 为什么把老脚本分开

早期眼动研究（视线连续光标方向）留下了约 70 个脚本。
它们的**结论已经写进 `README.md` 与 `FINDINGS-trigger.md`**，
脚本本身是复现手段，不是日常工作流的一部分。

混在一起的问题是：**每次要在 `tools/` 里找 `verify_all.py` 都要先扫过几十个
一眼看不出用途的文件**。按用途分开之后，当前工作流只有 12 个文件。

分开时注意过：
- 移动前用「文件名+扩展名」精确匹配检查了文档引用（避免 `calib` 误命中 `audit_calib`）
- 文档里的路径已同步更新（`tools/xxx.py` -> `tools/gaze-research/xxx.py`）
- 移动后重跑了 `verify_all.py`，确认当前工作流不受影响
