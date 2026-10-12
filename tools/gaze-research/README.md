# tools/gaze-research —— 早期眼动研究阶段的脚本

这些是项目**前期**（视线连续光标方向）用过的分析脚本与实验脚本，
**不是当前工作流的一部分**。当前工作流在上一层 `tools/`。

## 这些脚本对应哪些结论

它们的产出已经写进 `README.md` 与 `FINDINGS-trigger.md`：

| 脚本 | 对应结论 |
|---|---|
| `eyetrax_accuracy_test.py` | EyeTrax 精度的离线测量（产出 `eyetrax_result.json`） |
| `measure_snr.py`、`signal_check.py` | 眼部图像信噪比 —— **这是否决 appearance 方案的依据** |
| `compare_featuresets.py` | 三套特征的抖动/信噪比对比（相对特征优于绝对特征） |
| `verify-oneeuro.mjs` | 用官方 groundTruth.csv 验证 1€ 滤波（误差 2.45e-5 < 判据 1e-4） |
| `gaze_granularity.py`、`zone_partition_search.py`、`gaze_zone_real.py` | 视线可分辨粒度与分区搜索（水平 1×2 = 80.4%，垂直不可用） |
| `dwell_feasibility.py` | 停留交互的可行性（用已有 4147 帧数据） |
| `compare_jitter.py`、`analyze.py`、`audit_*.py`、`diagnose*.py` | 抖动分析、校准策略的几轮尝试 |
| `ir_eyetracker_feasibility.py`、`ir_prior_art.py`、`prior_art_search.py` | 红外眼动仪与既有方案的调研 |
| `train.py`、`export_model.py`、`interaction.py` | 早期尝试的建模与交互实验 |
| `verify-fusion.mjs`、`verify-map.mjs` | 状态机与映射验证（36/36、7/7） |
| `archive/` | 更早的一次性脚本（33 个） |

## 为什么归档而不是删除

**删掉不会损失结论**（结论在 README 里），保留只是便于日后复核，
成本约 250KB。所以保留，但从日常工作流里移出去 ——
否则在 `tools/` 里找 `verify_all.py` 要先扫过几十个用途不明的文件。

## 如果要重跑

脚本之间**没有相互依赖**，都是独立入口：

```bash
python tools/gaze-research/<name>.py <参数>        # 用法看文件头 docstring
node   tools/gaze-research/<name>.mjs
```

部分脚本需要 `data/` 下的样本数据（眼动帧 CSV、眼部图像目录）。
