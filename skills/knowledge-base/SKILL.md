# Skill: knowledge-base

## 模块概述

`knowledge-base` 是 OpenHR 自动化招聘智能体的知识库管理模块，负责管理招聘相关的话术、岗位需求和反馈模板。

## 触发条件

当以下场景需要时调用此 Skill：

- **打招呼**：需要生成个性化打招呼消息时
- **聊天跟进**：需要根据候选人的消息生成回复时
- **岗位匹配**：需要将候选人与岗位需求进行匹配时
- **发送反馈**：需要生成面试确认/拒绝/跟进消息时
- **学习新话术**：需要从历史聊天记录中提取新话术时

## 调用方式

### Python 脚本调用

```python
from scripts.knowledge_base import KnowledgeBase, get_knowledge_base

# 方式一：直接初始化
kb = KnowledgeBase()

# 方式二：获取全局单例
kb = get_knowledge_base()

# === 打招呼 ===
greeting = kb.get_greeting(position="Python后端开发", name="张三")
# 返回插值后的打招呼话术，如："您好 张三，我是贵公司的HR，看到您对Python后端开发岗位很感兴趣..."

# === 聊天话术匹配 ===
pattern = kb.match_chat_pattern("请问薪资范围是多少？")
if pattern:
    response = pattern.get("selected_response")
    scenario = pattern.get("scenario")

# === 岗位匹配 ===
matches = kb.match_candidate_to_position({
    "skills": ["Python", "Django", "PostgreSQL"],
    "experience_years": "3年",
    "education": "本科",
})
# 返回按匹配度排序的岗位列表

# === 反馈模板 ===
feedback = kb.get_feedback_template("interview_confirm", {
    "name": "张三",
    "time": "周三 15:00",
    "address": "北京市朝阳区XX大厦",
})
if feedback:
    message = feedback["text"]  # 插值后的消息文本

# === 从聊天记录学习 ===
report = kb.learn_from_chat_history([
    {"role": "hr", "message": "您好，请问您对这个岗位感兴趣吗？"},
    {"role": "candidate", "message": "感兴趣，请问薪资是多少？"},
    {"role": "hr", "message": "月薪20-30k，13薪。"},
])
# 自动提取新话术并添加到知识库

# === 保存所有更改 ===
results = kb.save()  # 保存到 data/knowledge/*.json
```

## 配置说明

### 数据文件位置

```
openhr/
└── data/
    └── knowledge/
        ├── greetings.json           # 打招呼话术库
        ├── chat_patterns.json       # 聊天话术模式库
        ├── position_requirements.json  # 岗位需求库
        └── feedback_templates.json  # 反馈模板库
```

### 打招呼话术库 (greetings.json)

支持变量插值：`{name}`（候选人姓名）、`{position}`（岗位名称）

```json
[
  {
    "id": "greet_1_1234",
    "text": "您好 {name}，看到您的简历，对 {position} 岗位很感兴趣，想和您详细聊聊~",
    "tags": ["热情", "带名字"],
    "priority": 10,
    "enabled": true,
    "variables": ["name", "position"]
  }
]
```

### 聊天话术模式库 (chat_patterns.json)

```json
[
  {
    "id": "chat_1_5678",
    "scenario": "候选人询问薪资",
    "conditions": ["薪资", "工资", "薪酬", "待遇"],
    "patterns": [
      "我们这个岗位月薪 20-30k，13 薪，五险一金全交，还有年度体检和团建~",
      "薪资方面会根据您的经验定级，月薪范围在 18-35k 之间，可以详细谈~"
    ],
    "follow_up": "等待候选人确认意向"
  }
]
```

### 岗位需求库 (position_requirements.json)

```json
[
  {
    "id": "pos_1_9012",
    "name": "Python后端开发",
    "department": "技术部",
    "skills": ["Python", "Django", "FastAPI", "PostgreSQL", "Redis"],
    "experience_years": "3-5年",
    "education": "本科及以上",
    "salary_range": "25k-40k",
    "location": "北京市朝阳区",
    "description": "负责公司核心业务后端开发",
    "keywords": ["Python", "后端", "Django"],
    "exclude_keywords": ["前端", "Java", "PHP"]
  }
]
```

### 反馈模板库 (feedback_templates.json)

支持模板类型：`interview_confirm`（面试确认）、`interview_reject`（拒绝）、`follow_up`（跟进）

```json
[
  {
    "id": "feedback_1_3456",
    "type": "interview_confirm",
    "title": "面试确认",
    "text": "您好 {name}，很高兴通知您面试通过！请于 {time} 到达 {address} 参加面试，收到请回复~",
    "enabled": true
  }
]
```

## 数据结构说明

### 打招呼话术字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✓ | 唯一标识 |
| text | string | ✓ | 模板文本，支持 {name}、{position} 等变量 |
| tags | array | - | 标签列表，用于分类筛选 |
| priority | int | - | 优先级，数值越大越优先被选中 |
| enabled | bool | - | 是否启用，默认 true |
| variables | array | - | 自动提取的变量列表 |

### 聊天话术模式字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✓ | 唯一标识 |
| scenario | string | ✓ | 场景名称，如"候选人询问薪资" |
| conditions | array | ✓ | 触发条件关键词列表 |
| patterns | array | ✓ | 回复模板列表，随机选一条返回 |
| follow_up | string | - | 后续动作提示 |

### 岗位需求字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✓ | 唯一标识 |
| name | string | ✓ | 岗位名称 |
| department | string | - | 部门 |
| skills | array | ✓ | 技能要求列表 |
| experience_years | string | - | 经验要求，如"3-5年" |
| education | string | - | 学历要求 |
| salary_range | string | - | 薪资范围，如"25k-40k" |
| location | string | - | 工作地点 |
| description | string | - | 岗位描述 |
| keywords | array | - | 筛选关键词 |
| exclude_keywords | array | - | 排除关键词 |

### 反馈模板字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| id | string | ✓ | 唯一标识 |
| type | string | ✓ | 模板类型 |
| title | string | ✓ | 模板标题 |
| text | string | ✓ | 模板文本，支持变量插值 |
| enabled | bool | - | 是否启用，默认 true |

## 常用操作示例

### 1. 打招呼流程

```python
kb = get_knowledge_base()

# 获取候选人的打招呼话术
position = kb.get_position_by_name("Python后端")
greeting = kb.get_greeting(
    position=position["name"] if position else "后端开发",
    name="张三"
)
# -> "您好 张三，我看到您的简历，对 Python后端 岗位很感兴趣，想和您详细聊聊~"
```

### 2. 聊天回复流程

```python
kb = get_knowledge_base()

# 接收候选人消息
candidate_msg = "请问这个岗位加班多吗？"

# 匹配话术模式
pattern = kb.match_chat_pattern(candidate_msg)
if pattern:
    response = pattern["selected_response"]
    scenario = pattern["scenario"]
    # 发送给候选人
```

### 3. 候选人评分流程

```python
kb = get_knowledge_base()

# 候选人信息（从简历解析得到）
candidate = {
    "skills": ["Python", "Django", "MySQL", "Docker"],
    "experience_years": "4年",
    "education": "本科",
}

# 与岗位需求匹配
matches = kb.match_candidate_to_position(candidate)
for match in matches:
    print(f"岗位: {match['name']}, 匹配分数: {match['match_score']}")
    print(f"匹配原因: {match['match_reasons']}")
```

### 4. 发送面试确认

```python
kb = get_knowledge_base()

# 获取面试确认模板
feedback = kb.get_feedback_template("interview_confirm", {
    "name": "张三",
    "time": "周三 15:00",
    "address": "北京市朝阳区XX大厦1801",
})
message = feedback["text"]
# -> "您好 张三，很高兴通知您面试通过！请于 周三 15:00 到达 北京市朝阳区XX大厦1801 参加面试，收到请回复~"
```

### 5. 从聊天记录学习

```python
kb = get_knowledge_base()

# 传入历史聊天记录
report = kb.learn_from_chat_history([
    {"role": "hr", "message": "您好，看到您对应聘我们公司很感兴趣~"},
    {"role": "candidate", "message": "您好，请问这个岗位还招人吗？"},
    {"role": "hr", "message": "还在招的，请问您之前有相关经验吗？"},
    {"role": "candidate", "message": "我有3年Python开发经验。"},
])

print(f"新增打招呼话术: {len(report['greetings_added'])} 条")
print(f"新增话术模式: {len(report['patterns_added'])} 条")
```

### 6. 动态添加新话术

```python
kb = get_knowledge_base()

# 添加新的打招呼话术
kb.add_greeting(
    text="Hi {name}，发现您的背景和 {position} 岗位高度契合，有兴趣聊聊吗？",
    tags=["主动", "精准匹配"],
    priority=5,
    enabled=True
)

# 添加新的聊天话术模式
kb.add_chat_pattern(
    scenario="候选人询问工作地点",
    conditions=["地点", "地址", "位置", "通勤"],
    patterns=[
        "我们公司在望京 SOHO，地铁直达，通勤很方便~",
        "工作地点在朝阳区大望路，靠近地铁站，公交也方便~"
    ],
    follow_up="等待候选人确认通勤距离是否可接受"
)

# 保存到文件
kb.save()
```

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 数据文件存在 | `ls data/knowledge/*.json` | 4 个 JSON 文件存在 |

### 第三方依赖

**无第三方依赖**。本模块 100% 使用 Python 标准库（json, os, re, threading, dataclasses, pathlib, typing, random）。

> 这是唯一不需要安装任何 pip 包的 Skill 模块。

---

## 线程安全

`KnowledgeBase` 类内部使用 `threading.RLock` 保证线程安全，可以被多个模块并发调用而不会产生数据竞争。

## 注意事项

1. **修改后记得调用 `save()`**：所有添加、更新、删除操作都在内存中进行，需要调用 `save()` 才真正写入文件
2. **JSON 文件可手动编辑**：数据以标准 JSON 格式存储，可以直接用文本编辑器修改
3. **变量插值**：`{name}`、`{position}` 等占位符在调用时会自动替换，源文件中保留原始占位符格式
4. **新学习的话术默认禁用**：从聊天记录学习的新话术默认 `enabled=False`，需要人工审核后启用
