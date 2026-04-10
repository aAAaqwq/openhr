# OpenHR 实施方案（可落地执行版）

> 更新时间：2026-04-10
> 状态：**模块开发已完成 → 待端到端集成测试 → 待部署自动化**
> 核心原则：**先跑通最小闭环，再逐步自动化**

---

## 现状总结

```
已完成：6 大模块全部通过验收（5680 行代码，7 个脚本）
待完成：端到端联调 → 飞书表格配置 → 自动化部署
```

### 项目结构（实际路径）

```
~/clawd/projects/openhr/
├── scripts/                    # 核心执行脚本
│   ├── boss_login.py           # M1: 登录（421行）
│   ├── anti_detect.py          # M6: 风控对抗（579行）
│   ├── boss_greet.py           # M2: 打招呼（1200行）
│   ├── chat_engine.py          # M4: 智能聊天（1231行）
│   ├── resume_parser.py        # M3: 简历解析（551行）
│   ├── feishu_upload.py        # M3: 飞书上传（584行）
│   ├── knowledge_base.py       # M5: 知识库（832行）
│   └── config_position.py      # 岗位配置CLI（282行）
├── config/                     # 配置文件
│   ├── anti_detect.json        # 风控参数
│   ├── feishu.json             # 飞书多维表格配置
│   ├── filters.json            # 候选人筛选条件
│   ├── llm.json                # LLM 配置
│   └── templates.json          # 打招呼/聊天模板
├── data/                       # 运行时数据
│   ├── cookies/                # 登录态存储
│   ├── chat_logs/              # 聊天记录
│   ├── knowledge/              # 知识库数据
│   └── templates/              # 模板缓存
├── skills/                     # 各模块 Skill 文档
│   ├── boss-login/SKILL.md
│   ├── boss-greet/SKILL.md
│   ├── anti-detect/SKILL.md
│   ├── resume-parser/SKILL.md
│   ├── chat-engine/SKILL.md
│   └── knowledge-base/SKILL.md
├── references/                 # 参考文档
│   ├── boss-api.md             # Boss直聘页面结构分析
│   ├── feishu-bitable-api.md   # 飞书多维表格API
│   └── anti-detect-guide.md    # 风控对抗指南
├── docs/
│   ├── PRD.md                  # 产品需求文档
│   └── implementation-plan.md  # 本文件
├── acceptance-criteria.md      # 验收标准
└── progress.json               # 项目进度记录
```

---

## 实施路线图（4 个阶段）

### 阶段 1：最小闭环跑通（1-2 天）

**目标**：手动执行脚本，跑通「登录 → 打招呼 → 聊天 → 飞书同步」全流程

| 步骤 | 任务 | 验证方法 | 负责人 |
|------|------|---------|--------|
| 1.1 | 确认 Python 环境和依赖安装 | `pip list \| grep playwright` | 开发 |
| 1.2 | 配置 LLM API Key（`ZAI_API_KEY` 环境变量） | 调用 GLM-5 接口测试 | 开发 |
| 1.3 | 配置飞书应用凭证 | 见下方「飞书配置清单」 | Daniel |
| 1.4 | 执行 `boss_login.py` 手动扫码登录 | 截图二维码 + 扫码成功 + cookie 保存 | 开发 |
| 1.5 | 执行 `boss_greet.py --dry-run` 测试打招呼 | 不实际发送，只输出候选人列表 | 开发 |
| 1.6 | 执行 `boss_greet.py` 正式打招呼（5 人） | 确认消息发送成功 + 计数更新 | 开发 |
| 1.7 | 执行 `chat_engine.py --monitor` 监控聊天 | 读取到候选人回复 | 开发 |
| 1.8 | 执行 `resume_parser.py` + `feishu_upload.py` | 飞书表格出现新记录 | 开发 |

#### 飞书配置清单（步骤 1.3）

需要在飞书开放平台完成以下操作：

```markdown
前置条件：
- 飞书应用已创建（App ID: cli_a9f758c0efa2dcc4 / cli_a83467f9ecba5013）
- 应用已开通「多维表格」权限（bitable:record:write, bitable:record:read）

需要补充的配置（config/feishu.json）：
1. app_secret    — 从 pass store 获取：pass api/feishu-hanxing
2. app_token     — 从飞书多维表格 URL 获取：feishu.cn/base/{app_token}?table={table_id}
3. table_id      — 从飞书多维表格 URL 获取

飞书多维表格表结构建议：
| 列名 | 类型 | 说明 |
|------|------|------|
| 姓名 | 单行文本 | 候选人全名 |
| 手机号 | 单行文本 | 不用数字类型（保留前导0） |
| 学历 | 单选 | 本科/硕士/博士/大专 |
| 工作年限 | 数字 | 筛选排序用 |
| 当前城市 | 单选 | 深圳/北京/上海等 |
| 期望岗位 | 单行文本 | |
| 期望薪资 | 单行文本 | 薪资区间不规范，文本更稳 |
| 最近公司 | 单行文本 | |
| 最近岗位 | 单行文本 | |
| 技能标签 | 多选 | Python, Go, React 等 |
| Boss链接 | 超链接 | |
| 跟进状态 | 单选 | 新入库/已打招呼/已回复/已约面/已拒绝/不匹配 |
| Agent评分 | 数字 | 1-10 |
| Agent报告 | 多行文本 | 200字评价 |
| 去重Key | 单行文本 | SHA1(手机号+姓名+公司+岗位) |
| 录入时间 | 日期 | 创建时间 |
```

#### 飞书 API 验证命令

```bash
# 1. 获取 tenant_access_token
curl -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/' \
  -H 'Content-Type: application/json' \
  -d '{"app_id": "cli_a9f758c0efa2dcc4", "app_secret": "YOUR_SECRET"}'

# 2. 验证表格可访问（返回字段列表）
curl -X GET "https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=1" \
  -H "Authorization: Bearer {tenant_access_token}"
```

> 官方文档：https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview

---

### 阶段 2：稳定化 + 调优（3-5 天）

**目标**：在真实场景下连续运行，修复边界情况

| 步骤 | 任务 | 说明 |
|------|------|------|
| 2.1 | 校准 CSS 选择器 | 登录真实 Boss 直聘，确认 `references/boss-api.md` 中的选择器有效性 |
| 2.2 | 调优风控参数 | 根据 `config/anti_detect.json` 调整间隔、阈值 |
| 2.3 | 补充打招呼模板 | `config/templates.json` 至少 20 个变体，避免同质化触发风控 |
| 2.4 | 验证去重逻辑 | 同一候选人不同渠道入库不重复 |
| 2.5 | 端到端压力测试 | 连续打招呼 50 人，观察风控反应 |
| 2.6 | 聊天引擎长时间运行 | 连续运行 4 小时，验证稳定性 |

#### CSS 选择器校准方法

```python
# 登录后手动检查选择器
import asyncio
from playwright.async_api import async_playwright

async def verify_selectors():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="data/cookies/boss_cookies.json")
        page = await context.new_page()

        # 测试候选人列表页
        await page.goto("https://www.zhipin.com/web/boss/recommend")
        await page.wait_for_load_state("networkidle")

        # 尝试各种选择器
        cards = await page.locator("[class*='card'], main li, section li").count()
        print(f"候选人卡片数量: {cards}")

        greet_btn = await page.get_by_role("button", name="打招呼").count()
        print(f"打招呼按钮数量: {greet_btn}")

        await browser.close()

asyncio.run(verify_selectors())
```

#### 风控参数调优建议

```json
// config/anti_detect.json — 推荐保守参数
{
  "delay_min": 5.0,          // 打招呼最小间隔（秒）
  "delay_max": 15.0,         // 打招呼最大间隔（秒）
  "daily_action_limit": 50,  // 每日上限（先从50开始，稳定后逐步提升）
  "burst_count": [5, 8],     // 每组打招呼数量
  "burst_rest_sec": [30, 180] // 组间休息
}
```

> 最小可用安全策略（必须遵守）：
> 1. Headed 模式运行（不能 headless）
> 2. 固定 storage_state / profile
> 3. 打招呼间隔 5-15s
> 4. 每 5-8 次长休息一次
> 5. 检测验证码即暂停
> 6. 每日上限硬限制
> 7. 同类话术至少 20+ 变体
> 8. 所有失败操作截图留痕

---

### 阶段 3：自动化调度（1-2 天）

**目标**：配置 Cron 任务，实现每日自动运行

| 步骤 | 任务 | Cron 表达式 | 说明 |
|------|------|------------|------|
| 3.1 | 每日自动打招呼 | `0 10 * * 1-5` | 工作日 10:00 执行 |
| 3.2 | 定时聊天监控 | 每 15 分钟 | 检查新消息并自动回复 |
| 3.3 | 每日进度汇报 | `0 20 * * 1-5` | 工作日 20:00 输出日报 |
| 3.4 | 登录态检查 | `0 9 * * 1-5` | 工作日 9:00 检查 cookie |

#### Cron 配置示例（系统 crontab）

```bash
# 编辑 crontab
crontab -e

# 每日打招呼（工作日 10:00）
0 10 * * 1-5 cd ~/clawd/projects/openhr && python scripts/boss_greet.py >> logs/greet_$(date +\%Y\%m\%d).log 2>&1

# 登录态检查（工作日 9:00）
0 9 * * 1-5 cd ~/clawd/projects/openhr && python scripts/boss_login.py --check >> logs/login_$(date +\%Y\%m\%d).log 2>&1

# 每日进度汇报（工作日 20:00）
0 20 * * 1-5 cd ~/clawd/projects/openhr && python -c "import json; d=json.load(open('data/greet_count.json')); print(f'今日打招呼: {d.get(\"today\", 0)}人')" >> logs/report_$(date +\%Y\%m\%d).log 2>&1
```

#### 或者用 Claude Code 的 CronCreate

```
# 每日打招呼（工作日 10:00）
cron: "0 10 * * 1-5"
prompt: "cd ~/clawd/projects/openhr && python scripts/boss_greet.py --limit 50"

# 聊天监控（每 15 分钟）
cron: "*/15 * * * *"
prompt: "cd ~/clawd/projects/openhr && python scripts/chat_engine.py --monitor"
```

---

### 阶段 4：扩展优化（持续迭代）

**目标**：根据实际运行数据持续优化

| 步骤 | 任务 | 优先级 |
|------|------|--------|
| 4.1 | 候选人智能评分模型优化 | P1 |
| 4.2 | 会话优先级队列（高意向优先回复） | P1 |
| 4.3 | 验证码自动解决（滑块/图形） | P2 |
| 4.4 | 多岗位并行招聘 | P2 |
| 4.5 | 拉勾/猎聘平台扩展 | P3 |
| 4.6 | 面试日历集成 | P3 |

---

## 核心流程执行图

```
[每日 09:00] 登录态检查
       │
       ├─ 已登录 ✅ → 继续
       └─ 未登录 🔴 → 通知管理员扫码（必须人工）
       │
[每日 10:00] 自动打招呼
       │
       ├─ 读取 config/filters.json 筛选条件
       ├─ 导航到推荐牛人页面
       ├─ 遍历候选人卡片 → 筛选 → 打招呼
       ├─ 每 5-8 次长休息 30-180s
       └─ 达到每日上限或无更多候选人 → 停止
       │
[每 15 分钟] 聊天监控
       │
       ├─ 遍历聊天列表
       ├─ 读取候选人回复 → LLM 生成回复
       ├─ 状态机推进：打招呼→兴趣确认→面试意向→时间确认
       ├─ 面试确认 🟡 → 通知管理员
       └─ 候选人拒绝 → 归档 + 更新飞书状态
       │
[触发式] 简历解析 + 飞书同步
       │
       ├─ 获取简历（聊天窗口/PDF）
       ├─ LLM 提取结构化信息 + 评分
       ├─ 去重检查 → 写入飞书多维表格
       └─ 评分 < 5 🟡 → 标记「待确认」
       │
[每日 20:00] 进度汇报
       │
       └─ 读取统计数据 → 输出日报
```

---

## 关键配置速查

### 环境变量

```bash
export ZAI_API_KEY="your_glm5_api_key"  # LLM 调用必须
```

### 配置文件说明

| 文件 | 用途 | 关键字段 |
|------|------|---------|
| `config/llm.json` | LLM 配置 | provider=zai, model=glm-5-plus, base_url, api_key_env |
| `config/anti_detect.json` | 风控参数 | delay_min/max, daily_action_limit, captcha_keywords |
| `config/feishu.json` | 飞书配置 | app_id, app_secret, app_token, table_id, field_mapping |
| `config/filters.json` | 筛选条件 | education, experience_years, salary_range |
| `config/templates.json` | 打招呼模板 | 多种变体模板 |

### 常用命令

```bash
cd ~/clawd/projects/openhr

# 登录
python scripts/boss_login.py                  # 扫码登录
python scripts/boss_login.py --check          # 仅检查登录态

# 打招呼
python scripts/boss_greet.py --dry-run        # 测试模式（不发送）
python scripts/boss_greet.py                  # 正式运行
python scripts/boss_greet.py --limit 20       # 限制 20 人

# 聊天
python scripts/chat_engine.py                 # 启动聊天引擎
python scripts/chat_engine.py --monitor       # 仅监控模式

# 简历
python scripts/resume_parser.py <file.pdf>    # 解析简历
python scripts/feishu_upload.py <file.pdf>    # 解析并上传飞书

# 岗位配置
python scripts/config_position.py --list      # 列出岗位
python scripts/config_position.py --add       # 添加岗位

# 查看状态
cat data/greet_count.json                     # 打招呼计数
ls data/chat_logs/                            # 聊天记录
```

---

## 官方文档参考

| 技术 | 官方文档 |
|------|---------|
| Playwright Python | https://playwright.dev/python/docs/intro |
| Playwright Selectors | https://playwright.dev/python/docs/locators |
| Playwright storage_state | https://playwright.dev/python/docs/auth |
| 飞书多维表格 API | https://open.feishu.cn/document/server-docs/docs/bitable-v1/bitable-overview |
| 飞书 tenant_access_token | https://open.feishu.cn/document/server-docs/getting-started/api-access-token |
| 飞书 Bitable Record API | https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/bitable-v1/app-table-record/create |
| GLM API | https://open.bigmodel.cn/dev/api |

---

## 飞书 API 要点（官方验证）

### 认证
```http
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal/
Content-Type: application/json
{"app_id": "xxx", "app_secret": "xxx"}
→ {"tenant_access_token": "t-xxx", "expire": 7200}
```

### 创建记录
```http
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
Authorization: Bearer {tenant_access_token}
{"fields": {"姓名": "张三", "学历": "本科", "跟进状态": "新入库"}}
```

### 批量创建（最多 1000 条/次）
```http
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create
Authorization: Bearer {tenant_access_token}
{"records": [{"fields": {...}}, {"fields": {...}}]}
```

### 查询记录（支持 filter）
```http
GET https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?filter=CurrentValue.[手机号]="138xxx"&page_size=20
Authorization: Bearer {tenant_access_token}
```

### 错误码
- `1254290` — 请求过快，需退避
- `1254291` — 写入冲突，不要并发写同一表
- `1254040` — app_token 不存在
- `1254043` — record_id 不存在

---

## 立即行动清单

**现在就能做的事：**

1. **配置飞书表格**（15 分钟）
   - 创建飞书多维表格
   - 按「飞书配置清单」建列
   - 填入 `config/feishu.json`

2. **测试登录**（5 分钟）
   ```bash
   export ZAI_API_KEY="your_key"
   cd ~/clawd/projects/openhr
   python scripts/boss_login.py
   ```

3. **Dry-run 打招呼**（5 分钟）
   ```bash
   python scripts/boss_greet.py --dry-run
   ```

4. **首次正式打招呼**（10 分钟）
   ```bash
   python scripts/boss_greet.py --limit 5
   ```

5. **验证飞书写入**
   ```bash
   python scripts/resume_parser.py test_resume.pdf
   python scripts/feishu_upload.py test_resume.pdf
   ```

---

*CEO 小a — 2026-04-10 | v4 实施方案（可落地执行版）*
