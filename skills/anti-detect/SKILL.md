# anti-detect — 风控对抗模块

## 模块概述

`anti_detect.py` 是 OpenHR 的**风控对抗基础模块**，为所有自动化操作提供：

- 随机操作间隔（正态分布）
- 鼠标轨迹模拟（贝塞尔曲线 + ease-in-out）
- 页面滚动行为模拟（分段滚动 + 偶有回滚）
- 验证码检测（关键词 + DOM 选择器双重策略）
- 封号预警（动作数、错误率、burst、连续失败多维度检测）
- Playwright stealth 配置（隐藏 `webdriver` 标识及各类浏览器指纹）

**定位**：供 `boss_greet.py`、`boss_login.py`、`chat_engine.py` 等业务脚本调用，本身不执行业务逻辑。

---

## 触发条件

以下场景**必须使用**此模块：

| 场景 | 使用功能 |
|------|---------|
| 任何页面点击操作前 | `random_delay()` + `simulate_mouse()` |
| 页面滚动前 | `simulate_scroll()` |
| 发送消息前后 | `random_delay()` + `detect_captcha()` |
| 每个业务动作完成后 | `check_warning()` |
| Playwright Page 创建后首次导航前 | `apply_stealth()` |
| 批量任务入口 | `act()` 包装器 |

---

## 核心功能

### 1. 随机操作间隔

**配置来源**：`config/anti_detect.json` → `delay_min` / `delay_max` / `delay_sigma`

```python
# 默认值
delay_min = 5.0      # 秒
delay_max = 15.0      # 秒
delay_sigma = 2.5    # 正态分布标准差
```

**实现**：`random.gauss(mean, sigma)` 生成正态分布延迟，钳制到 `[delay_min, delay_max]` 区间。暂停状态下自动等待恢复。

```python
await ad.random_delay()  # 返回实际睡眠秒数
```

---

### 2. 鼠标轨迹模拟

使用**三次贝塞尔曲线**，配合 ease-in-out 加速-减速曲线，模拟人类鼠标移动：

- `steps`：8~16 段（可配置，默认自动）
- 起点随机（viewport 内 50-300px 范围）
- 控制点随机偏移，构造自然弧线
- 终点微量随机偏移（±3px），避免每次正中圆心
- 目标悬停前随机停顿 200~900ms

```python
await ad.simulate_mouse(page, target_x=500, target_y=300, steps=0)
# steps=0 表示自动随机 8~16 段
```

**相关配置**（`config/anti_detect.json` → `mouse`）：
```json
{
  "bezier_steps_min": 8,
  "bezier_steps_max": 16,
  "hover_before_ms_min": 200,
  "hover_before_ms_max": 900
}
```

---

### 3. 页面滚动行为模拟

分多步小步滚动，每步随机停顿，模拟真实用户"往下看一段"的习惯：

- 总距离随机：`scroll_min` ~ `scroll_max` px（默认 300~900）
- 分 3~7 步完成（随机）
- 每步停顿：`scroll_pause` 秒区间（默认 0.5~2.0s）
- **15% 概率**回滚 30~100px（模拟"看漏了回头"）

```python
await ad.simulate_scroll(page, distance=None, steps=0)
# distance=None 表示随机
```

---

### 4. 验证码检测

**双重检测策略**：

**A. 关键词匹配**（`captcha_keywords`）：
```python
# 默认关键词（部分）
["验证码", "安全验证", "拼图", "滑动验证", "请在下方",
 "captcha", "verify", "验证", "人机验证", "请完成验证",
 "tcaptcha", "geetest"]
```

**B. DOM 选择器匹配**（13 种常见验证码容器）：
```python
# 包括 iframe、.geetest_panel、#captcha、[class*='captcha']、
# [class*='slider']、[class*='verify']、canvas、.nc_wrapper 等
```

检测到验证码后：
- 记录 `stats.captchas += 1`
- 打印警告日志
- 发送通知（`_notify()`）
- 返回 `True`

```python
detected = await ad.detect_captcha(page)  # True = 检测到
```

---

### 5. 封号预警

多维度异常检测，基于 `ActionStats` 统计数据：

| 预警维度 | 阈值（默认） | 触发结果 |
|---------|------------|---------|
| 日动作数超限 | `daily_action_limit=200` | `paused` |
| 验证码出现次数 ≥3 | `captchas >= 3` | `paused` |
| 错误率 | `error_rate_pct=30%` | `warning` |
| 30s 内 burst 动作数 | `action_burst=10` | `warning` |
| 连续失败次数 | `consecutive_failures=3` | `warning` |

**paused 状态**：自动暂停 5~15 分钟，重置统计数据。

```python
state = await ad.check_warning(page)
# 返回: "normal" | "warning" | "paused"
```

---

### 6. Playwright Stealth 配置

注入 8 项 JS 补丁（`apply_stealth()`）：

| # | 补丁项 | 说明 |
|---|--------|------|
| 1 | `navigator.webdriver = undefined` | 隐藏自动化标识 |
| 2 | `navigator.languages` 伪造 | 恢复被 Playwright 修改的值 |
| 3 | `navigator.plugins` 伪造 | 返回 `[1,2,3,4]` |
| 4 | `navigator.hardwareConcurrency` | 随机返回 8 或 16 |
| 5 | `navigator.deviceMemory` | 随机返回 4 或 8 |
| 6 | `chrome.runtime` 对象抹除 | 伪造 `chrome.runtime = {}` |
| 7 | `permissions.query` 拦截 | 伪造 notifications 权限 |
| 8 | WebGL vendor/renderer 伪造 | 返回 Intel 显卡信息 |
| 9 | AudioContext decodeAudioData | 不做修改（占位） |
| 10 | `mediaDevices.enumerateDevices` | 随机去掉一个设备 |

```python
await ad.apply_stealth(page)  # 在页面导航前调用
```

---

## 调用方式

### 方式 1：类封装（推荐用于复杂场景）

```python
from scripts.anti_detect import AntiDetect

# 初始化（加载配置文件或使用默认）
ad = AntiDetect(config_path="config/anti_detect.json")

# 1. 应用 stealth（每个新 Page 只做一次）
await ad.apply_stealth(page)

# 2. 业务操作前注入随机延迟
await ad.random_delay()

# 3. 鼠标移动
await ad.simulate_mouse(page, target_x=500, target_y=300)

# 4. 页面滚动
await ad.simulate_scroll(page)

# 5. 操作后检测验证码
if await ad.detect_captcha(page):
    print("需要人工处理验证码")

# 6. 检查预警状态
state = await ad.check_warning(page)
if state == "paused":
    print("自动暂停中，等待恢复...")
```

### 方式 2：`act()` 包装器（推荐用于批量任务）

自动串联：随机延迟 → 执行 fn → 验证码检测 → 预警检查

```python
async def greet_candidate(page, candidate_id):
    # 业务逻辑
    await page.click(f"[data-id='{candidate_id}']")
    await page.fill("textarea", f"您好，{candidate_id}，我们正在招聘...")

await ad.act(page, greet_candidate, page, candidate_id="12345")
```

### 方式 3：模块级便捷函数（简单场景）

```python
from scripts.anti_detect import (
    random_delay,
    simulate_mouse,
    simulate_scroll,
    detect_captcha,
    apply_stealth,
)

await random_delay()
await apply_stealth(page)
await simulate_mouse(page, 500, 300)
await simulate_scroll(page)
detected = await detect_captcha(page)
```

---

## 配置说明

**文件**：`config/anti_detect.json`

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `delay_min` | float | 5.0 | 最小操作间隔（秒） |
| `delay_max` | float | 15.0 | 最大操作间隔（秒） |
| `delay_sigma` | float | 2.5 | 正态分布 sigma |
| `daily_action_limit` | int | 200 | 每日动作上限 |
| `scroll_min` | int | 300 | 最小滚动距离（px） |
| `scroll_max` | int | 900 | 最大滚动距离（px） |
| `scroll_pause` | tuple | [0.5, 2.0] | 滚动间停顿区间（秒） |
| `captcha_keywords` | list[str] | 见上文 | 验证码检测关键词 |
| `warning_thresholds.error_rate_pct` | int | 30 | 错误率预警阈值（%） |
| `warning_thresholds.consecutive_failures` | int | 3 | 连续失败预警阈值 |
| `warning_thresholds.action_burst` | int | 10 | burst 动作数阈值 |
| `warning_thresholds.burst_window_sec` | int | 30 | burst 统计窗口（秒） |
| `mouse.bezier_steps_min` | int | 8 | 鼠标轨迹最小段数 |
| `mouse.bezier_steps_max` | int | 16 | 鼠标轨迹最大段数 |
| `mouse.hover_before_ms_min` | int | 200 | 悬停前停顿最小（ms） |
| `mouse.hover_before_ms_max` | int | 900 | 悬停前停顿最大（ms） |
| `notify.enabled` | bool | false | 是否启用通知 |
| `notify.feishu_webhook` | str | "" | 飞书 Webhook URL |
| `notify.telegram_bot_token` | str | "" | Telegram Bot Token |
| `notify.telegram_chat_id` | str | "" | Telegram Chat ID |

---

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 安装 numpy | `pip3 install numpy` | `python3 -c "import numpy"` |

> **注意**：`playwright` 由调用方（boss-greet/chat-engine 等）安装，本模块接收 `page` 对象作为参数，不直接 import playwright。`playwright-stealth` 不需要安装（代码使用自实现 JS 补丁）。

### 第三方依赖

| 包 | 用途 | 说明 |
|----|------|------|
| `numpy` | 贝塞尔曲线计算 | 代码中实际用 `math` 模块实现，numpy 为顶层 import 但未调用，可忽略 |
| `aiohttp` | 可选 | 通知 Webhook 推送（默认未启用） |

### 无需安装

| 包 | 说明 |
|----|------|
| `playwright` | 由调用方传入 page 对象 |
| `playwright-stealth` | 代码使用自实现 JS 补丁，不需要此包 |
