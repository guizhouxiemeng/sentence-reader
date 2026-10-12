# -*- coding: utf-8 -*-
r'''
拆仓库 —— 第一步：建研究仓库 publish-gaze/

用户选了方案 A：
    sentence-reader          阅读扩展（已有）
    gaze-precision-study     视线/指尖精度研究（新建）

为什么拆（用户的判断，我认同）：
    视线/指尖研究解决的是【输入方式】—— 用什么操作电脑
    阅读扩展解决的是【理解内容】—— 哪一句没读懂
    这不是同一个问题，两者没有共用代码、没有共用技术。

    我原来在 README 里写的那条线（"测了视线不可用 → 转向判断你卡在哪句"）
    讲得太顺了，把两个问题说成了一条因果链。

归属划分：

    研究仓库（本脚本建的）：
        README.md            由 RESEARCH.md 改写（加一段导语 + 指向另一个仓库）
        research-report.md   调研与 MVP 方案（视线词 54 / 阅读词 2）
        ROADMAP.md           视线交互路线图（21 / 1）
        README-LOCAL.md      Gaze Collector 本地运行说明（10 / 0）
        demo/index.html      视线交互 Demo
        demo/demo-hand.html  指尖指针
        demo/hand-test.html  手部追踪精度测试
        gaze_*_frames.csv    6 个原始测量
        collector.html       采集工具
        data/                检查图与说明
        eyetrax_result.json / run_eyetrax_test.cmd
        tools/               gaze-research 的分析脚本
        LICENSE

    扩展仓库保留：
        plugin/ demo/reader_flow.html + reader.html + reader_zones.html
        tools/（不含 gaze-research）  store/
        README.md（重写） PROBLEMS.md JOURNEY.md INTERVIEW.md
        FINDINGS-trigger.md
        （reader.html / reader_zones.html 留在扩展这边：
          它们是"认知状态推断层"的验证工具，而推断层是扩展的一部分，
          它的结论 FINDINGS-trigger.md 也在扩展这边 —— 拆开就成了
          结论和工具分居两地。）
'''
import io
import os
import shutil
import sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')
ROOT = r'D:\projects\gaze-project'
OUT = os.path.join(ROOT, 'publish-gaze')

# ---------------------------------------------------------------- 清空重建
if os.path.isdir(OUT):
    assert os.path.abspath(OUT) == os.path.join(os.path.abspath(ROOT), 'publish-gaze'), \
        '路径不对，拒绝删除'
    gitdir = os.path.join(OUT, '.git')
    stash = None
    if os.path.isdir(gitdir):
        stash = os.path.join(ROOT, '.publish-gaze-git-stash')
        if os.path.isdir(stash):
            shutil.rmtree(stash)
        shutil.move(gitdir, stash)
    shutil.rmtree(OUT)
    os.makedirs(OUT)
    if stash:
        shutil.move(stash, os.path.join(OUT, '.git'))
        print('  检测到 .git —— 已保住')
else:
    os.makedirs(OUT)
print('  publish-gaze/ 已重建')

# ---------------------------------------------------------------- README
#  以 RESEARCH.md 为主体，前面加一段导语。
#  导语要说清三件事：
#    ① 这是什么（一句话）
#    ② 它和另一个仓库的关系（不藏：那里是分出去的另一条路）
#    ③ 结论是什么（让人三秒知道值不值得读下去）
research = io.open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
# 去掉之前加在扩展 README 里的"已上架"一节（那属于扩展仓库）
cut = research.find('## 一句话结论')
body = research[cut:] if cut > 0 else research

LEAD = """# 消费级摄像头的免手交互精度边界研究

用一台普通 640×480 网络摄像头做免手交互，回答一个具体问题：
**在消费级硬件能达到的精度下，哪种输入模态、界面应该怎么设计？**

不是"手势控制 PPT"式的演示项目。核心产出是**定量的精度边界**、
**一组被证伪的直觉假设**，以及一条**从失败模态迁移到可行模态的决策链**。

> **这个仓库是独立的研究仓库。**
> 同一时期还有另一条路 —— 一个按句高亮、就地讲解的阅读辅助扩展：
> <https://github.com/guizhouxiemeng/sentence-reader>
>
> 两者**没有代码依赖，也不解决同一个问题**：
> 这里研究的是「用什么操作电脑」（输入方式），
> 那边解决的是「哪一句没读懂」（理解内容）。
> 唯一的共同点是同一个出发点：读论文时不顺畅。

---

"""

# 去掉 body 里原有的标题行（避免出现两个 H1）
lines = body.split('\n')
while lines and (lines[0].startswith('# ') or not lines[0].strip()):
    lines.pop(0)
body = '\n'.join(lines)

io.open(os.path.join(OUT, 'README.md'), 'w', encoding='utf-8', newline='').write(
    LEAD + body)
print('  README.md（由 RESEARCH.md 改写，加了导语）')

# ---------------------------------------------------------------- 文档
for fn in ('research-report.md', 'ROADMAP.md', 'README-LOCAL.md'):
    src = os.path.join(ROOT, fn)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(OUT, fn))
print('  文档 3 份（research-report / ROADMAP / README-LOCAL）')

# ---------------------------------------------------------------- 早期页面
os.makedirs(os.path.join(OUT, 'demo'), exist_ok=True)
n = 0
for fn in ('index.html', 'demo-hand.html', 'hand-test.html'):
    src = os.path.join(ROOT, 'demo', fn)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(OUT, 'demo', fn))
        n += 1
print('  demo/ 早期实验台 %d 个页面' % n)

# ---------------------------------------------------------------- 数据
GAZE_FILES = [
    'gaze_p1_frames.csv', 'gaze_p029379_frames.csv', 'gaze_p411900_frames.csv',
    'gaze_p463357_frames.csv', 'gaze_p478309_frames.csv', 'gaze_p496980_frames.csv',
    'collector.html', 'run_eyetrax_test.cmd', 'eyetrax_result.json',
]
gn = 0
for fn in GAZE_FILES:
    src = os.path.join(ROOT, fn)
    if os.path.exists(src):
        shutil.copy2(src, os.path.join(OUT, fn))
        gn += 1
print('  原始测量数据 %d 个文件' % gn)

# data/：跳过眼部图像（真人眼睛，不公开）
DATA_SKIP = {'eye_grid.png', 'signal_check_左眼.png', 'signal_check_右眼.png'}
os.makedirs(os.path.join(OUT, 'data'), exist_ok=True)
dn = 0
for fn in os.listdir(os.path.join(ROOT, 'data')):
    src = os.path.join(ROOT, 'data', fn)
    if os.path.isfile(src) and fn not in DATA_SKIP:
        shutil.copy2(src, os.path.join(OUT, 'data', fn))
        dn += 1
print('  data/ %d 个文件（跳过眼部图像）' % dn)

# ---------------------------------------------------------------- 分析脚本
src = os.path.join(ROOT, 'tools', 'gaze-research')
dst = os.path.join(OUT, 'tools')
shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__', '.git'))
cn = sum(len(fs) for _, _, fs in os.walk(dst))
print('  tools/ 分析脚本 %d 个文件' % cn)

# ---------------------------------------------------------------- LICENSE
shutil.copy2(os.path.join(ROOT, 'publish', 'LICENSE'), os.path.join(OUT, 'LICENSE'))
print('  LICENSE（MIT，从扩展仓库复制，保持一致）')

# ---------------------------------------------------------------- .gitignore
io.open(os.path.join(OUT, '.gitignore'), 'w', encoding='utf-8', newline='').write(
    '# 眼部图像：真人眼睛，不公开\n'
    'data/eyes_p029379/\ndata/eye_grid.png\ndata/signal_check_*.png\ngaze_*_eyes.zip\n\n'
    '# 由 CSV 生成的图，跑脚本能重画\n'
    'gaze_*_headfree.png\ngaze_*_diag.png\ngaze_*_experiment.png\n\n'
    '# 第三方大件（MediaPipe 模型约 30MB，未进仓库）\n'
    'vendor/\n\n'
    '# 系统 / 编辑器\n__pycache__/\n.venv/\n.DS_Store\nThumbs.db\n.vscode/\n.idea/\n')
io.open(os.path.join(OUT, '.gitattributes'), 'w', encoding='utf-8', newline='').write(
    '# 语言统计：分析脚本不参与（它们的价值在结论不在代码）\n'
    'tools/**  linguist-vendored\n\n'
    '# 文档\n*.md  linguist-documentation\nLICENSE  linguist-documentation\n\n'
    '# 数据\n*.csv  linguist-data\n')
print('  .gitignore + .gitattributes')

# ---------------------------------------------------------------- 统计
tf = tb = 0
for dp, dns, fns in os.walk(OUT):
    dns[:] = [d for d in dns if d != '.git']
    for fn in fns:
        tf += 1
        tb += os.path.getsize(os.path.join(dp, fn))
print()
print('=' * 70)
print('  publish-gaze/ 共 %d 个文件，%.1f MB' % (tf, tb / 1024 / 1024))
print('=' * 70)
for d in sorted(os.listdir(OUT)):
    if d == '.git':
        continue
    p = os.path.join(OUT, d)
    if os.path.isfile(p):
        print('    %-28s %8.1f KB' % (d, os.path.getsize(p) / 1024))
    else:
        sz = sum(os.path.getsize(os.path.join(dp, f))
                 for dp, _, fs in os.walk(p) for f in fs)
        cnt = sum(len(fs) for _, _, fs in os.walk(p))
        print('    %-28s %8.1f KB  (%d 个文件)' % (d + '/', sz / 1024, cnt))
