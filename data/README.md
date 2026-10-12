# 原始测量数据

这里放的是 [`../RESEARCH.md`](../RESEARCH.md) 里所有数字背后的原始数据。
**没有这批数据，那份文档里的定量结论就无法核对。**

## 文件

| 文件 | 内容 |
|---|---|
| `gaze_p1_frames.csv` | 受试者 p1，一组标定+测量 |
| `gaze_p029379_frames.csv` | 受试者 p029379 |
| `gaze_p411900_frames.csv` | 受试者 p411900（用得最多，多份分析都基于它） |
| `gaze_p463357_frames.csv` | 受试者 p463357 |
| `gaze_p478309_frames.csv` | 受试者 p478309 |
| `gaze_p496980_frames.csv` | 受试者 p496980 |
| `collector.html` | **采集工具本身** —— 采集协议实现在这里，不是文字描述 |
| `data/*.png` | 信号质量与光照条件检查 |
| `run_eyetrax_test.cmd` | 与 EyeTrax（486 维特征）的交叉验证脚本 |
| `eyetrax_result.json` | 该交叉验证的结果 |

## CSV 的列

每行是**一帧**（约 30fps）。关键列：

```
t, trial, phase          时间、试次号、阶段（pre / ...）
tx, ty                   该帧的【目标点】屏幕坐标 —— 这是真值
f_L_h, f_L_v, f_L_h2 …   左眼特征（一阶、二阶）
f_R_h, f_R_v, f_R_h2 …   右眼特征
f_iod, f_earL, f_earR    瞳距、左右眼开合度
f_yaw, f_pitch           头部姿态
irisL_x/y/z, irisR_x/…   虹膜在眼内的位置
```

**误差 = 预测坐标 − (tx, ty)。**
归一化用的屏幕对角线在 `RESEARCH.md`「数据采集协议」一节。

## 怎么复现

从**仓库根目录**运行（脚本按相对路径找 CSV）：

```bash
# 单份分析
python tools/gaze-research/analyze.py gaze_p411900_frames.csv

# 特征集对比（结论"180 维不比 486 维差"来自这个）
python tools/gaze-research/compare_featuresets.py

# 与 EyeTrax 交叉验证
python tools/gaze-research/compare.py
```

> **注意**：这些脚本是从本机绝对路径改过来的，改成了相对路径。
> 如果你在别处运行，先 `cd` 到仓库根目录。

## 没有放进来的东西

| 没发 | 为什么 |
|---|---|
| `gaze_p029379_eyes.zip`（9.8MB，4436 张眼部裁剪图） | 那是喂 MediaPipe 的输入，而 MediaPipe（约 30MB）没进仓库 —— 发了也跑不了。**同时它也是真人眼部图像** |
| `eye_grid.png`、`signal_check_*.png` | **真人眼部图像。** 见下 |
| `gaze_*_headfree.png` 等图 | 由 CSV 生成，跑脚本就能重画，没必要占地方 |

### 关于眼部图像

原始录制里包含受试者的眼部画面，我们**不公开这些图像**。

**这不影响这份研究的可核对性** —— 上面每一条结论都是数字：
误差多少像素、抖动百分之几、误触发率降了多少。
没有一条需要靠"看一眼眼睛照片"来验证，而 CSV 里有全部原始测量值。

换句话说：这些图对验证没有贡献，但它们是一个真人的眼睛。这个交换不划算。

`lighting.png` 保留了 —— 那是亮度与对比度的直方图，不含任何个人内容。

需要原始图像请联系我，但需要说明用途。
