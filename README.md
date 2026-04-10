# OpenHR

> AI 驱动的 Boss 直聘自动化招聘 Skills 集合

基于 Playwright + LLM 的招聘全流程自动化——从筛选候选人、打招呼、智能聊天跟进到简历解析入飞书，一条龙搞定。

## Skills 一览

| Skill | 脚本 | 功能 | 依赖 |
|-------|------|------|------|
| **boss-login** | `scripts/boss_login.py` | 登录态管理，QR码扫码，Cookie 持久化 | playwright |
| **boss-greet** | `scripts/boss_greet.py` | 遍历推荐牛人，智能匹配岗位，发送个性化打招呼 | boss-login, anti-detect, knowledge-base |
| **chat-engine** | `scripts/chat_engine.py` | LLM 驱动的聊天引擎，状态机推进到面试确认 | boss-login, knowledge-base, LLM API |
| **resume-parser** | `scripts/resume_parser.py` + `scripts/feishu_upload.py` | 简历结构化提取 + 飞书多维表格写入（自动去重） | LLM API, 飞书 App |
| **knowledge-base** | `scripts/knowledge_base.py` | 话术库、岗位需求库、反馈模板，支持从聊天记录学习 | 无（纯标准库） |
| **anti-detect** | `scripts/anti_detect.py` | 风控对抗：随机间隔、鼠标轨迹、验证码检测、封号预警 | numpy |

## 流水线

```
① boss-login ──→ ② boss-greet ──→ ③ chat-engine
     ↑                 │                │
     │                 ↓                ↓
⑥ anti-detect     ④ resume-parser ──→ ⑤ knowledge-base
```

1. **登录** → 获取 Boss 直聘登录态
2. **打招呼** → 自动筛选匹配候选人并发送个性化消息
3. **聊天跟进** → LLM 自动回复，推进到面试确认
4. **简历解析** → 提取候选人信息，评分，写入飞书多维表格
5. **全程** 风控护航 + 知识库供给话术

## 快速开始

### 安装

```bash
# Python 3.10+
pip3 install playwright requests numpy
python3 -m playwright install chromium

# 无界面服务器需要 xvfb
sudo apt install xvfb
```

### 配置

```bash
# LLM API Key（必须）
export ZAI_API_KEY="your_glm5_api_key"

# 飞书配置（resume-parser 需要）
# 编辑 config/feishu.json，填入 app_secret / app_token / table_id
```

### 运行

```bash
# 1. 登录
xvfb-run -a python3 scripts/boss_login.py

# 2. 打招呼（先 dry-run 测试）
xvfb-run -a python3 scripts/boss_greet.py --dry-run
xvfb-run -a python3 scripts/boss_greet.py --max-greets 5

# 3. 聊天跟进
xvfb-run -a python3 scripts/chat_engine.py --poll-interval 30

# 4. 岗位配置
python3 scripts/config_position.py --list
python3 scripts/config_position.py --add
```

> 详细前置安装指南见 [docs/prerequisites.md](docs/prerequisites.md)

## 项目结构

```
openhr/
├── scripts/                    # 核心脚本（8个，5680行）
│   ├── boss_login.py           # 登录管理
│   ├── boss_greet.py           # 主动打招呼
│   ├── chat_engine.py          # 智能聊天引擎
│   ├── resume_parser.py        # 简历解析
│   ├── feishu_upload.py        # 飞书多维表格同步
│   ├── knowledge_base.py       # 知识库系统
│   ├── anti_detect.py          # 风控对抗
│   └── config_position.py      # 岗位配置 CLI
├── config/                     # 配置文件
│   ├── llm.json                # LLM 配置（GLM-5 / OpenRouter）
│   ├── anti_detect.json        # 风控参数
│   ├── feishu.json             # 飞书配置
│   ├── filters.json            # 候选人筛选条件
│   └── templates.json          # 打招呼/聊天模板
├── data/                       # 运行时数据
│   ├── cookies/                # 登录态（gitignore）
│   ├── chat_logs/              # 聊天记录（gitignore）
│   ├── knowledge/              # 知识库数据
│   └── templates/              # 模板缓存
├── skills/                     # 各模块 Skill 文档
├── docs/                       # 项目文档
│   ├── PRD.md                  # 产品需求文档
│   ├── implementation-plan.md  # 实施方案
│   ├── prerequisites.md        # 前置安装指南
│   └── skills-workflow.md      # 业务流程全景图
└── references/                 # 参考文档
    ├── boss-api.md             # Boss 直聘页面结构分析
    ├── feishu-bitable-api.md   # 飞书多维表格 API
    └── anti-detect-guide.md    # 风控对抗指南
```

## 技术栈

| 技术 | 用途 |
|------|------|
| Playwright (Python async) | 浏览器自动化（必须 headed 模式） |
| GLM-5-plus | LLM 聊天生成 + 简历解析评分 |
| 飞书 Bot API | 多维表格读写（候选人池） |
| numpy | 贝塞尔曲线鼠标轨迹模拟 |

## 每个 Skill 的详细文档

| Skill | 文档 |
|-------|------|
| boss-login | [skills/boss-login/SKILL.md](skills/boss-login/SKILL.md) |
| boss-greet | [skills/boss-greet/SKILL.md](skills/boss-greet/SKILL.md) |
| anti-detect | [skills/anti-detect/SKILL.md](skills/anti-detect/SKILL.md) |
| chat-engine | [skills/chat-engine/SKILL.md](skills/chat-engine/SKILL.md) |
| resume-parser | [skills/resume-parser/SKILL.md](skills/resume-parser/SKILL.md) |
| knowledge-base | [skills/knowledge-base/SKILL.md](skills/knowledge-base/SKILL.md) |

## 注意事项

- **必须 headed 模式运行**（`headless=False`），Boss 直聘反爬会识别 headless
- **不建议 headless 服务器裸跑**，用 `xvfb-run` 模拟显示
- **打招呼间隔 5-15s**，每日上限建议从 50 次起步
- **检测到验证码立即暂停**，等待人工处理
- **飞书配置需手动完成**：创建多维表格 → 填入 `config/feishu.json`

## License

MIT
