#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
cognitive_state.py — 认知状态推断层的实现

对应 tools/cognitive_state_design.py 里确定的设计。核心是两层：

  信号层（逐帧更新，O(1) 内存）
      region(t) -> dwell[R], visits[R], revisit[R], visitDur[R][]
      effort[R] = dwell[R] / (1 + revisit[R] * 0.6)

  判定层（用相对基线，不用绝对阈值）
      base[R] = len[R] * 该人的单位长度用时
      跳过 / 正常阅读 / 处理受阻

为什么用"重访率"而不是纯"停留时长"：
    停留时长分不清"吃力"和"这段内容本来就多"，两者都表现为待得久。
    而"同一段反复回去"是受阻的特异性指标（即阅读研究里的回视次数）。

为什么用相对基线：
    绝对阈值会把慢读者全部判成"受阻"。基线从使用者自己的正常段落估出。

本模块不依赖摄像头、不依赖 LLM，可单独测试 —— 这是刻意的设计，
因为只有这样"效果来自时机还是来自解释质量"才能分离。

用法：
  python tools/cognitive_state.py            # 用合成轨迹自测
"""
import math
import sys
from collections import defaultdict

for _s in ('stdout', 'stderr'):
    try:
        getattr(sys, _s).reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ---------------------------------------------------------------- 参数
FPS = 30.0
DT = 1.0 / FPS

# 停留判据：光标速度低于此值视为"在停留"（高于视为扫视，不计入 dwell）
#
#  这里踩过一个坑，值得记录 —— 有三个量容易混为一谈：
#      ① 绝对偏差 |预测-目标|      实测中位 632 px   （系统偏差主导，可校准）
#      ② 位置抖动（段内散布）       实测中位  75 px   （绝对量级）
#      ③ 逐帧步长（相邻帧位移）     实测中位 4.2 px   （p90 13.2 px，约 97fps）
#  停留门限必须比【③ 逐帧步长】大，而不是比【② 位置抖动】大。
#  早先版本按"抖动的 3 倍"取了 204 px/s，而实测逐帧速度中位就有 407 px/s，
#  于是没有任何一帧被判为停留，dwell 全是 0，所有状态都退化成 reading。
#
#  现在取 ③ 的 p90 的 3 倍作为门限：既能容纳凝视颤动，
#  又能把真正的扫视（阅读时通常 > 2000 px/s）排除。
STILL_SPEED_PX_S = 13.2 * 3 / 0.0103      # ≈ 3845 px/s，基于实测 p90 步长与帧间隔

# 访问判定：进入区域且连续停留 >= 该时长才算"一次访问"
# 用于滤掉段边界抖动造成的瞬时穿越
MIN_VISIT_SEC = 0.15

# effort 的定义：总注视时间（不扣除回读时间）
#
#  这里纠正过一个设计错误，值得记录：
#    早先试图从 effort 里"扣掉回读占用的时间"，理由是"回读不算新的处理"。
#    但这个扣法有两个问题：
#      ① 扣的量不对：当时按"回读次数 x 整段预期时长"扣，
#         而实测一次回读只花约 1 秒，结果扣成了负数（58.5 - 3x24 = -13.5）。
#      ② 更根本的是方向错了：受阻时"反复回去看"这件事【本身就是证据】，
#         把它扣掉等于把要检测的信号删掉。
#
#  所以 effort 就是总注视时间，而"分不清吃力与内容多"的问题
#  交给辅助条件解决 —— 见 classify() 里的三条件表决。
EFFORT_SUBTRACT_REREAD = False

# 状态阈值（相对 base 的倍数）
T_SKIP = 0.35          # 低于此比例且无回看 -> 跳过
T_READ_LO = 0.50       # 正常阅读下界
T_READ_HI = 1.80       # 正常阅读上界
T_BLOCKED = 2.00       # 高于此比例且满足辅助条件 -> 处理受阻
#  阈值取自实测两类的分界：
#    受阻段（盯 55~72 秒 / 基线 24 秒）          ratio 2.4 ~ 3.0
#    内容多但正常读完（如盯 42 秒 / 基线 24 秒）  ratio 约 1.7
#  取 2.0 落在两者之间。且超过 2.0 单独仍不足以判定，还要有辅助条件。
T_PREPARE = 1.50       # 越过此比例即开始"静默准备"（不打扰）

# 受阻的辅助条件
AUX_REVISIT_MIN = 2         # 回看次数 >= 2
AUX_LONG_VISIT_MULT = 2.0   # 最长单次访问 > 2.0 x base

# 自动展开的例外条件
AUTO_REVEAL_WINDOW_S = 30.0
AUTO_REVEAL_COUNT = 3

# 侧边栏取出条件
SIDEBAR_DWELL_S = 0.8


class Region:
    """一个段级区域。rect 用屏幕像素 (x0,y0,x1,y1)。"""

    __slots__ = ('rid', 'x0', 'y0', 'x1', 'y1', 'chars', 'order')

    def __init__(self, rid, x0, y0, x1, y1, chars, order=None):
        self.rid = rid
        self.x0, self.y0, self.x1, self.y1 = x0, y0, x1, y1
        self.chars = chars
        self.order = rid if order is None else order

    def contains(self, x, y):
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def __repr__(self):
        return 'R%d(%d字)' % (self.rid, self.chars)


class CognitiveStateTracker:
    """逐帧喂入注视点，输出认知状态。"""

    def __init__(self, regions, cps=5.0):
        """
        regions: Region 列表
        cps: 该人的阅读速度（字/秒）。5.0 字/秒 ≈ 300 字/分钟。
             实际使用时应从会话开头的正常段落估出，这里作为初值。
        """
        self.regions = list(regions)
        self.cps = cps

        # 信号层状态
        self.dwell = defaultdict(float)
        self.visits = defaultdict(int)
        self.visit_durs = defaultdict(list)
        self.last_pos = None
        self.last_t = None
        self.cur_region = None
        self.cur_start = None
        self.still_time = 0.0        # 当前停留的连续时长
        self.buffer_region = None    # 已进入但还没达 MIN_VISIT_SEC 的候选

        # 事件与判定
        self.events = []             # 操作事件（视频：暂停/倒退）(t, kind, region)
        self.blocked_hits = defaultdict(list)   # rid -> [t,...] 判定为受阻的时刻
        self._last_auto = {}                     # rid -> 上次自动展开时刻（冷却用）
        self.prepared = set()        # 已静默准备过的区域
        self.reveals = []            # 展开记录 (t, rid, reason)
        self.t = 0.0
        self._sidebar_dwell = defaultdict(float)

    # ------------------------------------------------------------ 信号层
    def region_at(self, x, y):
        for r in self.regions:
            if r.contains(x, y):
                return r
        return None

    def update(self, x, y):
        """喂入一帧注视点，返回本帧状态字典。"""
        self.t += DT
        reg = self.region_at(x, y)
        rid = reg.rid if reg else None

        # 速度 -> 是否在停留
        speed = 0.0
        if self.last_pos is not None:
            dx = x - self.last_pos[0]
            dy = y - self.last_pos[1]
            speed = math.hypot(dx, dy) / DT
        self.last_pos = (x, y)

        # ---- 段内累计注视时间（只在停留且归属同一段时累计） ----
        if rid is not None and speed < STILL_SPEED_PX_S:
            self.dwell[rid] += DT
            self.still_time += DT
        else:
            self.still_time = 0.0

        # ---- 访问判定 ----
        if rid != self.cur_region:
            # 离开旧段：结算
            if self.cur_region is not None and self.cur_start is not None:
                dur = self.t - self.cur_start
                if dur >= MIN_VISIT_SEC:
                    self.visit_durs[self.cur_region].append(dur)
                else:
                    # 太短，撤销这次访问计数（属于边界抖动）
                    self.visits[self.cur_region] -= 1
                    if self.visits[self.cur_region] < 0:
                        self.visits[self.cur_region] = 0
            # 进入新段
            self.cur_region = rid
            self.cur_start = self.t if rid is not None else None
            if rid is not None:
                self.visits[rid] += 1

        return self.state_snapshot(rid)

    def add_event(self, kind, rid=None):
        """记录操作事件（视频场景：pause / seek_back）。"""
        self.events.append((self.t, kind, rid))

    # ------------------------------------------------------------ 判定层
    def base_of(self, rid):
        """该段的预期处理量（秒） = 字数 / 阅读速度。"""
        for r in self.regions:
            if r.rid == rid:
                return max(r.chars / self.cps, 0.2)
        return None

    def revisit_of(self, rid):
        return max(self.visits.get(rid, 0) - 1, 0)

    def effort_of(self, rid):
        """净处理时间 = 总注视时间 - 回读占用的时间。

        受阻时重复读的时间花在移动和重读已知内容上，不是新的处理，
        所以扣除"重复读一遍的预期用时"，剩下的才是真正的理解投入。
        """
        d = self.dwell.get(rid, 0.0)
        if not EFFORT_SUBTRACT_REREAD:
            return d
        rv = self.revisit_of(rid)
        base = self.base_of(rid) or 0.0
        return max(d - rv * base, 0.0)

    def ratio_of(self, rid):
        b = self.base_of(rid)
        if not b:
            return None
        return self.effort_of(rid) / b

    def recent_events(self, window):
        return [e for e in self.events if self.t - e[0] <= window]

    def classify(self, rid):
        """返回 (状态, 依据dict)。"""
        if rid is None:
            return 'off', {}
        ratio = self.ratio_of(rid)
        if ratio is None:
            return 'off', {}
        rv = self.revisit_of(rid)
        durs = self.visit_durs.get(rid, [])
        base = self.base_of(rid)
        longest = max(durs) if durs else (self.t - self.cur_start
                                          if rid == self.cur_region
                                          and self.cur_start else 0.0)
        aux = []
        if rv >= AUX_REVISIT_MIN:
            aux.append('回看%d次' % rv)
        if base and longest > base * AUX_LONG_VISIT_MULT:
            aux.append('单次%.1fs(>%.1fx基线)' % (longest, AUX_LONG_VISIT_MULT))
        ev = [e for e in self.recent_events(30.0) if e[2] == rid]
        if ev:
            aux.append('操作事件%d次' % len(ev))

        info = dict(ratio=ratio, revisit=rv, effort=self.effort_of(rid),
                    base=base, longest=longest, aux=aux)

        # 判定采用【两条件同时满足】：
        #   ratio > T_BLOCKED        说明在这一段花的处理量远超预期
        #   且 aux 非空              说明有"回去过 / 卡了很久 / 有操作事件"
        #
        #  两条件缺一不可，因为单独任一条件都会误判：
        #   · 只看 ratio 高      -> 把"这段内容本来就多、读者正常读完"判成受阻
        #   · 只看回看           -> 把"偶尔扫回上一段对照"判成受阻
        #  读者感知识别里"慢但没卡住"与"卡住了"的差别，正好落在这两个条件的交集上。
        if ratio > T_BLOCKED and aux:
            return 'blocked', info
        if ratio < T_SKIP and rv == 0:
            return 'skipped', info
        if T_READ_LO <= ratio <= T_READ_HI:
            return 'reading', info
        return 'reading' if ratio < T_BLOCKED else 'reading', info

    # ------------------------------------------------------------ 响应层
    def state_snapshot(self, rid):
        st, info = self.classify(rid)
        # 静默准备：越过 T_PREPARE 即后台准备（界面无变化）
        prepared_now = None
        if rid is not None:
            ratio = self.ratio_of(rid)
            if ratio is not None and ratio > T_PREPARE and rid not in self.prepared:
                self.prepared.add(rid)
                prepared_now = rid
        # 受阻判定
        if st == 'blocked' and rid is not None:
            self.blocked_hits[rid].append(self.t)
            # 自动展开的例外
            recent = [x for x in self.blocked_hits[rid]
                      if self.t - x <= AUTO_REVEAL_WINDOW_S]
            # 冷却保护：展开后的一段时间内不再重复触发。
            # 早先只清空 blocked_hits，结果下一帧又立刻凑满 3 次，
            # 于是 172.8~186.0 秒之间几乎每帧都展开一次。
            last_auto = self._last_auto.get(rid, -1e9)
            if (len(recent) >= AUTO_REVEAL_COUNT
                    and self.t - last_auto > AUTO_REVEAL_WINDOW_S):
                self.reveals.append((self.t, rid, 'auto-repeat'))
                self._last_auto[rid] = self.t
                self.blocked_hits[rid] = []
        return dict(t=self.t, rid=rid, state=st, prepared_now=prepared_now,
                    info=info)

    def sidebar_update(self, x, y, sidebar_rect):
        """侧边栏停留检测：停留 > SIDEBAR_DWELL_S 则展开已准备的解释。"""
        x0, y0, x1, y1 = sidebar_rect
        inside = (x0 <= x < x1 and y0 <= y < y1)
        for rid in list(self._sidebar_dwell):
            if not inside:
                self._sidebar_dwell[rid] = 0.0
        if inside and self.cur_region is None:
            for rid in self.prepared:
                self._sidebar_dwell[rid] += DT
                if self._sidebar_dwell[rid] >= SIDEBAR_DWELL_S:
                    self.reveals.append((self.t, rid, 'user-gaze'))
                    self._sidebar_dwell[rid] = -1e9   # 只展开一次
                    return rid
        return None


# ==================================================================== 自测
def make_test_regions():
    """造 6 个段落，纵向排布。每段 120 字。"""
    regs = []
    x0, x1 = 100, 1500
    for i in range(6):
        y0 = 80 + i * 150
        regs.append(Region(i, x0, y0, x1, y0 + 140, chars=120))
    return regs


def simulate(regions, plan, cps=5.0, spread=75.0, step=4.2, seed=0):
    """按 plan 生成合成注视轨迹。

    plan: [(rid, 停留秒数, 回看次数)] —— 每一步先正常读该段，
          然后额外回去 revisit 次（每次 1.2 秒）。

    两个抖动参数必须分开（这是我早先的错误）：
      spread —— 段内位置的整体散布（实测中位 75 px）。决定"看得准不准"。
      step   —— 逐帧步长（实测中位 4.2 px）。决定"是否算作停留"。

    早先版本用 spread 当逐帧噪声，导致帧间速度高达 2000+ px/s，
    全部超过停留门限，dwell 恒为 0。真实凝视是【缓慢游走】，
    逐帧变化很小、但累积起来散布可达几十像素 —— 所以用随机游走建模。
    """
    import random
    rng = random.Random(seed)

    def walk(cx, cy, n):
        """从 (cx,cy) 出发做受限随机游走，逐帧步长 ~ step。"""
        x, y = cx, cy
        out = []
        for _ in range(n):
            x += rng.gauss(0, step)
            y += rng.gauss(0, step)
            # 弹性拉回，保证长期散布 ~ spread 而不是无界扩散
            x += (cx - x) * 0.02
            y += (cy - y) * 0.02
            out.append((x, y))
        return out

    tr = CognitiveStateTracker(regions, cps=cps)
    log = []
    for (rid, dur, revisit) in plan:
        reg = next(r for r in regions if r.rid == rid)
        cx = (reg.x0 + reg.x1) / 2
        cy = (reg.y0 + reg.y1) / 2
        # 正常读这一段
        for (x, y) in walk(cx, cy, int(dur * FPS)):
            log.append(tr.update(x, y))
        # 额外回看
        for _ in range(revisit):
            for (x, y) in walk(cx + 900, cy + 400, int(0.5 * FPS)):
                log.append(tr.update(x, y))
            for (x, y) in walk(cx, cy, int(1.2 * FPS)):
                log.append(tr.update(x, y))
        # 前进
        for (x, y) in walk(cx + 900, cy + 400, int(0.4 * FPS)):
            log.append(tr.update(x, y))
    return tr, log


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--spread', type=float, default=75.0)
    ap.add_argument('--step', type=float, default=4.2)
    args = ap.parse_args()

    print('=' * 86)
    print('认知状态推断层 —— 合成轨迹自测')
    print('=' * 86)
    print('  参数：位置散布 %.0fpx / 逐帧步长 %.1fpx，阅读速度 5 字/秒，每段 120 字'
          % (args.spread, args.step))
    print('        -> 每段基线 base = 120/5 = 24.0 秒')
    print()

    regions = make_test_regions()

    # 场景：R0 正常、R1 受阻、R2 跳过、R3 正常、R4 受阻、R5 正常
    #
    #  受阻的真实表现不是"多待几秒"，而是【盯得明显更久 + 反复回读】。
    #  早先合成数据只给受阻段加了 2~6 秒，所以判不出受阻 ——
    #  那是数据不合实际，不是判据太严。
    plan = [
        (0, 24.0, 0),    # 正常阅读
        (1, 55.0, 3),    # 受阻：盯 55 秒 + 回读 3 次
        (2, 3.0, 0),     # 跳过
        (3, 24.0, 0),    # 正常
        (4, 70.0, 2),    # 受阻：更严重
        (5, 24.0, 0),    # 正常
    ]
    truth = {0: 'reading', 1: 'blocked', 2: 'skipped',
             3: 'reading', 4: 'blocked', 5: 'reading'}

    tr, log = simulate(regions, plan, spread=args.spread, step=args.step)

    print('=' * 86)
    print('逐段结果')
    print('=' * 86)
    print('  %-4s %-8s %-10s %-10s %-10s %-12s %-10s %s'
          % ('段', '字数', '基线s', 'dwell', 'effort', 'ratio', '回看', '判定'))
    print('  ' + '-' * 82)
    correct = 0
    for r in regions:
        rid = r.rid
        d = tr.dwell.get(rid, 0.0)
        e = tr.effort_of(rid)
        ratio = tr.ratio_of(rid)
        rv = tr.revisit_of(rid)
        st, info = tr.classify(rid)
        ok = 'OK' if st == truth[rid] else 'MISS(期望%s)' % truth[rid]
        if st == truth[rid]:
            correct += 1
        print('  %-4d %-8d %-10.1f %-10.1f %-10.1f %-12s %-10d %s  %s'
              % (rid, r.chars, tr.base_of(rid), d, e,
                 ('%.2f' % ratio) if ratio else '-', rv, st, ok))
    print()
    print('  准确率: %d/%d' % (correct, len(regions)))

    print()
    print('=' * 86)
    print('响应层事件')
    print('=' * 86)
    print('  静默准备过的段: %s' % sorted(tr.prepared))
    _rv = [(round(t, 1), rid, why) for t, rid, why in tr.reveals]
    print('  已展开 %d 次: %s%s' % (len(_rv), _rv[:6], ' ...' if len(_rv) > 6 else ''))
    print()
    print('  说明：R1/R4 被准备（effort 越过 1.5x base），但默认【不展开】——')
    print('        只有使用者把视线移到侧边栏停留 >0.8s 才取出。')
    print('        若同段 30 秒内受阻 >=3 次，才自动展开一次。')

    print()
    print('=' * 86)
    print('抖动敏感性：推断层在多大抖动下仍成立')
    print('=' * 86)
    print('  %-12s %-12s %-12s %s' % ('逐帧步长px', '准确率', '误判情况', '判读'))
    print('  ' + '-' * 70)
    for st in (1.0, 4.2, 10.0, 25.0, 60.0):
        tr2, _ = simulate(regions, plan, step=st)
        c = sum(1 for r in regions if tr2.classify(r.rid)[0] == truth[r.rid])
        misses = [r.rid for r in regions if tr2.classify(r.rid)[0] != truth[r.rid]]
        v = 'OK' if c == len(regions) else ('部分退化' if c >= 4 else '失效')
        print('  %-12.1f %-12s %-12s %s'
              % (st, '%d/%d' % (c, len(regions)),
                 ('段%s' % misses) if misses else '无', v))
    print()
    print('  注：合成轨迹里抖动只影响速度判据（是否算作"停留"），')
    print('      所以本测试对抖动的敏感度【低于真实情况】——')
    print('      真实数据里抖动还会影响段归属的准确性。')
    print('      这一点必须用真实阅读数据复核。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
