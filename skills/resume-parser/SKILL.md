# 简历解析 + 飞书多维表格模块 (resume-parser)

> Skill 名称: `resume-parser`  
> 所属模块: OpenHR c4  
> 文件路径: `scripts/resume_parser.py` + `scripts/feishu_upload.py`  
> 触发条件: 需要解析候选人简历或写入飞书多维表格时调用  
> 更新时间: 2026-04-07

---

## 概述

本模块负责：
1. 从 Boss 直聘聊天窗口或简历详情页提取候选人结构化信息
2. 将候选人信息写入飞书多维表格（含去重逻辑）
3. 支持独立使用或流水线调用

---

## 架构

```
简历来源
  ├── Boss 直聘聊天窗口        → resume_parser.extract_from_page(page, source="chat")
  ├── Boss 直聘简历详情页      → resume_parser.extract_from_page(page, source="detail")
  └── 直接文本传入             → resume_parser.extract_from_text(text)

           ↓

  CandidateInfo (结构化数据)
      ├── 字段验证 + 去重 key 生成
      └── to_dict() / to_feishu_fields()

           ↓

  feishu_upload.FeishuUploader
      ├── upsert_candidate()  ← 核心方法（自动去重）
      └── upsert_batch()       ← 批量写入
```

---

## 核心数据结构

### CandidateInfo（简历提取结果）

```python
from scripts.resume_parser import CandidateInfo

info = CandidateInfo(
    name="张三",
    age_gender="28岁/男",
    education="本科",
    years_of_experience="5年",
    city="上海",
    expected_salary="25-35K",
    latest_company="字节跳动",
    latest_title="高级后端工程师",
    experience_summary="...",
    skills=["Python", "Go", "Redis"],
    phone="13800138000",
    boss_url="https://...",
    dedup_key="a3f5b8c1...",  # 自动生成
)
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | str | 姓名 |
| `age_gender` | str | 年龄/性别，如 "28岁/男" |
| `education` | str | 学历 |
| `years_of_experience` | str | 工作年限 |
| `city` | str | 当前城市 |
| `expected_salary` | str | 期望薪资，如 "25-35K" |
| `latest_company` | str | 最近公司 |
| `latest_title` | str | 最近岗位 |
| `experience_summary` | str | 工作经历摘要（多行） |
| `project_summary` | str | 项目经历摘要 |
| `education_summary` | str | 教育经历摘要 |
| `skills` | list[str] | 技能标签列表 |
| `self_summary` | str | 自我评价 |
| `phone` | str | 手机号 |
| `boss_url` | str | Boss 候选人链接 |
| `source` | str | 来源平台，默认 "Boss直聘" |
| `raw_text` | str | 原始文本（供调试） |
| `dedup_key` | str | 去重 key（SHA1，基于 phone/name/company/title） |

---

## 使用方式

### 方式一：Playwright 页面提取（自动判断来源）

```python
from playwright.async_api import async_playwright
from scripts.resume_parser import extract_from_page
from scripts.feishu_upload import FeishuUploader

async def parse_and_upload(page):
    # 1. 从当前页面提取候选人信息
    info = await extract_from_page(page, source="detail")

    # 2. 转为 dict
    candidate_dict = info.to_dict()

    # 3. 写入飞书
    uploader = FeishuUploader.from_config("config/feishu.json", org="hanxing")
    record_id, is_new = uploader.upsert_candidate(candidate_dict)

    print(f"写入{'新建' if is_new else '更新'}: record_id={record_id}")
    return record_id, is_new
```

### 方式二：直接文本解析（无需浏览器）

```python
from scripts.resume_parser import extract_from_text, CandidateInfo

raw = """
张三 | 28岁/男 | 本科 | 5年经验
手机: 13800138000
期望薪资: 25-35K
最近公司: 字节跳动 | 岗位: 高级后端工程师
技能: Python, Go, Redis, K8s
工作经历:
2019-2022 字节跳动 Python开发
2022-至今 字节跳动 高级后端工程师
"""

info = extract_from_text(raw)
print(info.name)         # 张三
print(info.skills)      # ['Python', 'Go', 'Redis', 'K8s']
print(info.dedup_key)   # a3f5b8c1...
```

### 方式三：仅写入飞书（已有结构化数据）

```python
from scripts.feishu_upload import upload_candidate

candidate = {
    "name": "李四",
    "age_gender": "26岁/女",
    "education": "硕士",
    "phone": "13900139000",
    "skills": ["Java", "Spring"],
    "dedup_key": "...",  # 用 resume_parser.build_dedup_key() 生成
}

record_id, is_new = upload_candidate(candidate)
```

### 方式四：批量写入

```python
from scripts.feishu_upload import FeishuUploader

uploader = FeishuUploader.from_config("config/feishu.json")
result = uploader.upsert_batch([candidate1, candidate2, candidate3])
print(result)
# {'created': 2, 'updated': 1, 'failed': 0, 'errors': []}
```

---

## 命令行用法

### 简历解析（Playwright 页面）

```bash
# 从当前页面提取（需已安装并登录 Boss）
python3 scripts/resume_parser.py

# 指定模式（简历详情页）
python3 scripts/resume_parser.py --mode detail

# 聊天窗口模式
python3 scripts/resume_parser.py --mode chat

# 直接传入文本（跳过浏览器）
python3 scripts/resume_parser.py --text "张三\n28岁\n本科\nPython开发"

# 输出到文件
python3 scripts/resume_parser.py --text "..." --output data/candidate.json
```

### 飞书上传

```bash
# 调试模式（打印配置，不写入）
python3 scripts/feishu_upload.py --debug

# 测试模式（打印映射结果，不写入）
python3 scripts/feishu_upload.py --test

# 实际写入
python3 scripts/feishu_upload.py

# 指定组织和配置路径
python3 scripts/feishu_upload.py --config config/feishu.json --org hanxing
```

---

## 去重策略

| 优先级 | 条件 | 行为 |
|--------|------|------|
| 1 | 手机号精确匹配 | 更新已有记录 |
| 2 | 去重 key 匹配 | 更新已有记录 |
| 3 | 姓名+公司+岗位组合 | 更新已有记录 |
| 4 | 无匹配 | 新建记录 |

**去重 key 生成规则**：
```
SHA1(phone | name | latest_company | latest_title)
```

---

## 字段映射（feishu.json）

飞书多维表格列名通过 `config/feishu.json` 的 `field_mapping` 配置：

```json
{
  "hanxing": {
    "field_mapping": {
      "name": "姓名",
      "age_gender": "年龄/性别",
      "education": "学历",
      "experience": "工作经历",
      "skills": "技能标签",
      "expected_salary": "期望薪资",
      "phone": "手机号",
      "source": "来源平台",
      "status": "沟通状态",
      "created_at": "录入时间",
      "dedup_key": "去重Key"
    }
  }
}
```

---

## 飞书多维表格建表建议

在飞书中创建多维表格时，建议按以下列名和类型创建：

| 列名 | 类型 | 说明 |
|------|------|------|
| 姓名 | 单行文本 | 主展示字段 |
| 手机号 | 单行文本 | 去重用 |
| 年龄/性别 | 单行文本 | |
| 学历 | 单行文本 | 或单选 |
| 工作年限 | 数字 | |
| 最近公司 | 单行文本 | |
| 最近岗位 | 单行文本 | |
| 期望薪资 | 单行文本 | |
| 工作经历 | 多行文本 | |
| 技能标签 | 多选 | 推荐多选 |
| 来源平台 | 单行文本 | 默认 "Boss直聘" |
| 沟通状态 | 单选 | 新入库/已打招呼/已回复/待跟进/已约面 |
| 录入时间 | 创建时间 | 自动填充 |
| 去重Key | 单行文本 | 隐藏列 |
| Boss链接 | 超链接 | |

### 推荐状态枚举值

```
新入库 → 已打招呼 → 已回复 → 待跟进 → 已约面 → 已拒绝 / 不匹配
```

---

## 错误处理

| 错误类型 | 处理策略 |
|----------|----------|
| 网络错误 | 指数退避重试（最多3次） |
| Token 过期 | 自动刷新 tenant_access_token |
| 429 限流 | 按 Retry-After 等待后重试 |
| 字段不存在 | 跳过该字段，记录警告日志 |
| 记录已存在 | 自动转为 update |

---

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 安装 Playwright（仅 CLI 模式需要） | `pip3 install playwright` | `python3 -c "import playwright"` |
| 3 | 安装 Chromium（仅 CLI 模式需要） | `python3 -m playwright install chromium` | 浏览器二进制文件存在 |
| 4 | 安装 requests（飞书上传需要） | `pip3 install requests` | `python3 -c "import requests"` |
| 5 | 配置 LLM API Key（评分需要） | `export ZAI_API_KEY="your_key"` | `echo $ZAI_API_KEY` 非空 |
| 6 | 配置飞书凭证 | 编辑 `config/feishu.json` | app_secret + app_token + table_id 已填写 |

### 第三方依赖

| 包 | 用途 | 使用位置 |
|----|------|---------|
| `playwright` | 从 Boss 页面提取简历 | `resume_parser.py`（CLI 模式） |
| `requests` | 调用 LLM API + 飞书 API | `feishu_upload.py`（飞书写入） |

> **注意**：作为模块导入使用 `extract_from_text()` 时不需要 playwright，纯文本解析仅需 Python 标准库。

### 运行命令

```bash
# 直接文本解析（不需要浏览器）
python3 scripts/resume_parser.py --text "简历文本..."

# 从 Boss 页面提取（需要已登录）
xvfb-run -a python3 scripts/resume_parser.py --mode detail

# 飞书上传
python3 scripts/feishu_upload.py --test   # 测试模式
python3 scripts/feishu_upload.py          # 正式写入
```

---

## 触发条件

| 场景 | 是否调用 |
|------|---------|
| 打招呼模块发现候选人，需要获取简历信息时 | ✅ |
| 聊天跟进时，候选人发送简历文本 | ✅ |
| HR 手动要求上传候选人时 | ✅ |
| 简历详情页打开后自动触发 | ✅ |

---

## 注意事项

1. **配置必须完整**：首次使用前需填写 `config/feishu.json` 中的 `app_token`、`table_id` 和 `app_secret`
2. **飞书应用权限**：确保应用已开通「多维表格」权限
3. **去重 key 唯一性**：相同候选人多次写入不会重复创建
4. **批量写入推荐**：候选人量大时优先用 `upsert_batch()`，减少 API 调用
5. **调试模式**：`--debug` 和 `--test` 模式不实际写入，适合验证配置

---

## 目录结构

```
openhr/
├── scripts/
│   ├── resume_parser.py      # ← 简历解析脚本
│   └── feishu_upload.py      # ← 飞书上传脚本
├── config/
│   └── feishu.json           # ← 飞书配置（需补充 app_token/table_id）
└── skills/
    └── resume-parser/
        └── SKILL.md          # ← 本文档
```
