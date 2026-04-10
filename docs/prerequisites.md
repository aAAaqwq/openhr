# OpenHR 前置环境安装指南

> 更新时间：2026-04-10
> 所有 Skill 运行前必须完成本文档中的步骤

---

## 1. 系统要求

| 项目 | 最低版本 | 推荐版本 |
|------|---------|---------|
| Python | 3.10+ | 3.12+ |
| 操作系统 | Linux / macOS | Ubuntu 22.04+ |
| 磁盘空间 | 500MB（含浏览器） | 1GB |

> Python 3.10+ 是因为代码中使用了 `str | Path` 等联合类型语法。

### 检查 Python 版本

```bash
python3 --version
# 预期输出: Python 3.10.x 或更高
```

---

## 2. 核心依赖安装

### 2.1 安装 Python 包

```bash
cd ~/clawd/projects/openhr

# 所有模块的核心依赖（一次装齐）
pip3 install playwright requests

# anti-detect 模块的额外依赖（贝塞尔曲线计算）
pip3 install numpy
```

> **注意**：`knowledge-base` 模块是纯标准库，不需要额外 pip 安装。

### 2.2 安装 Chromium 浏览器

```bash
python3 -m playwright install chromium
```

安装路径：`~/.cache/ms-playwright/chromium-*/chrome-linux/chrome`

验证安装：

```bash
python3 -c "from playwright.sync_api import sync_playwright; print('OK')"
# 预期输出: OK
```

---

## 3. 无头服务器（Headless Server）配置

如果你的服务器**没有图形界面**（大部分云服务器/VPS），需要额外配置：

### 3.1 安装 xvfb（虚拟帧缓冲）

```bash
# Ubuntu/Debian
sudo apt install xvfb

# CentOS/RHEL
sudo yum install xorg-x11-server-Xvfb
```

### 3.2 使用 xvfb-run 运行脚本

```bash
# 方式一：每次手动用 xvfb-run 包裹（推荐）
xvfb-run -a python3 scripts/boss_login.py

# 方式二：启动长期运行的虚拟显示器
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
python3 scripts/boss_login.py
```

### 3.3 验证 xvfb

```bash
xvfb-run python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    page.goto('https://www.baidu.com')
    print(f'Title: {page.title()}')
    browser.close()
"
# 预期输出: Title: 百度一下，你就知道
```

> **为什么不用 headless=True？** Boss直聘的反爬检测会识别 headless 模式，必须用 `headless=False` + `xvfb` 模拟真实浏览器环境。

---

## 4. 环境变量配置

### 4.1 LLM API Key（必须）

```bash
# GLM-5 API Key（通过智谱AI开放平台获取）
export ZAI_API_KEY="your_api_key_here"

# 写入 .bashrc 永久生效
echo 'export ZAI_API_KEY="your_api_key_here"' >> ~/.bashrc
source ~/.bashrc
```

验证：

```bash
python3 -c "
import os
from openai import OpenAI
client = OpenAI(
    api_key=os.environ['ZAI_API_KEY'],
    base_url='https://open.bigmodel.cn/api/paas/v4'
)
resp = client.chat.completions.create(
    model='glm-5-plus',
    messages=[{'role': 'user', 'content': 'Hi'}],
    max_tokens=10
)
print(resp.choices[0].message.content)
"
```

### 4.2 可选环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `DISPLAY` | X11 显示器地址（xvfb 模式） | `:99` |
| `OPENROUTER_API_KEY` | OpenRouter LLM 备用 Key | 无 |

---

## 5. 配置文件检查

运行前确保这些配置文件存在：

```bash
cd ~/clawd/projects/openhr
ls config/
# 预期输出:
# anti_detect.json  feishu.json  filters.json  llm.json  templates.json
```

### 关键配置项

| 文件 | 必须手动配置的字段 | 说明 |
|------|-------------------|------|
| `config/llm.json` | `api_key_env` | 指向环境变量名（默认 `ZAI_API_KEY`） |
| `config/feishu.json` | `app_secret`, `app_token`, `table_id` | 飞书多维表格凭证 |
| `config/anti_detect.json` | 无需修改 | 默认参数即可使用 |

---

## 6. 数据目录初始化

```bash
cd ~/clawd/projects/openhr

# 确保数据目录存在
mkdir -p data/cookies
mkdir -p data/chat_logs
mkdir -p data/knowledge
mkdir -p data/templates
```

---

## 7. 快速验证（一键测试）

完成以上所有步骤后，运行以下命令验证环境：

```bash
cd ~/clawd/projects/openhr

# 1. 检查 Python 版本
python3 --version

# 2. 检查依赖包
python3 -c "import playwright, requests, numpy; print('All deps OK')"

# 3. 检查 Chromium
python3 -m playwright install --dry-run chromium 2>&1 || echo "Chromium needs install"

# 4. 检查环境变量
python3 -c "import os; print('ZAI_API_KEY:', 'SET' if os.environ.get('ZAI_API_KEY') else 'NOT SET')"

# 5. 检查配置文件
ls config/*.json

# 6. 测试登录模块（xvfb 模式）
xvfb-run -a python3 scripts/boss_login.py --check
```

---

## 各 Skill 模块特有依赖速查

| Skill | pip 包 | 系统包 | 环境变量 | 备注 |
|-------|--------|--------|---------|------|
| boss-login | playwright | xvfb（无界面服务器） | 无 | 基础模块 |
| boss-greet | playwright | xvfb | 无 | 依赖 boss-login |
| anti-detect | numpy | xvfb | 无 | 依赖 playwright（间接） |
| chat-engine | requests | xvfb | ZAI_API_KEY | 依赖 boss-login + LLM |
| resume-parser | playwright, requests | 无 | ZAI_API_KEY | 依赖 LLM 评分 |
| knowledge-base | 无 | 无 | 无 | 纯标准库 |

---

*老王出品 — 2026-04-10 | 装不好环境别来找我*
