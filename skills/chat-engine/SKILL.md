# chat-engine — 智能聊天跟进引擎 Skill

> OpenHR 项目 M4 模块 | 负责自动监控候选人回复并驱动聊天状态机推进至面试确认

---

## 触发条件

本 Skill 在以下情况下触发：

1. **定时轮询触发**：Boss 直聘聊天页（`https://www.zhipin.com/web/boss/chat`）已打开，且 Playwright Page 处于登录态
2. **手动调用**：`python3 scripts/chat_engine.py --poll-interval 30`
3. **子 agent 调用**：主 agent 通过 `spawn_subagent` 启动本模块

---

## 前置条件

> **通用前置安装**见 [docs/prerequisites.md](../../docs/prerequisites.md)，以下为本模块特有说明。

### 必须完成

| # | 步骤 | 命令 | 验证 |
|---|------|------|------|
| 1 | Python 3.10+ | `python3 --version` | ≥ 3.10 |
| 2 | 安装 Playwright | `pip3 install playwright` | `python3 -c "import playwright"` |
| 3 | 安装 Chromium | `python3 -m playwright install chromium` | 浏览器二进制文件存在 |
| 4 | 安装 requests | `pip3 install requests` | `python3 -c "import requests"` |
| 5 | 无界面服务器装 xvfb | `sudo apt install xvfb` | `which xvfb-run` 有输出 |
| 6 | 已完成 boss-login 登录 | `python3 scripts/boss_login.py --check` | 输出"已登录" |
| 7 | 配置 LLM API Key | `export ZAI_API_KEY="your_key"` | `echo $ZAI_API_KEY` 非空 |

### 内部模块依赖

| 模块 | 路径 | 用途 |
|------|------|------|
| 登录模块 | `scripts/boss_login.py` | 获取已登录 Playwright Page |
| 知识库 | `scripts/knowledge_base.py` | 聊天话术匹配、岗位需求 |

### 第三方依赖

| 包 | 用途 |
|----|------|
| `playwright` | 浏览器自动化（读取聊天列表、发送消息） |
| `requests` | 调用 LLM API（GLM-5 / OpenRouter） |

### 环境变量

| 变量 | 用途 | 必填 |
|------|------|------|
| `ZAI_API_KEY` | GLM-5 API Key（当前默认 provider） | 二选一 |
| `OPENROUTER_API_KEY` | OpenRouter API Key（备用 provider） | 二选一 |

> 具体使用哪个 key 由 `config/llm.json` 中的 `api_key_env` 字段决定。

### 运行命令

```bash
# 有图形界面
python3 scripts/chat_engine.py

# 无界面服务器
xvfb-run -a python3 scripts/chat_engine.py --poll-interval 30
```

---

## 状态机流转图

```
                    ┌──────────────────────────────────────┐
                    │           GREETING                    │
                    │   (打招呼阶段，HR 已发送初始消息)       │
                    └──────────────┬───────────────────────┘
                                   │ 候选人回复
                                   ▼
                    ┌──────────────────────────────────────┐
                    │        INTEREST_CONFIRM               │
                    │        (兴趣确认阶段)                  │
                    │  HR 询问面试意向，候选人表示有兴趣     │
                    └──────────────┬───────────────────────┘
                                   │ 候选人说"感兴趣/可以/好"
                                   ▼
                    ┌──────────────────────────────────────┐
                    │         INTERVIEW_INTENT              │
                    │         (面试意向阶段)                 │
                    │  HR 引导确认面试时间/地点              │
                    └──────────────┬───────────────────────┘
                                   │ 候选人表达面试意向
                                   ▼
                    ┌──────────────────────────────────────┐
                    │       TIME_PLACE_CONFIRM              │
                    │       (时间地点确认阶段)               │
                    │  提取面试日期+时间（自动）              │
                    └──────────────┬───────────────────────┘
                                   │ 确认时间+地点
                    ┌──────────────┴───────────────────────┐
                    │                                       │
          ┌─────────▼─────────┐               ┌──────────▼──────────┐
          │     COMPLETED      │               │      REJECTED        │
          │   (面试已确认)      │               │   (候选人拒绝)       │
          │   ★ 终态，保存日志  │               │   ★ 终态，记录原因    │
          └───────────────────┘               └─────────────────────┘
```

---

## 执行步骤

### 步骤 1：初始化 ChatEngine
```python
from scripts.chat_engine import ChatEngine
from scripts.knowledge_base import KnowledgeBase
import json

# 加载 LLM 配置
with open("config/llm.json") as f:
    llm_config = json.load(f)

# 初始化知识库
kb = KnowledgeBase()

# 创建引擎实例
engine = ChatEngine(
    page=page,                  # Playwright Page（需已登录聊天页）
    kb=kb,                      # KnowledgeBase 实例
    llm_config=llm_config,       # LLM 配置文件
    poll_interval=30,           # 轮询间隔（秒）
    chat_log_dir=Path("data/chat_logs"),
)
```

### 步骤 2：启动监控
```python
await engine.start()   # 异步主循环，阻塞直到 stop()
```

### 步骤 3：处理单个会话
```python
await engine.process_session("candidate_id_xxx")
```

### 步骤 4：停止引擎
```python
await engine.stop()
```

### 步骤 5：获取会话摘要（运行时监控）
```python
summary = engine.get_sessions_summary()
for s in summary:
    print(f"{s['candidate_name']}: {s['state']} | {s['message_count']}条消息")
```

---

## LLM 调用配置说明

### 默认 Provider：OpenRouter

配置文件：`config/llm.json`

```json
{
  "provider": "openrouter",
  "api_key_env": "OPENROUTER_API_KEY",
  "model": "anthropic/claude-3.5-sonnet",
  "base_url": "https://openrouter.ai/api/v1",
  "max_tokens": 500,
  "temperature": 0.7,
  "retry_times": 3,
  "fallback_models": ["openai/gpt-4o-mini", "google/gemini-2.0-flash-exp"],
  "system_prompt": "你是一位专业的HR招聘助手..."
}
```

### 切换 Provider（示例：切换到 OpenAI 直连）

```python
from scripts.chat_engine import register_llm_provider, create_llm_provider

class OpenAIProvider(LLMProvider):
    def __init__(self, config):
        self.api_key = os.environ["OPENAI_API_KEY"]
        ...

    def generate(self, prompt, system_prompt="", max_tokens=500, temperature=0.7, model=""):
        import openai
        client = openai.OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=[{"role":"system","content":system_prompt}, {"role":"user","content":prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return resp.choices[0].message.content.strip()

register_llm_provider("openai", OpenAIProvider)

# 修改 config/llm.json: {"provider": "openai", ...}
llm = create_llm_provider(llm_config)
```

### 重试机制

- 默认重试 3 次
- 遇到 429（限流）自动等待并重试
- 有 `fallback_models` 时自动切换模型

---

## 聊天记录持久化

路径：`data/chat_logs/candidate_{姓名}_{时间戳}.json`

```json
{
  "candidate_id": "张三_0_1744041600",
  "candidate_name": "张三",
  "position": "Python后端开发",
  "state": "COMPLETED",
  "messages": [
    {"sender": "boss", "text": "您好！我是HR...", "timestamp": "..."},
    {"sender": "candidate", "text": "感兴趣，请问薪资范围？", "timestamp": "..."}
  ],
  "interview_details": {
    "date": "周三",
    "time": "15:00",
    "address": "",
    "method": "视频面试",
    "raw_text": "周三 15:00 视频面试"
  },
  "reject_reason": "",
  "resume_info": {...},
  "created_at": "2026-04-07T10:00:00",
  "updated_at": "2026-04-07T10:30:00",
  "llm_reply_count": 5
}
```

---

## 命令行用法

### 基本启动（需要先运行 boss_login.py）
```bash
python3 scripts/chat_engine.py
```

### 指定轮询间隔
```bash
python3 scripts/chat_engine.py --poll-interval 60
```

### 指定聊天页 URL
```bash
python3 scripts/chat_engine.py --chat-url "https://www.zhipin.com/web/boss/chat"
```

### 指定 LLM 配置文件
```bash
python3 scripts/chat_engine.py --llm-config "config/llm.json"
```

### 指定日志目录
```bash
python3 scripts/chat_engine.py --log-dir "data/chat_logs"
```

### 完整示例
```bash
export ZAI_API_KEY=your_key
python3 scripts/chat_engine.py \
    --poll-interval 30 \
    --llm-config config/llm.json \
    --log-dir data/chat_logs
```

---

## 关键类/函数一览

| 类/函数 | 说明 |
|--------|------|
| `ChatEngine` | 核心引擎类，包含状态机 + LLM 调用 + 消息发送 |
| `ChatState` | 状态枚举：`GREETING` → `INTEREST_CONFIRM` → `INTERVIEW_INTENT` → `TIME_PLACE_CONFIRM` → `COMPLETED` / `REJECTED` |
| `CandidateSession` | 单个候选人会话的数据结构（含状态、消息、面试详情） |
| `ChatMessage` | 单条消息结构（sender/text/timestamp） |
| `InterviewDetails` | 面试详情（日期/时间/地点/方式） |
| `InterviewExtractor` | 从聊天文本提取面试信息的工具类 |
| `LLMProvider` | LLM 抽象基类 |
| `OpenRouterProvider` | OpenRouter API 实现（默认） |
| `create_llm_provider(config)` | 根据配置创建 LLM Provider |
| `register_llm_provider(name, cls)` | 注册自定义 Provider |
| `detect_rejection(message)` | 检测拒绝意图，返回 (是否拒绝, 关键词) |
| `build_dedup_key(...)` | 生成候选人去重 Key |

---

## 注意事项

1. **Boss 直聘 SPA 特性**：页面是动态加载的，每次获取消息都需要等 2-3 秒让 DOM 渲染
2. **轮询频率**：建议 30-60 秒，过于频繁容易触发风控
3. **消息去重**：内部用 `_seen_messages` 缓存避免重复处理同一消息
4. **终态处理**：COMPLETED / REJECTED 后不再发送消息，仅记录日志
5. **LLM 失败兜底**：LLM 调用失败时自动回退到知识库模板，不阻塞流程
6. **数据安全**：聊天日志包含候选人个人信息，请妥善保管

---

## 演进建议

- **R6（集成测试）**：将聊天引擎与打招呼模块、简历解析模块串联，形成完整招聘闭环
- **优先级队列**：根据候选人回复速度和质量动态调整轮询优先级
- **飞书通知**：面试确认后自动发送飞书消息给 HR 和候选人
