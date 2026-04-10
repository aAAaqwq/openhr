# boss-greet — Boss直聘主动打招呼模块

> OpenHR M2 模块Skill，负责自动遍历候选人列表、筛选合适人才、发送个性化打招呼消息。

---

## 触发条件

当满足以下任一条件时触发本模块：

- 用户发送：「打招呼」「开始招聘」「自动打招呼」「跑一下打招呼」
- 定时任务触发（每日 09:00 / 14:00，默认）
- API 调用：`POST /openhr/greet` 或 CLI 命令

---

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 安装 Playwright | `pip3 install playwright` | `python3 -c "import playwright"` |
| 3 | 安装 Chromium | `python3 -m playwright install chromium` | 浏览器二进制文件存在 |
| 4 | 无界面服务器装 xvfb | `sudo apt install xvfb` | `which xvfb-run` 有输出 |
| 5 | 已完成 boss-login 登录 | `python3 scripts/boss_login.py --check` | 输出"已登录" |

### 内部模块依赖

| 模块 | 路径 | 用途 |
|------|------|------|
| 登录模块 | `scripts/boss_login.py` | 获取已登录 Playwright Page |
| 风控模块 | `scripts/anti_detect.py` | 随机间隔、验证码检测、封号预警 |
| 知识库 | `scripts/knowledge_base.py` | 打招呼话术、岗位匹配 |

### 第三方依赖

| 包 | 用途 |
|----|------|
| `playwright` | 浏览器自动化（遍历候选人列表、点击打招呼按钮） |

### 运行命令

```bash
# 有图形界面
python3 scripts/boss_greet.py

# 无界面服务器
xvfb-run -a python3 scripts/boss_greet.py --dry-run   # 先测试
xvfb-run -a python3 scripts/boss_greet.py --max-greets 5  # 正式跑5人
```

---

## 输入（Input）

### 方式一：CLI 参数

```bash
python3 scripts/boss_greet.py \
  --max-greets 100 \
  --position-id pos_1 \
  --filter-education 本科 \
  --filter-experience 3年 \
  --filter-skills Python,Redis \
  --dry-run
```

### 方式二：代码调用

```python
import asyncio
from scripts.boss_greet import BossGreetRunner

runner = BossGreetRunner(
    max_daily_greets=100,      # 每日上限，默认100
    position_id="pos_1",        # 指定岗位ID，不指定则用知识库所有岗位
    filters={
        "education": "本科及以上",
        "experience": "3-5年",
        "skills": ["Python", "Django", "Redis"],
    },
    dry_run=False,             # True=只模拟不实际发消息
)

asyncio.run(runner.run())
```

### 输入字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `max_daily_greets` | int | 否 | 每日打招呼上限，默认100 |
| `position_id` | str | 否 | 指定岗位ID，不指定则遍历知识库所有岗位匹配 |
| `filters` | dict | 否 | 额外筛选条件 |
| `filters.education` | str | 否 | 学历要求，如 "本科及以上" |
| `filters.experience` | str | 否 | 工作经验要求，如 "3-5年" |
| `filters.skills` | list[str] | 否 | 必备技能列表 |
| `filters.exclude_keywords` | list[str] | 否 | 排除关键词 |
| `dry_run` | bool | 否 | True=只跑流程不实际打招呼，用于测试 |

---

## 执行步骤

### Step 1 — 初始化

1. 加载 `config/templates.json` 打招呼模板
2. 加载 `data/greet_count.json` 读取当日已打招呼次数
3. 初始化 `KnowledgeBase`（加载岗位需求和话术）
4. 初始化 `AntiDetect`（加载风控配置）

### Step 2 — 打开Boss直聘候选人列表页

1. 调用 `boss_login.py` 的 `get_logged_in_page()` 获取已登录 Page
   - 若未登录，生成二维码等待扫码（阻塞）
2. 导航到候选人推荐页：`https://www.zhipin.com/web/boss/recommend`

### Step 3 — 遍历候选人列表

Boss 是 SPA + 虚拟滚动，采用 **滚动→抽取→处理** 循环：

1. 滚动页面触发下一批候选人加载
2. 抽取当前屏所有候选人卡片文本
3. 对每张卡片解析结构化信息（姓名、技能、工作年限、学历、期望职位）
4. 按以下条件过滤：
   - 岗位匹配分数 > 阈值（知识库 `match_candidate_to_position`）
   - 学历要求满足（若设置了 `filters.education`）
   - 工作经验满足（若设置了 `filters.experience`）
   - 必备技能命中（若设置了 `filters.skills`）
   - 未在当日已打招呼名单中
5. 满足条件 → 点击「打招呼」按钮 → 发送个性化消息
6. 不满足 → 跳过，记录原因

### Step 4 — 发送个性化打招呼

1. 从知识库获取一条打招呼模板（`kb.get_greeting`）
2. 提取候选人关键信息填充变量：
   - `{name}` → 候选人姓名
   - `{position}` → 目标岗位
   - `{skill}` → 匹配到的技能关键词
   - `{company}` → 公司名称（从配置读取）
   - `{salary}` → 薪资范围
   - `{education}` → 学历
3. 将填充后的话术填入打招呼输入框，点击发送

### Step 5 — 风控保护

每次操作后：

1. 调用 `anti_detect.random_delay()` — 随机停顿 5~15 秒
2. 调用 `anti_detect.detect_captcha()` — 检测验证码
3. 调用 `anti_detect.check_warning()` — 检查封号预警
4. 若检测到验证码或预警 → 暂停，等待人工处理

### Step 6 — 次数控制

- 每日打招呼上限存储在 `data/greet_count.json`
- 结构：`{"date": "2026-04-07", "count": 42, "greeted_ids": ["uid_xxx", "uid_yyy"]}`
- 达到上限自动停止，输出报告

---

## 输出（Output）

### 返回值结构

```python
@dataclass
class GreetResult:
    total_candidates: int      # 遍历到的候选人总数
    matched: int               # 匹配成功数
    greeted: int               # 实际打招呼数
    skipped: int               # 跳过数（不符合条件）
    captchas_detected: int     # 检测到验证码次数
    reached_limit: bool        # 是否达到每日上限
    daily_count: int           # 当日累计打招呼数
    duration_seconds: float    # 总耗时（秒）
    errors: list[str]           # 错误列表
```

### 日志输出示例

```
[ BossGreet ] ========== 打招呼任务开始 ==========
[ BossGreet ] 当日已打招呼: 12 / 100
[ BossGreet ] 候选人列表页加载中...
[ BossGreet ] 滚动批次 1/5，已加载 20 个候选人
[ BossGreet ] 候选人: 张三 | 匹配岗位: Python后端(92分) | 打招呼 ✓
[ BossGreet ] 候选人: 李四 | 匹配岗位: 无 | 跳过（不匹配）
[ BossGreet ] 随机停顿 8.3s...
[ BossGreet ] 候选人: 王五 | 匹配岗位: Python后端(75分) | 打招呼 ✓
...
[ BossGreet ] ========== 任务完成 ==========
[ BossGreet ] 总耗时: 45.2s | 打招呼: 8 | 跳过: 12 | 累计: 20/100
```

---

## 配置文件

### `config/templates.json`

包含至少 8 个不同风格的打招呼模板，支持变量插值。

### `config/anti_detect.json`

风控参数（由 `anti_detect.py` 使用）：
```json
{
  "delay_min": 5.0,
  "delay_max": 15.0,
  "daily_action_limit": 200,
  "captcha_keywords": ["验证码", "安全验证", "滑动验证"]
}
```

### `data/greet_count.json`（运行时生成）

```json
{
  "date": "2026-04-07",
  "count": 42,
  "greeted_ids": ["geek_xxx", "geek_yyy"]
}
```

---

## CLI 用法

```bash
# 标准运行（使用知识库中的岗位配置）
python3 scripts/boss_greet.py

# 指定岗位ID
python3 scripts/boss_greet.py --position-id pos_1

# 带筛选条件
python3 scripts/boss_greet.py \
  --filter-education 本科 \
  --filter-experience 3-5年 \
  --filter-skills Python,Django,Redis

# 限制打招呼次数
python3 scripts/boss_greet.py --max-greets 50

# 干跑（不实际打招呼，用于测试流程）
python3 scripts/boss_greet.py --dry-run

# 查看帮助
python3 scripts/boss_greet.py --help
```

---

## 验收标准

| 标准 | 说明 |
|------|------|
| ✅ 遍历候选人列表 | 滚动加载 + 虚拟滚动节点处理 |
| ✅ 按岗位需求筛选 | 调用 `match_candidate_to_position`，评分>阈值才打招呼 |
| ✅ 个性化打招呼 | 基于模板 + 候选人信息变量填充 |
| ✅ 每日次数限制 | `greet_count.json` 计数，达到上限自动停止 |
| ✅ 操作间隔随机化 | 调用 `anti_detect.random_delay()`，每次操作后调用 |
| ✅ 完整注释 + 错误处理 | 所有函数有类型注解和中文注释，异常捕获完整 |

---

## 错误处理

| 错误类型 | 处理策略 |
|------|------|
| 登录态失效 | 重新触发扫码登录流程 |
| 验证码出现 | 暂停任务，通知人工处理，截图保存 |
| 页面结构变更 | 截图 + 导出 HTML 片段到 `data/debug/` |
| 网络超时 | 重试 3 次，每次间隔 5s |
| 打招呼被拒（风控） | 调用 `anti_detect.check_warning()` 自动降速 |
| 每日上限达到 | 正常结束，输出报告 |

---

## 注意事项

1. **不要修改已有模块**（`boss_login.py`、`anti_detect.py`、`knowledge_base.py`）
2. 本模块只操作候选人推荐列表页，不进入简历详情页
3. 所有选择器优先使用语义/文本属性，不依赖动态 class
4. 每日计数按自然日重置，跨天后自动清零
5. 调试时可使用 `--dry-run` 模式，不实际发送消息

---

*Module: M2 主动打招呼 | Author: 小code | Updated: 2026-04-07*
