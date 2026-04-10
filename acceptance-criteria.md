# 验收标准 — OpenHR 自动化招聘智能体

## 概述
基于 Boss 直聘的全流程 AI 自动化招聘系统，6 大模块全部通过。

## 验收条件

### 1. [c1] Boss直聘登录模块
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/boss_login.py` + `~/clawd/projects/openhr/skills/boss-login/SKILL.md`
- **负责 Agent**: code
- **依赖**: 无
- **输出物**:
  - `scripts/boss_login.py` — 登录控制脚本（检测登录态、生成二维码、cookie持久化）
  - `skills/boss-login/SKILL.md` — 登录模块 Skill 文档
  - `data/cookies/` — cookie 存储目录
- **通过标准**:
  - 脚本可检测当前登录状态
  - 未登录时能触发二维码生成（通过 Playwright 截图）
  - cookie 可持久化到本地
  - 包含登录态过期检测逻辑

### 2. [c2] 风控对抗基础模块
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/anti_detect.py` + `~/clawd/projects/openhr/skills/anti-detect/SKILL.md`
- **负责 Agent**: code
- **依赖**: 无
- **输出物**:
  - `scripts/anti_detect.py` — 风控对抗脚本（随机间隔、行为模拟、指纹管理）
  - `skills/anti-detect/SKILL.md` — 风控模块 Skill
  - `config/anti_detect.json` — 风控参数配置
  - `references/anti-detect-guide.md` — 风控最佳实践文档
- **通过标准**:
  - 随机操作间隔（5-15s）实现
  - 验证码检测 + 暂停 + 通知机制
  - 封号预警逻辑
  - Playwright stealth 配置

### 3. [c3] 主动打招呼模块
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/boss_greet.py` + `~/clawd/projects/openhr/skills/boss-greet/SKILL.md`
- **负责 Agent**: code
- **依赖**: c1, c2
- **输出物**:
  - `scripts/boss_greet.py` — 自动打招呼脚本
  - `skills/boss-greet/SKILL.md` — 打招呼模块 Skill
  - `config/templates.json` — 打招呼模板配置
- **通过标准**:
  - 能遍历候选人列表
  - 按岗位需求筛选候选人
  - 个性化打招呼（基于模板+候选人信息）
  - 每日次数限制（默认100次）+ 当日已用计数
  - 操作间隔随机化（调用 anti_detect）

### 4. [c4] 简历解析 + 飞书多维表格
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/resume_parser.py` + `~/clawd/projects/openhr/scripts/feishu_upload.py`
- **负责 Agent**: code (主) + data (飞书API对接辅助)
- **依赖**: c1
- **输出物**:
  - `scripts/resume_parser.py` — 简历信息提取脚本
  - `scripts/feishu_upload.py` — 飞书多维表格上传脚本
  - `skills/resume-parser/SKILL.md` — 简历解析 Skill
  - `config/feishu.json` — 飞书多维表格配置（app_id, table_id, 字段映射）
  - `references/feishu-bitable-api.md` — 飞书API参考文档
- **通过标准**:
  - 能从聊天窗口/简历卡片提取关键信息（姓名、学历、经历、技能、期望薪资）
  - 结构化输出 JSON
  - 飞书多维表格写入接口实现
  - 去重逻辑（基于手机号/姓名+公司）

### 5. [c5] 智能聊天跟进引擎
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/chat_engine.py` + `~/clawd/projects/openhr/skills/chat-engine/SKILL.md`
- **负责 Agent**: code
- **依赖**: c1, c2, c5的知识库部分
- **输出物**:
  - `scripts/chat_engine.py` — 智能聊天引擎
  - `skills/chat-engine/SKILL.md` — 聊天引擎 Skill
- **通过标准**:
  - 监控候选人回复
  - LLM 生成上下文相关回复（结合岗位需求+候选人背景）
  - 状态机：打招呼 → 兴趣确认 → 面试意向 → 时间地点确认
  - 面试确认时提取时间和地点信息
  - 候选人拒绝 → 礼貌结束 + 记录原因

### 6. [c6] 知识库系统
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/scripts/knowledge_base.py` + `~/clawd/projects/openhr/skills/knowledge-base/SKILL.md`
- **负责 Agent**: code
- **依赖**: 无
- **输出物**:
  - `scripts/knowledge_base.py` — 知识库管理脚本
  - `skills/knowledge-base/SKILL.md` — 知识库 Skill
  - `data/knowledge/` — 知识库数据目录
    - `greetings.json` — 打招呼话术库
    - `chat_patterns.json` — 聊天话术模式库
    - `position_requirements.json` — 岗位需求库
    - `feedback_templates.json` — 反馈模板
- **通过标准**:
  - 话术库可读写（JSON格式）
  - 岗位需求库可配置
  - 支持从历史聊天记录中提取话术模式
  - 反馈模板可自定义

### 7. [c7] 参考文档完备
- **验证方法**: `file_exists`
- **验证目标**: `~/clawd/projects/openhr/references/boss-api.md`
- **负责 Agent**: research
- **依赖**: 无
- **输出物**:
  - `references/boss-api.md` — Boss直聘页面结构分析（URL、CSS选择器、关键DOM元素）
  - `references/feishu-bitable-api.md` — 飞书多维表格API文档
  - `references/anti-detect-guide.md` — 反检测最佳实践
- **通过标准**:
  - Boss直聘关键页面URL列表
  - 候选人列表页/聊天页/简历页的关键CSS选择器
  - 飞书多维表格API调用示例
  - 反检测技术清单
