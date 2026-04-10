# OpenHR Skills 业务流程全景图

> 总分结构 | 按执行顺序排列 | 每步可验证可交付
> 更新时间：2026-04-10

---

## 总：全局业务流程

OpenHR 的 6 个 Skills 按「依赖关系 + 执行时序」组成一条完整的招聘自动化流水线：

```
┌─────────────────────────────────────────────────────────────────┐
│                     OpenHR 招聘自动化流水线                       │
│                                                                 │
│  ① boss-login ──→ ② boss-greet ──→ ③ chat-engine              │
│     (登录态)         (打招呼)          (智能聊天)                │
│         ↑               │                  │                    │
│         │               ↓                  ↓                    │
│  ⑥ anti-detect     ④ resume-parser ──→ ⑤ knowledge-base       │
│     (风控护航)        (简历解析)          (知识库支撑)           │
│                                                                 │
│  数据出口：飞书多维表格（候选人池 + 沟通状态）                    │
└─────────────────────────────────────────────────────────────────┘
```

### 模块依赖关系

```
anti-detect ─────────────────┐（底层，所有模块依赖）
                             │
boss-login ──────────────────┤（基础，必须先完成）
       │                     │
       ├─→ boss-greet ───────┤（核心业务）
       │       │             │
       ├─→ chat-engine ──────┤（核心业务）
       │       │             │
       └─→ resume-parser ────┘（数据出口）
               │
           knowledge-base（话术/岗位供给，被 greet/chat 调用）
```

### 一次完整招聘的执行顺序

```
步骤1: boss-login     → 获取登录态（人工扫码 / Cookie 恢复）
步骤2: boss-greet     → 遍历推荐牛人，筛选匹配，发送个性化打招呼
步骤3: chat-engine    → 每15分钟轮询聊天列表，LLM 自动跟进
步骤4: resume-parser  → 候选人回复后提取简历，写入飞书表格
全程:  anti-detect    → 风控护航（随机间隔/验证码检测/封号预警）
全程:  knowledge-base → 供给话术模板 + 岗位匹配规则
```

---

## 分：6 个 Skill 详细业务流程

---

### Skill 1: boss-login（登录管理）

**定位**：流水线的第一步，所有操作的前提

#### 执行步骤

| 步骤 | 动作 | 输入 | 输出 | 验证方法 |
|------|------|------|------|---------|
| 1.1 | 启动浏览器 | — | Playwright Browser Context | 浏览器窗口可见 |
| 1.2 | 注入反检测补丁 | anti_detect 配置 | stealth JS 已注入 | `navigator.webdriver === undefined` |
| 1.3 | 加载本地 Cookie | `data/cookies/boss_cookies.json` | Cookie 写入 Context | 文件存在且未过期（24h 内） |
| 1.4 | 打开 Boss 首页 | `https://www.zhipin.com/` | 页面加载完成 | HTTP 200 |
| 1.5 | **检测登录态** | 页面 DOM | `True` / `False` | 检查 `/web/boss/chat` 链接是否存在 |
| 1.6a | ✅ 已登录 → 保存 Cookie | Context | `boss_cookies.json` 更新 | 文件写入成功 |
| 1.6b | ❌ 未登录 → 生成二维码 | `zhipin.com/web/user/?intent=1` | `data/cookies/boss_qr_*.png` | 截图文件存在 |
| 1.7 | 等待扫码 🔴 | — | 登录成功信号 | 页面出现招聘者导航元素 |
| 1.8 | 保存 Cookie | Context | `boss_cookies.json` + `boss_cookies_meta.json` | 文件存在，meta 含 `saved_at` |

#### 交付物

```bash
data/cookies/boss_cookies.json        # Cookie 数据
data/cookies/boss_cookies_meta.json   # 元数据（保存时间、过期时间）
scripts/boss_login.py                 # 脚本本体
skills/boss-login/SKILL.md            # Skill 文档
```

#### 关键代码调用

```python
from scripts.boss_login import check_login, load_cookies, save_cookies, generate_qr_code

# 流程
loaded = load_cookies(context)           # 步骤 1.3
page.goto("https://www.zhipin.com/")    # 步骤 1.4
is_logged_in = await check_login(page)   # 步骤 1.5
if not is_logged_in:
    qr_path = await generate_qr_code()  # 步骤 1.6b
    # ... 等待扫码 ...
save_cookies(context)                    # 步骤 1.8
```

---

### Skill 2: boss-greet（主动打招呼）

**定位**：核心业务模块，每天自动筛选候选人并发送打招呼

**前置依赖**：boss-login（必须已登录）+ anti-detect + knowledge-base

#### 执行步骤

| 步骤 | 动作 | 输入 | 输出 | 验证方法 |
|------|------|------|------|---------|
| 2.1 | 初始化 | `config/templates.json`, `data/greet_count.json` | Runner 实例 | 日志打印当前计数 |
| 2.2 | 获取已登录 Page | boss-login | Playwright Page | Page 可访问 Boss 站点 |
| 2.3 | 导航到推荐牛人页 | URL: `/web/boss/recommend` | 页面加载完成 | 候选人卡片出现 |
| 2.4 | 滚动加载候选人 | anti_detect.simulate_scroll | 当前屏候选人卡片文本 | 卡片数 > 0 |
| 2.5 | 解析候选人卡片 | 卡片文本 | 结构化信息（姓名/技能/学历/经验） | JSON 字段非空 |
| 2.6 | 岗位匹配评分 | knowledge_base.match_candidate_to_position | 匹配分数 (0-100) | 分数 > 阈值 |
| 2.7 | 生成个性化打招呼 | kb.get_greeting + 模板变量填充 | 最终打招呼文本 | 文本中 `{name}` 已替换 |
| 2.8 | 点击打招呼按钮 | page.get_by_role("button", name="打招呼") | 消息发送成功 | 无报错 |
| 2.9 | 风控检查 | anti_detect.detect_captcha + check_warning | "normal" / "warning" / "paused" | 状态为 normal |
| 2.10 | 随机等待 | anti_detect.random_delay | 等待 5-15s | 日志打印等待秒数 |
| 2.11 | 更新计数 | `data/greet_count.json` | count + 1 | 文件更新 |
| 2.12 | 循环或结束 | count < max && 无更多候选人 | GreetResult | 返回统计报告 |

#### 每日计数格式

```json
{
  "date": "2026-04-10",
  "count": 42,
  "greeted_ids": ["geek_xxx", "geek_yyy"]
}
```

#### 交付物

```bash
scripts/boss_greet.py           # 脚本本体
config/templates.json           # 打招呼模板（至少8个变体）
config/filters.json             # 筛选条件
data/greet_count.json           # 运行时计数
skills/boss-greet/SKILL.md     # Skill 文档
```

#### 关键代码调用

```python
from scripts.boss_greet import BossGreetRunner

runner = BossGreetRunner(max_daily_greets=50, dry_run=False)
result = await runner.run()
# result: GreetResult(total_candidates=120, matched=35, greeted=28, skipped=85)
```

---

### Skill 3: chat-engine（智能聊天跟进）

**定位**：核心业务模块，自动监控候选人回复并推进到面试确认

**前置依赖**：boss-login + anti-detect + knowledge-base + LLM API

#### 状态机流转

```
GREETING（打招呼阶段）
    │ 候选人回复
    ▼
INTEREST_CONFIRM（兴趣确认）
    │ 候选人说"感兴趣/可以/好"
    ▼
INTERVIEW_INTENT（面试意向）
    │ 候选人同意面试
    ▼
TIME_PLACE_CONFIRM（时间地点确认）
    │ 确认时间+地点
    ├──→ COMPLETED ✅（面试已确认）→ 写入飞书 + 通知管理员
    └──→ REJECTED ❌（候选人拒绝）→ 记录原因 + 归档
```

#### 执行步骤

| 步骤 | 动作 | 输入 | 输出 | 验证方法 |
|------|------|------|------|---------|
| 3.1 | 初始化引擎 | llm.json, knowledge_base, page | ChatEngine 实例 | 日志打印初始化完成 |
| 3.2 | 导航到聊天页 | URL: `/web/boss/chat` | 页面加载完成 | 聊天列表可见 |
| 3.3 | 遍历左侧聊天列表 | DOM: 会话列表 | 候选人会话列表 | 会话数 > 0 |
| 3.4 | 点击单个会话 | 会话 DOM 元素 | 聊天消息流可见 | 消息区域加载 |
| 3.5 | 读取聊天记录 | DOM: 消息区域 | 消息列表 [{sender, text, ts}] | 消息条数 > 0 |
| 3.6 | 判断是否需要回复 | 最后一条消息 sender | "需要回复" / "无需回复" | sender = "candidate" |
| 3.7 | **LLM 生成回复** | 历史消息 + 岗位需求 + 话术模式 | 回复文本 | 文本非空且合理 |
| 3.8 | 发送回复 | textarea + 发送按钮 | 消息发送成功 | 消息出现在聊天区 |
| 3.9 | 更新状态机 | 当前状态 + 候选人回复 | 新状态 | 状态合法流转 |
| 3.10 | 持久化聊天日志 | 会话数据 | `data/chat_logs/candidate_*.json` | 文件写入成功 |
| 3.11 | 面试确认处理 🟡 | COMPLETED 状态 | 通知管理员 + 更新飞书 | 通知发送成功 |
| 3.12 | 等待下一轮 | poll_interval (默认 30s) | — | 下一轮开始 |

#### 聊天日志格式

```json
{
  "candidate_id": "张三_0_1744041600",
  "candidate_name": "张三",
  "state": "COMPLETED",
  "messages": [
    {"sender": "boss", "text": "您好！...", "timestamp": "..."},
    {"sender": "candidate", "text": "感兴趣，请问薪资？", "timestamp": "..."}
  ],
  "interview_details": {"date": "周三", "time": "15:00", "method": "视频面试"},
  "llm_reply_count": 5
}
```

#### 交付物

```bash
scripts/chat_engine.py          # 脚本本体
config/llm.json                 # LLM 配置
data/chat_logs/                 # 聊天日志目录
skills/chat-engine/SKILL.md     # Skill 文档
```

#### 关键代码调用

```python
from scripts.chat_engine import ChatEngine

engine = ChatEngine(page=page, kb=kb, llm_config=llm_config, poll_interval=30)
await engine.start()   # 启动主循环（阻塞）
# 或
summary = engine.get_sessions_summary()  # 获取所有会话摘要
await engine.stop()    # 停止
```

---

### Skill 4: resume-parser（简历解析 + 飞书同步）

**定位**：数据出口模块，将候选人信息结构化并写入飞书多维表格

**前置依赖**：boss-login（从页面提取时）

#### 执行步骤

| 步骤 | 动作 | 输入 | 输出 | 验证方法 |
|------|------|------|------|---------|
| 4.1 | 获取简历文本 | 聊天窗口 / 简历详情页 / 直接文本 | 原始文本 | 文本长度 > 50 字符 |
| 4.2 | LLM 结构化提取 | 原始文本 + 提取 prompt | CandidateInfo 对象 | 必填字段（name）非空 |
| 4.3 | 字段验证 | CandidateInfo | 验证结果 | 关键字段类型正确 |
| 4.4 | 生成去重 Key | phone + name + company + title | SHA1 哈希字符串 | 长度 = 40 |
| 4.5 | **LLM 评分** | 简历文本 + 岗位需求 | score(1-10) + report(200字) | score 在合法范围 |
| 4.6 | 查询飞书去重 | dedup_key / phone | record_id 或 None | API 返回 code=0 |
| 4.7a | 不存在 → 创建记录 | fields 映射 | record_id | 飞书表格出现新行 |
| 4.7b | 已存在 → 更新记录 | record_id + fields | 更新确认 | 飞书表格字段更新 |
| 4.8 | 更新状态字段 | 跟进状态枚举 | 状态写入 | 状态在枚举范围内 |

#### CandidateInfo 核心字段

```python
CandidateInfo(
    name="张三",               # 姓名
    age_gender="28岁/男",      # 年龄/性别
    education="本科",           # 学历
    years_of_experience="5年",  # 工作年限
    city="上海",                # 城市
    expected_salary="25-35K",   # 期望薪资
    latest_company="字节跳动",   # 最近公司
    latest_title="高级后端工程师", # 最近岗位
    skills=["Python","Go"],     # 技能标签
    phone="13800138000",        # 手机号
    boss_url="https://...",     # Boss链接
    dedup_key="a3f5b8c1...",   # 自动生成
)
```

#### 去重策略（优先级从高到低）

| 优先级 | 匹配条件 | 行为 |
|--------|---------|------|
| 1 | 手机号精确匹配 | 更新已有记录 |
| 2 | SHA1(手机号+姓名+公司+岗位) | 更新已有记录 |
| 3 | 无匹配 | 新建记录 |

#### 交付物

```bash
scripts/resume_parser.py       # 简历解析脚本
scripts/feishu_upload.py       # 飞书上传脚本
config/feishu.json             # 飞书配置（需补充 app_token/table_id）
skills/resume-parser/SKILL.md  # Skill 文档
```

#### 关键代码调用

```python
from scripts.resume_parser import extract_from_page, extract_from_text
from scripts.feishu_upload import FeishuUploader

# 从页面提取
info = await extract_from_page(page, source="detail")

# 写入飞书
uploader = FeishuUploader.from_config("config/feishu.json", org="hanxing")
record_id, is_new = uploader.upsert_candidate(info.to_dict())
```

---

### Skill 5: knowledge-base（知识库系统）

**定位**：支撑模块，为 boss-greet 和 chat-engine 供给话术和匹配规则

**无前置依赖**：独立运行，可最先初始化

#### 执行步骤

| 步骤 | 动作 | 输入 | 输出 | 验证方法 |
|------|------|------|------|---------|
| 5.1 | 加载知识库数据 | `data/knowledge/*.json` | KnowledgeBase 实例 | 4 个 JSON 文件全部加载 |
| 5.2a | 获取打招呼话术 | position + name | 插值后话术文本 | `{name}` 已替换 |
| 5.2b | 匹配聊天话术 | 候选人消息文本 | 话术模式 + 回复模板 | scenario 非空 |
| 5.2c | 岗位匹配评分 | 候选人技能/学历/经验 | 岗位列表（按分数排序） | match_score > 0 |
| 5.2d | 获取反馈模板 | 模板类型 + 变量 | 插值后模板文本 | 模板类型合法 |
| 5.3 | 从聊天记录学习 | 历史消息列表 | 新增话术数量报告 | 新话术 added |
| 5.4 | 保存修改 | 内存数据 | `data/knowledge/*.json` 更新 | 文件修改时间更新 |

#### 知识库数据文件

| 文件 | 内容 | 被谁调用 |
|------|------|---------|
| `greetings.json` | 打招呼话术（支持 {name}/{position} 变量） | boss-greet |
| `chat_patterns.json` | 聊天话术模式（场景+触发词+回复模板） | chat-engine |
| `position_requirements.json` | 岗位需求（技能/学历/经验/薪资） | boss-greet, chat-engine |
| `feedback_templates.json` | 反馈模板（面试确认/拒绝/跟进） | chat-engine |

#### 交付物

```bash
scripts/knowledge_base.py              # 脚本本体
data/knowledge/greetings.json          # 打招呼话术库
data/knowledge/chat_patterns.json      # 聊天话术模式库
data/knowledge/position_requirements.json  # 岗位需求库
data/knowledge/feedback_templates.json # 反馈模板库
skills/knowledge-base/SKILL.md         # Skill 文档
```

#### 关键代码调用

```python
from scripts.knowledge_base import KnowledgeBase

kb = KnowledgeBase()
greeting = kb.get_greeting(position="Python后端", name="张三")
matches = kb.match_candidate_to_position({"skills": ["Python"], "experience_years": "3年"})
pattern = kb.match_chat_pattern("请问薪资是多少？")
kb.save()  # 持久化修改
```

---

### Skill 6: anti-detect（风控对抗）

**定位**：底层护航模块，被所有业务模块调用，本身不执行业务

**无前置依赖**：独立运行

#### 执行步骤（按调用时序）

| 步骤 | 动作 | 触发时机 | 输入 | 输出 | 验证方法 |
|------|------|---------|------|------|---------|
| 6.1 | 注入 Stealth 补丁 | 新 Page 创建后首次导航前 | page | 10 项 JS 补丁注入 | `navigator.webdriver === undefined` |
| 6.2 | 随机延迟 | 每次业务操作前后 | anti_detect.json 配置 | 等待 5-15s（正态分布） | 日志打印实际等待秒数 |
| 6.3 | 鼠标轨迹模拟 | 点击按钮前 | 目标坐标 | 贝塞尔曲线鼠标移动 | 鼠标轨迹非直线 |
| 6.4 | 页面滚动模拟 | 浏览列表时 | 滚动距离 | 分段滚动 + 偶尔回滚 | 页面位置变化 |
| 6.5 | 验证码检测 | 每次关键操作后 | page DOM | True（检测到）/ False | 关键词 + DOM 选择器双检 |
| 6.6 | 封号预警 | 每次操作后 | ActionStats | "normal" / "warning" / "paused" | 统计数据在阈值内 |
| 6.7 | 通知 | 验证码/预警触发时 | notify 配置 | 飞书/Telegram 通知 | 通知发送成功 |

#### 预警阈值

| 维度 | 阈值 | 触发结果 |
|------|------|---------|
| 每日动作数 | 200 次（配置中 200，建议先调 50） | paused（暂停 5-15 分钟） |
| 验证码出现次数 | ≥ 3 次 | paused |
| 错误率 | > 30% | warning（降速） |
| 30s 内 burst | > 10 次 | warning |
| 连续失败 | ≥ 3 次 | warning |

#### 交付物

```bash
scripts/anti_detect.py          # 脚本本体
config/anti_detect.json         # 风控参数配置
references/anti-detect-guide.md # 风控最佳实践参考
skills/anti-detect/SKILL.md     # Skill 文档
```

#### 关键代码调用

```python
from scripts.anti_detect import AntiDetect

ad = AntiDetect(config_path="config/anti_detect.json")
await ad.apply_stealth(page)                              # 步骤 6.1
await ad.random_delay()                                   # 步骤 6.2
await ad.simulate_mouse(page, target_x=500, target_y=300) # 步骤 6.3
await ad.simulate_scroll(page)                            # 步骤 6.4
if await ad.detect_captcha(page):                         # 步骤 6.5
    # 暂停 + 通知人工
state = await ad.check_warning(page)                      # 步骤 6.6
```

---

## 总：端到端联调步骤（确保如期交付）

### 第一天：基础环境

| # | 任务 | 验证标准 | 负责人 |
|---|------|---------|--------|
| 1 | 安装依赖 (`playwright`, `requests`) | `pip list \| grep playwright` | 开发 |
| 2 | 配置 `ZAI_API_KEY` 环境变量 | 调用 GLM-5 接口返回正常 | 开发 |
| 3 | 执行 `python scripts/boss_login.py` 扫码登录 | `data/cookies/boss_cookies.json` 生成 | 开发 |

### 第二天：核心流程跑通

| # | 任务 | 验证标准 | 负责人 |
|---|------|---------|--------|
| 4 | `python scripts/boss_greet.py --dry-run` | 输出候选人列表，不实际发送 | 开发 |
| 5 | `python scripts/boss_greet.py --max-greets 5` | 5 人打招呼成功，计数更新 | 开发 |
| 6 | `python scripts/chat_engine.py --poll-interval 30` | 监控到候选人回复并自动回复 | 开发 |

### 第三天：数据出口

| # | 任务 | 验证标准 | 负责人 |
|---|------|---------|--------|
| 7 | 创建飞书多维表格（按本文档字段建议） | 表格可访问，列名正确 | Daniel |
| 8 | 配置 `config/feishu.json`（app_token, table_id, app_secret） | curl 获取 token 成功 | Daniel |
| 9 | `python scripts/feishu_upload.py --test` | 映射结果正确，不实际写入 | 开发 |
| 10 | `python scripts/feishu_upload.py` 实际写入 | 飞书表格出现新记录 | 开发 |

### 第四天：稳定化 + 自动化

| # | 任务 | 验证标准 | 负责人 |
|---|------|---------|--------|
| 11 | 校准 CSS 选择器（登录真实 Boss 确认） | 候选人卡片/打招呼按钮定位成功 | 开发 |
| 12 | 补充打招呼模板到 20+ 变体 | `config/templates.json` 条目 ≥ 20 | 开发 |
| 13 | 调优风控参数（从 50 次/天起步） | 连续运行 1 小时无封号预警 | 开发 |
| 14 | 配置 crontab 自动化 | 工作日定时任务执行正常 | 开发 |

### 交付清单汇总

```bash
# 必须交付的文件
scripts/boss_login.py          ✅ 已完成
scripts/boss_greet.py          ✅ 已完成
scripts/chat_engine.py         ✅ 已完成
scripts/resume_parser.py       ✅ 已完成
scripts/feishu_upload.py       ✅ 已完成
scripts/knowledge_base.py      ✅ 已完成
scripts/anti_detect.py         ✅ 已完成
scripts/config_position.py     ✅ 已完成

# 必须交付的配置
config/llm.json                ✅ 已有（需配置 ZAI_API_KEY）
config/anti_detect.json        ✅ 已有（建议 daily_action_limit 调为 50）
config/feishu.json             ⚠️ 需补充 app_token + table_id + app_secret
config/filters.json            ✅ 已有
config/templates.json          ✅ 已有（建议补充到 20+ 变体）

# 必须交付的数据
data/knowledge/greetings.json           ✅ 已有
data/knowledge/chat_patterns.json       ✅ 已有
data/knowledge/position_requirements.json ✅ 已有
data/knowledge/feedback_templates.json  ✅ 已有

# 必须交付的文档
docs/PRD.md                    ✅ 已完成
docs/implementation-plan.md   ✅ 已完成
docs/skills-workflow.md        ✅ 本文档
skills/*/SKILL.md              ✅ 6 个全部完成
references/*.md                ✅ 3 个参考文档
```

---

*老王出品 — 2026-04-10 | 按这个走，不会翻车*
