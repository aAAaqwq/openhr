# Boss 直聘登录模块 (boss-login)

> Skill 名称: `boss-login`  
> 所属模块: OpenHR c1  
> 文件路径: `scripts/boss_login.py`  
> 触发条件: 当需要确保 Boss 直聘处于登录态时调用  
> 更新时间: 2026-04-07

---

## 概述

本模块负责 Boss 直聘招聘者账号的登录态管理，包括：
- 检测当前登录状态
- 未登录时生成二维码截图供人工扫码
- Cookie 持久化（JSON 格式）
- 登录态过期自动检测（默认 24h）

---

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 安装 Playwright | `pip3 install playwright` | `python3 -c "import playwright"` |
| 3 | 安装 Chromium | `python3 -m playwright install chromium` | `~/.cache/ms-playwright/chromium-*/chrome-linux/chrome` 存在 |
| 4 | 无界面服务器装 xvfb | `sudo apt install xvfb` | `which xvfb-run` 有输出 |

### 运行命令

```bash
# 有图形界面的机器
python3 scripts/boss_login.py

# 无界面服务器（VPS/云服务器）
xvfb-run -a python3 scripts/boss_login.py
```

### 第三方依赖

| 包 | 用途 |
|----|------|
| `playwright` | 浏览器自动化（`async_playwright`, `Browser`, `BrowserContext`, `Page`） |

> 无其他第三方依赖，其余均为 Python 标准库。

---

## 核心函数

### `check_login(page)` — 检测登录态

```python
from scripts.boss_login import check_login

is_logged_in = await check_login(page)
# True = 已登录，False = 未登录
```

**检测逻辑（多信号判断）：**

| 状态 | 检测信号 |
|------|---------|
| ✅ 已登录 | `a[href*="/web/boss/chat"]`, `a[href*="/web/boss/recommend"]`, 用户头像 |
| ❌ 未登录 | 顶部有"登录"链接，出现扫码/手机号登录 UI |

---

### `generate_qr_code(output_path=None)` — 生成二维码截图

```python
from scripts.boss_login import generate_qr_code

qr_path = await generate_qr_code()
# 返回截图路径，默认 data/cookies/boss_qr_{timestamp}.png
```

**流程：**
1. 启动有界面 Chromium（headless=False，降低被检测风险）
2. 打开招聘者登录页：`https://www.zhipin.com/web/user/?intent=1`
3. 处理可能的协议弹窗
4. 等待二维码容器渲染
5. 截图保存，通知人工扫码

**注意：** 二维码有效期约 2~5 分钟，超时需重新生成。

---

### `save_cookies(context, meta=None)` — 持久化 Cookies

```python
from scripts.boss_login import save_cookies

save_cookies(context)
# 保存到: data/cookies/boss_cookies.json
# 元数据: data/cookies/boss_cookies_meta.json
```

**存储格式：**
```json
// boss_cookies.json
[
  {
    "name": "bsns_id",
    "value": "xxx",
    "domain": ".zhipin.com",
    "path": "/",
    "expires": -1,
    "httpOnly": false,
    "secure": true,
    "sameSite": "Lax"
  }
]

// boss_cookies_meta.json
{
  "saved_at": "2026-04-07T22:00:00",
  "expiry_hours": 24,
  "cookie_count": 12
}
```

---

### `load_cookies(context)` — 加载 Cookies

```python
from scripts.boss_login import load_cookies

loaded = load_cookies(context)
# True = 加载成功且未过期
# False = 文件不存在或已过期
```

**过期检测：** 读取 `boss_cookies_meta.json` 中的 `saved_at` 时间，超过 24h 视为过期。

---

## 命令行用法

```bash
# 检测登录态，未登录则生成二维码并等待扫码
python3 scripts/boss_login.py

# 仅检查登录态（不生成二维码）
python3 scripts/boss_login.py --check

# 强制重新生成二维码
python3 scripts/boss_login.py --qr

# 指定二维码截图保存路径
python3 scripts/boss_login.py --qr --qr-output /tmp/my_qr.png
```

---

## 反检测措施

| 措施 | 说明 |
|------|------|
| `headless=False` | 有界面模式，避免被识别为自动化 |
| 固定 UA | `Chrome/124.0.0.0` on macOS |
| 固定 locale/timezone | `zh-CN` / `Asia/Shanghai` |
| stealth JS | 屏蔽 `navigator.webdriver` 等检测属性 |
| `AutomationControlled` 禁用 | `--disable-blink-features=AutomationControlled` |

详见：`references/anti-detect-guide.md`

---

## 依赖

> 详细安装步骤见 [前置条件](#前置条件) 章节。

```
playwright >= 1.40    # pip3 install playwright && python3 -m playwright install chromium
```

---

## 目录结构

```
openhr/
├── scripts/
│   └── boss_login.py          # ← 本模块
├── data/
│   └── cookies/
│       ├── boss_cookies.json  # cookie 存储（运行时生成）
│       ├── boss_cookies_meta.json
│       └── boss_qr_*.png      # 二维码截图（运行时生成）
└── skills/
    └── boss-login/
        └── SKILL.md           # ← 本文档
```

---

## 触发条件

| 场景 | 是否调用 |
|------|---------|
| 启动任何 Boss 自动化任务前 | ✅ 必须调用 |
| `boss_greet.py` 启动前 | ✅ 依赖 c1 |
| `chat_engine.py` 启动前 | ✅ 依赖 c1 |
| 任何脚本访问 Boss 页面之前 | ✅ 先调用 `load_cookies()` 尝试恢复会话 |

---

## 注意事项

1. **二维码有时效**：Boss 二维码约 2~5 分钟有效期，超时需重新生成
2. **不要 headless 长期跑**：参考 `anti-detect-guide.md`，有界面模式更稳定
3. **Cookie 过期后需重新扫码**：每次启动建议先调用 `load_cookies()` 检查
4. **扫码时不要关闭浏览器窗口**：需保持页面在二维码状态等待扫码完成
5. **登录成功后自动保存**：`main()` 流程会在检测到登录成功后自动调用 `save_cookies()`

---

## 状态码

| 返回值 | 含义 |
|--------|------|
| `True`（`check_login`） | 已登录 |
| `False`（`check_login`） | 未登录 |
| `True`（`load_cookies`） | Cookie 加载成功且未过期 |
| `False`（`load_cookies`） | Cookie 文件不存在或已过期 |
