# -*- coding: utf-8 -*-
"""
OpenHR 风控对抗基础模块
=======================
职责：
  - 随机操作间隔（正态分布）
  - 鼠标轨迹模拟（贝塞尔曲线）
  - 页面滚动行为模拟
  - 验证码检测 + 暂停 + 通知机制
  - 封号预警逻辑（异常检测 → 自动降速/暂停）
  - Playwright stealth 配置（隐藏 webdriver 标识）

依赖：
  pip install playwright playwright-stealth numpy
  playwright install chromium

用法：
  from scripts.anti_detect import AntiDetect
  ad = AntiDetect(config_path="config/anti_detect.json")
  await ad.apply_stealth(page)          # 初始化 stealth
  await ad.random_delay()               # 随机停顿
  await ad.simulate_mouse(page, x, y)   # 移动鼠标
  await ad.simulate_scroll(page)         # 模拟滚动
  detected = await ad.detect_captcha(page)  # 检测验证码
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

import numpy as np

# ---------------------------------------------------------------------------
# Stealth JS — 注入到 Playwright context，抹除自动化特征
# ---------------------------------------------------------------------------
STEALTH_JS = """
(function () {
    // 1. 隐藏 webdriver 标识
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. 恢复被 Playwright 修改的 navigator properties
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en-US', 'en']
    });
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4]
    });
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => [8, 16][Math.floor(Math.random() * 2)]
    });
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => [4, 8][Math.floor(Math.random() * 2)]
    });

    // 3. 抹除 chrome runtime 对象
    window.chrome = window.chrome || { runtime: {}, loadTimes: function(){},	csi: function(){} };

    // 4. 伪造 permissions 查询
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );

    // 5. 伪造 WebGL vendor / renderer
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (parameter) {
        if (parameter === 37445) return 'Intel Inc.';
        if (parameter === 37446) return 'Intel Iris OpenGL Engine';
        return getParameter.apply(this, arguments);
    };

    // 6. 伪造 AudioContext fingerprint
    if (window.AudioContext || window.webkitAudioContext) {
        const proto = (window.AudioContext || window.webkitAudioContext).prototype;
        const _getChannelData = proto.decodeAudioData || proto.decodeAudioData;
        proto.decodeAudioData = function (buffer) {
            return _getChannelData.call(this, buffer);
        };
    }

    // 7. 伪造 mediaDevices enumerateDevices
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
        const _enum = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
        navigator.mediaDevices.enumerateDevices = () =>
            _enum().then(devices => {
                const fake = [...devices];
                // 随机去掉一个真实设备，让列表看起来更自然
                if (fake.length > 1 && Math.random() > 0.5) fake.pop();
                return fake;
            });
    }

    // 8. 拦截 navigator.webdriver（双重保险）
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
})();
"""


# ---------------------------------------------------------------------------
# 配置数据结构
# ---------------------------------------------------------------------------
@dataclass
class AntiDetectConfig:
    delay_min: float = 5.0           # 最小操作间隔（秒）
    delay_max: float = 15.0          # 最大操作间隔（秒）
    delay_sigma: float = 2.5         # 正态分布 sigma
    daily_action_limit: int = 200    # 每日动作上限（超过触发警告）
    captcha_keywords: List[str] = field(default_factory=lambda: [
        "验证码", "安全验证", "拼图", "滑动验证", "请在下方",
        "captcha", "verify", "验证", "人机验证", "请完成验证"
    ])
    warning_thresholds: dict = field(default_factory=lambda: {
        "error_rate_pct": 30,         # 错误率超过 30% 触发警告
        "consecutive_failures": 3,    # 连续失败次数
        "action_burst": 10,           # N 秒内动作数阈值
        "burst_window_sec": 30,       # 动作 burst 统计窗口
    })
    scroll_min: int = 300            # 最小滚动步长（px）
    scroll_max: int = 900            # 最大滚动步长（px）
    scroll_pause: tuple = (0.5, 2.0) # 滚动间停顿（秒）

    @classmethod
    def from_file(cls, path: str | Path) -> "AntiDetectConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


# ---------------------------------------------------------------------------
# 行为统计（用于封号预警）
# ---------------------------------------------------------------------------
@dataclass
class ActionStats:
    total: int = 0
    errors: int = 0
    captchas: int = 0
    recent_timestamps: list = field(default_factory=list)  # 时间戳列表（滑动窗口）

    def record_action(self):
        now = time.time()
        self.total += 1
        self.recent_timestamps.append(now)
        # 只保留滑动窗口内的记录
        cutoff = now - 60  # 只保留最近 60 秒
        self.recent_timestamps = [t for t in self.recent_timestamps if t >= cutoff]

    def record_error(self):
        self.errors += 1

    def record_captcha(self):
        self.captchas += 1

    def error_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.errors / self.total * 100

    def burst_count(self, window: int = 30) -> int:
        """统计最近 window 秒内的动作数"""
        now = time.time()
        return sum(1 for t in self.recent_timestamps if (now - t) <= window)

    def consecutive_failures(self) -> int:
        return min(self.errors, 3)  # 简版，实际可用滑动窗口追踪


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------
class AntiDetect:
    """
    OpenHR 风控对抗模块
    """

    def __init__(self, config_path: str | Path | None = None):
        if config_path and Path(config_path).exists():
            self.cfg = AntiDetectConfig.from_file(config_path)
        else:
            # 默认配置
            self.cfg = AntiDetectConfig()

        self.stats = ActionStats()
        self._state = "normal"   # normal | warning | paused
        self._pause_until: float = 0   # unix timestamp

        # 加载环境变量中的通知 token（可选）
        self._notify_token = os.getenv("OPENHR_NOTIFY_TOKEN", "")

    # ------------------------------------------------------------------
    # 通知机制（可扩展）
    # ------------------------------------------------------------------
    async def _notify(self, msg: str):
        """发送通知。默认打印到 stdout；可接入飞书/钉钉/TG bot。"""
        print(f"[AntiDetect NOTIFY] {msg}")
        # TODO: 接入飞书 Webhook / TG Bot / 邮件等
        # if self._notify_token:
        #     async with aiohttp.post("https://...", json={"msg": msg}) as resp:
        #         pass

    # ------------------------------------------------------------------
    # 1. 随机操作间隔
    # ------------------------------------------------------------------
    def _gaussian_delay(self) -> float:
        """生成正态分布随机延迟，以 (min+max)/2 为均值。"""
        mean = (self.cfg.delay_min + self.cfg.delay_max) / 2
        delay = random.gauss(mean, self.cfg.delay_sigma)
        # 钳制到 [min, max]
        return max(self.cfg.delay_min, min(self.cfg.delay_max, delay))

    async def random_delay(self) -> float:
        """
        执行一次随机停顿。返回实际睡眠秒数。
        如果处于暂停状态则自动延长暂停时间。
        """
        if time.time() < self._pause_until:
            wait = self._pause_until - time.time()
            print(f"[AntiDetect] PAUSED — 等待 {wait:.1f}s")
            await asyncio.sleep(wait)

        delay = self._gaussian_delay()
        print(f"[AntiDetect] 随机停顿 {delay:.2f}s")
        await asyncio.sleep(delay)
        self.stats.record_action()
        return delay

    async def random_delay_short(self) -> float:
        """
        短随机延迟（0.5-2s），用于页面操作间的快速停顿。
        比 random_delay() 更保守，避免被识别为机器人行为。
        """
        delay = random.uniform(0.5, 2.0)
        print(f"[AntiDetect] 短停顿 {delay:.2f}s")
        await asyncio.sleep(delay)
        self.stats.record_action()
        return delay

    # ------------------------------------------------------------------
    # 2. 鼠标轨迹模拟（贝塞尔曲线）
    # ------------------------------------------------------------------
    async def simulate_mouse(
        self,
        page,
        target_x: int,
        target_y: int,
        steps: int = 0,
        hover_before_ms: tuple = (200, 900),
    ):
        """
        模拟人类鼠标移动：从当前位置沿贝塞尔曲线移动到 (target_x, target_y)。

        Args:
            page: Playwright Page 对象
            target_x, target_y: 目标坐标
            steps: 轨迹分段数（0=自动）
            hover_before_ms: 点击前随机悬停时长区间
        """
        if steps <= 0:
            steps = random.randint(8, 16)

        # 获取当前鼠标位置（从 viewport 左上角开始或随机起点）
        start_x = random.randint(50, 300)
        start_y = random.randint(50, 300)

        # 生成控制点（构建三次贝塞尔）
        cp1x = start_x + random.randint(-200, 300)
        cp1y = start_y + random.randint(-150, 150)
        cp2x = target_x + random.randint(-100, 100)
        cp2y = target_y + random.randint(-100, 100)

        def bezier(t: float) -> tuple:
            """三次贝塞尔公式"""
            x = (1 - t) ** 3 * start_x + 3 * (1 - t) ** 2 * t * cp1x + \
                3 * (1 - t) * t ** 2 * cp2x + t ** 3 * target_x
            y = (1 - t) ** 3 * start_y + 3 * (1 - t) ** 2 * t * cp1y + \
                3 * (1 - t) * t ** 2 * cp2y + t ** 3 * target_y
            return int(x), int(y)

        # 逐段移动（带加速-减速曲线）
        for i in range(steps + 1):
            t = i / steps
            # 应用 ease-in-out 曲线
            t = t * t * (3 - 2 * t) if random.random() > 0.3 else t
            x, y = bezier(t)
            await page.mouse.move(x, y)
            # 每段停顿：开头快，接近目标慢
            step_delay = random.uniform(0.005, 0.04) * (1 + (1 - t) * 0.5)
            await asyncio.sleep(step_delay)

        # 目标增加微量随机偏移（避免每次正中圆心）
        final_x = target_x + random.randint(-3, 3)
        final_y = target_y + random.randint(-3, 3)
        await page.mouse.move(final_x, final_y)

        # 悬停
        hover = random.uniform(hover_before_ms[0], hover_before_ms[1]) / 1000
        await asyncio.sleep(hover)

    # ------------------------------------------------------------------
    # 3. 页面滚动行为模拟
    # ------------------------------------------------------------------
    async def simulate_scroll(
        self,
        page,
        distance: int | None = None,
        steps: int = 0,
    ):
        """
        模拟人类滚动：分多次小步滚动，每步之间随机停顿。

        Args:
            page: Playwright Page 对象
            distance: 总滚动距离（px），None=随机
            steps: 分几步完成
        """
        if distance is None or distance == 0:
            distance = random.randint(self.cfg.scroll_min, self.cfg.scroll_max)

        if steps <= 0:
            steps = random.randint(3, 7)

        per_step = distance // steps
        for i in range(steps):
            # 本步实际距离（最后一步可能有余数）
            d = per_step + random.randint(-50, 50) if i < steps - 1 else distance - per_step * i
            await page.evaluate(f"window.scrollBy(0, {d})")
            # 每步之间随机停顿
            pause = random.uniform(*self.cfg.scroll_pause)
            await asyncio.sleep(pause)
            # 偶尔往回滚一点再继续（模拟"看漏了回头"）
            if random.random() < 0.15 and i > 0 and i < steps - 1:
                back = random.randint(30, 100)
                await page.evaluate(f"window.scrollBy(0, -{back})")
                await asyncio.sleep(random.uniform(0.3, 0.8))

    # ------------------------------------------------------------------
    # 4. 验证码检测
    # ------------------------------------------------------------------
    async def detect_captcha(self, page) -> bool:
        """
        检测页面是否出现验证码相关元素。
        Returns True 表示检测到验证码。

        检测策略：
          1. HTML 文本 / title 关键词匹配
          2. DOM 选择器匹配（iframe、特定 class / id）
        """
        try:
            content = await page.content()
            title = await page.title()

            # 关键词检测
            for kw in self.cfg.captcha_keywords:
                if kw.lower() in content.lower() or kw in title:
                    self.stats.record_captcha()
                    print(f"[AntiDetect] ⚠️ 验证码检测到关键词: {kw}")
                    return True

            # DOM 结构检测（常见验证码容器）
            captcha_selectors = [
                "iframe[src*='captcha']",
                "iframe[src*='验证码']",
                ".geetest_panel",
                "#captcha",
                "[class*='captcha']",
                "[class*='slider']",
                "[class*='verify']",
                "[id*='captcha']",
                "[id*='tcaptcha']",
                ".geetest_panel",
                ".geetest_item",
                "canvas",
                ".nc_wrapper",
            ]
            for sel in captcha_selectors:
                try:
                    el = await page.query_selector(sel)
                    if el:
                        visible = await el.is_visible()
                        if visible:
                            self.stats.record_captcha()
                            print(f"[AntiDetect] ⚠️ 验证码检测到元素: {sel}")
                            return True
                except Exception:
                    pass

            return False

        except Exception as e:
            print(f"[AntiDetect] 检测验证码时出错: {e}")
            return False

    # ------------------------------------------------------------------
    # 5. 封号预警逻辑
    # ------------------------------------------------------------------
    async def check_warning(self, page) -> str:
        """
        执行异常检测，返回当前状态：
          - "normal"   : 一切正常
          - "warning"  : 触发预警（错误率高 / 频繁验证码 / 动作过快）
          - "paused"   : 已自动降速/暂停

        触发条件：
          - 日动作超 daily_action_limit
          - 验证码出现频繁（captchas 过多）
          - burst 动作数超过阈值
          - 连续失败过多
        """
        t = self.cfg.warning_thresholds
        state = "normal"
        reasons: list[str] = []

        # 条件1: 动作数超限
        if self.stats.total >= self.cfg.daily_action_limit:
            reasons.append(f"日动作数 {self.stats.total} >= {self.cfg.daily_action_limit}")
            state = "paused"

        # 条件2: 验证码出现
        if self.stats.captchas >= 3:
            reasons.append(f"验证码出现 {self.stats.captchas} 次")
            state = "paused"

        # 条件3: 错误率
        er = self.stats.error_rate()
        if er >= t["error_rate_pct"]:
            reasons.append(f"错误率 {er:.1f}% >= {t['error_rate_pct']}%")
            if state != "paused":
                state = "warning"

        # 条件4: burst
        burst = self.stats.burst_count(window=t.get("burst_window_sec", 30))
        if burst >= t["action_burst"]:
            reasons.append(f"动作 burst {burst} >= {t['action_burst']}")
            if state != "paused":
                state = "warning"

        # 条件5: 连续失败
        cf = self.stats.consecutive_failures()
        if cf >= t["consecutive_failures"]:
            reasons.append(f"连续失败 {cf} >= {t['consecutive_failures']}")
            if state != "paused":
                state = "warning"

        if state != "normal":
            msg = f"[AntiDetect] 🚨 预警触发: {'; '.join(reasons)}"
            print(msg)
            await self._notify(msg)

            if state == "paused":
                # 自动暂停 5~15 分钟
                pause_sec = random.randint(300, 900)
                self._pause_until = time.time() + pause_sec
                self.stats = ActionStats()  # 重置统计
                pause_msg = f"[AntiDetect] ⏸️ 自动暂停 {pause_sec//60} 分钟"
                print(pause_msg)
                await self._notify(pause_msg)
                state = "paused"

        self._state = state
        return state

    # ------------------------------------------------------------------
    # 6. Playwright Stealth 配置
    # ------------------------------------------------------------------
    async def apply_stealth(self, page):
        """
        对 Playwright Page 应用全套 stealth 配置：
          - 注入 JS 补丁（隐藏 webdriver 标识）
          - 禁止 automation 扩展
        """
        try:
            await page.add_init_script(STEALTH_JS)
            # 额外：拦截 automation 扩展请求
            await page.route(
                re.compile(r"extension.*(webdriver|automation)"),
                lambda route: route.abort(),
            )
            print("[AntiDetect] ✅ Stealth 配置已应用")
        except Exception as e:
            print(f"[AntiDetect] ⚠️ Stealth 配置失败: {e}")

    # ------------------------------------------------------------------
    # 辅助：批量操作包装器（自动注入 delay）
    # ------------------------------------------------------------------
    async def act(self, page, fn, *args, **kwargs):
        """
        在执行 fn 之前自动插入随机延迟，并在执行后检测验证码和预警。

        示例:
          await ad.act(page, some_action_function, arg1, arg2)
        """
        await self.random_delay()
        try:
            result = await fn(*args, **kwargs)
        except Exception as e:
            self.stats.record_error()
            raise

        # 执行后检查验证码
        if await self.detect_captcha(page):
            print("[AntiDetect] ⚠️ 检测到验证码，当前操作已暂停等待处理")
            await self._notify("检测到验证码，需要人工处理！")

        # 执行后检查预警
        state = await self.check_warning(page)
        if state == "paused":
            print("[AntiDetect] ⏸️ 进入暂停状态，等待自动恢复...")

        return result


# ---------------------------------------------------------------------------
# 便捷入口函数（直接导入使用）
# ---------------------------------------------------------------------------
_default_cfg_path = str(
    Path(__file__).parent.parent / "config" / "anti_detect.json"
)

_ad: Optional[AntiDetect] = None


def get_ad() -> AntiDetect:
    global _ad
    if _ad is None:
        _ad = AntiDetect(_default_cfg_path)
    return _ad


async def random_delay() -> float:
    return await get_ad().random_delay()


async def random_delay_short() -> float:
    """
    短随机延迟（0.5-2s），用于页面操作间的快速停顿。
    比 random_delay() 更保守，避免被识别为机器人行为。
    """
    delay = random.uniform(0.5, 2.0)
    await asyncio.sleep(delay)
    return delay


async def simulate_mouse(page, x: int, y: int, **kw) -> None:
    await get_ad().simulate_mouse(page, x, y, **kw)


async def simulate_scroll(page, **kw) -> None:
    await get_ad().simulate_scroll(page, **kw)


async def detect_captcha(page) -> bool:
    return await get_ad().detect_captcha(page)


async def apply_stealth(page) -> None:
    await get_ad().apply_stealth(page)


# ---------------------------------------------------------------------------
# __main__ — 快速测试
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("AntiDetect 模块自检...")
    cfg = AntiDetectConfig()
    print(f"  默认延迟区间: [{cfg.delay_min}, {cfg.delay_max}]s")
    print(f"  正态分布 sigma: {cfg.delay_sigma}")
    print(f"  验证码关键词: {cfg.captcha_keywords[:5]}")
    print(f"  预警阈值: {cfg.warning_thresholds}")
    print("自检完成。")
