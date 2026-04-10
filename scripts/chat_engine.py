# -*- coding: utf-8 -*-
"""
OpenHR 智能聊天跟进引擎 (c5)
============================
自动监控候选人回复，驱动聊天状态机，调用 LLM 生成上下文相关回复，
推进到面试时间地点确认，并将聊天记录持久化到 data/chat_logs/。

依赖:
    - playwright
    - requests（用于 OpenRouter API 调用）
    - 参考: scripts/boss_login.py, scripts/knowledge_base.py, scripts/resume_parser.py
    - 参考: references/boss-api.md, config/llm.json

用法（作为模块导入）:
    from scripts.chat_engine import ChatEngine, ChatState
    engine = ChatEngine(context, kb, llm_config)
    await engine.start()

用法（命令行）:
    python scripts/chat_engine.py --poll-interval 30
"""

from __future__ import annotations

import abc
import asyncio
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 项目路径配置
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CHAT_LOGS_DIR = PROJECT_ROOT / "data" / "chat_logs"
CHAT_LOGS_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 状态机枚举
# ---------------------------------------------------------------------------

class ChatState(Enum):
    """聊天状态枚举"""
    GREETING = "GREETING"                    # 打招呼阶段
    INTEREST_CONFIRM = "INTEREST_CONFIRM"     # 兴趣确认
    INTERVIEW_INTENT = "INTERVIEW_INTENT"     # 面试意向
    TIME_PLACE_CONFIRM = "TIME_PLACE_CONFIRM" # 时间地点确认
    COMPLETED = "COMPLETED"                   # 已确认面试（终态）
    REJECTED = "REJECTED"                    # 候选人拒绝（终态）
    UNKNOWN = "UNKNOWN"                      # 未知状态（初始）


# ---------------------------------------------------------------------------
# 消息数据结构
# ---------------------------------------------------------------------------

@dataclass
class ChatMessage:
    """单条聊天消息"""
    sender: str           # "boss" | "candidate" | "system"
    text: str
    timestamp: str = ""   # ISO 格式时间戳
    raw_html: str = ""    # 原始 HTML（供调试）

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InterviewDetails:
    """面试详情（从聊天中提取）"""
    date: str = ""        # 日期，如 "周三"、"4月10日"
    time: str = ""        # 时间，如 "15:00"、"下午3点"
    address: str = ""     # 地点/地址
    method: str = ""      # 面试方式，如 "线下面试"、"视频面试"
    raw_text: str = ""    # 原始提取文本

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CandidateSession:
    """单个候选人的聊天会话状态"""
    candidate_id: str                      # 候选人唯一标识（去重 key）
    candidate_name: str = ""               # 候选人姓名
    position: str = ""                     # 岗位名称
    state: ChatState = ChatState.UNKNOWN   # 当前状态
    messages: list[ChatMessage] = field(default_factory=list)   # 聊天记录
    interview_details: Optional[InterviewDetails] = None  # 面试详情
    reject_reason: str = ""                 # 拒绝原因
    resume_info: Optional[dict] = None     # 候选人简历信息（来自 resume_parser）
    created_at: str = ""                   # 会话创建时间
    updated_at: str = ""                   # 最后更新时间
    llm_reply_count: int = 0               # LLM 生成回复次数

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "position": self.position,
            "state": self.state.value,
            "messages": [m.to_dict() for m in self.messages],
            "interview_details": self.interview_details.to_dict() if self.interview_details else None,
            "reject_reason": self.reject_reason,
            "resume_info": self.resume_info,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "llm_reply_count": self.llm_reply_count,
        }

    def save(self, log_dir: Path = CHAT_LOGS_DIR) -> Path:
        """将会话持久化到 JSON 文件"""
        log_dir.mkdir(parents=True, exist_ok=True)
        # 文件名：candidate_{short_id}_{timestamp}.json
        safe_name = re.sub(r'[^\w\-]', '_', self.candidate_name or self.candidate_id)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = log_dir / f"candidate_{safe_name}_{ts}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        return filepath


# ---------------------------------------------------------------------------
# LLM 抽象接口
# ---------------------------------------------------------------------------

class LLMProvider(abc.ABC):
    """
    LLM Provider 抽象基类。
    支持自定义 provider，只需实现 generate() 方法，
    并在 register_provider() 中注册即可切换。
    """

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = 500, temperature: float = 0.7,
                 model: str = "") -> str:
        """
        调用 LLM 生成文本。

        Args:
            prompt: 用户输入 prompt
            system_prompt: 系统提示词
            max_tokens: 最大 token 数
            temperature: 温度参数
            model: 模型名称（可选）

        Returns:
            LLM 生成的文本内容
        """
        raise NotImplementedError


class HTTPChatProvider(LLMProvider):
    """
    OpenAI 兼容 API Provider（支持 zai / OpenRouter / 任意 OpenAI 兼容接口）。
    默认使用 config/llm.json 中的配置。
    """

    def __init__(self, config: dict):
        self.api_key = os.environ.get(
            config.get("api_key_env", "ZAI_API_KEY"), ""
        )
        self.base_url = config.get("base_url", "https://open.bigmodel.cn/api/paas/v4")
        self.model = config.get("model", "glm-5-plus")
        self.max_tokens = config.get("max_tokens", 500)
        self.temperature = config.get("temperature", 0.7)
        self.timeout = config.get("timeout_seconds", 30)
        self.retry_times = config.get("retry_times", 3)
        self.retry_delay = config.get("retry_delay_seconds", 5)
        self.fallback_models = config.get("fallback_models", [])

    def generate(self, prompt: str, system_prompt: str = "",
                 max_tokens: int = None, temperature: float = None,
                 model: str = "") -> str:
        import requests

        actual_model = model or self.model
        actual_max_tokens = max_tokens or self.max_tokens
        actual_temp = temperature if temperature is not None else self.temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": actual_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": actual_max_tokens,
            "temperature": actual_temp,
        }

        # 构建完整 URL（base_url 末尾已带 /v4 则不重复拼）
        base = self.base_url.rstrip("/")
        url = f"{base}/chat/completions"

        # 重试逻辑
        tried_models = [actual_model]
        errors = []

        for attempt in range(self.retry_times):
            try:
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["choices"][0]["message"]["content"].strip()
                elif resp.status_code == 429:
                    errors.append(f"429 rate limit on {actual_model}")
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    errors.append(f"{resp.status_code}: {resp.text[:200]}")
                    if self.fallback_models:
                        for fb_model in self.fallback_models:
                            if fb_model not in tried_models:
                                actual_model = fb_model
                                tried_models.append(fb_model)
                                payload["model"] = actual_model
                                break
            except requests.exceptions.RequestException as e:
                errors.append(f"Request error: {e}")
                time.sleep(self.retry_delay)

        raise RuntimeError(
            f"LLM 调用失败（已重试 {self.retry_times} 次）: {'; '.join(errors)}"
        )


# Provider 注册表
_llm_providers: dict[str, type[LLMProvider]] = {
    "openrouter": HTTPChatProvider,
    "zai": HTTPChatProvider,
    "http": HTTPChatProvider,
}


def register_llm_provider(name: str, cls: type[LLMProvider]) -> None:
    """注册自定义 LLM Provider"""
    _llm_providers[name] = cls


def create_llm_provider(config: dict) -> LLMProvider:
    """根据配置创建 LLM Provider 实例"""
    provider_name = config.get("provider", "openrouter")
    cls = _llm_providers.get(provider_name)
    if cls is None:
        raise ValueError(f"未知的 LLM provider: {provider_name}，可用: {list(_llm_providers.keys())}")
    return cls(config)


# ---------------------------------------------------------------------------
# 面试信息提取
# ---------------------------------------------------------------------------

class InterviewExtractor:
    """
    从聊天文本中提取面试时间/地点/方式信息。
    支持多种表达形式的模糊识别。
    """

    # 日期匹配
    DATE_PATTERNS = [
        re.compile(r'(\d{1,2})月(\d{1,2})日'),
        re.compile(r'(本周|下周)?(周[一二三四五六日]|星期[一二三四五六日])'),
        re.compile(r'(周一|周二|周三|周四|周五|周六|周日)'),
        re.compile(r'(\d{1,2})号'),
    ]

    # 时间匹配
    TIME_PATTERNS = [
        re.compile(r'(\d{1,2})[:：](\d{2})\s*(点|时|hours?)'),
        re.compile(r'(上午|下午|早上|晚上|上午|中午)\s*(\d{1,2})[:：]?(\d{2})?'),
        re.compile(r'(\d{1,2})\s*(点|时)\s*(\d{1,2})?\s*(分)?'),
    ]

    # 地点匹配
    ADDRESS_PATTERNS = [
        re.compile(r'(在|到|去|面试地点|地址|地址是)\s*[:：]?\s*(.{2,50})'),
        re.compile(r'(线上|视频|电话|腾讯会议|钉钉|zoom)\s*(面试|沟通)?'),
    ]

    def extract(self, text: str) -> InterviewDetails:
        details = InterviewDetails(raw_text=text)

        # 提取日期
        for pat in self.DATE_PATTERNS:
            m = pat.search(text)
            if m:
                details.date = m.group(0)
                break

        # 提取时间
        for pat in self.TIME_PATTERNS:
            m = pat.search(text)
            if m:
                details.time = m.group(0)
                break

        # 提取地点
        for pat in self.ADDRESS_PATTERNS:
            m = pat.search(text)
            if m:
                matched = m.group(0)
                # 线上/视频关键词
                if any(kw in matched for kw in ["线上", "视频", "电话", "腾讯会议", "zoom"]):
                    details.method = "视频面试"
                    details.address = matched
                else:
                    details.address = matched
                break

        # 识别面试方式
        if "视频" in text or "腾讯会议" in text or "zoom" in text.lower():
            details.method = "视频面试"
        elif "线下面试" in text or "公司" in text or "办公室" in text:
            details.method = "线下面试"
        elif "电话" in text:
            details.method = "电话面试"

        return details


# ---------------------------------------------------------------------------
# 拒绝意图检测
# ---------------------------------------------------------------------------

REJECT_KEYWORDS = [
    "不需要", "不考虑", "不感兴趣", "暂时不", "已找到", "已有offer",
    "不想换", "不想面试", "算了", "不用了", "不需要招人",
    "不合适", "不想去", "不考虑了", "谢谢", "打扰了",
]


def detect_rejection(message: str) -> tuple[bool, str]:
    """
    检测候选人消息中的拒绝意图。

    Returns:
        (是否拒绝, 拒绝原因/拒绝关键词)
    """
    msg = message.strip().lower()
    for kw in REJECT_KEYWORDS:
        if kw in msg:
            return True, kw
    return False, ""


# ---------------------------------------------------------------------------
# 核心聊天引擎
# ---------------------------------------------------------------------------

class ChatEngine:
    """
    智能聊天跟进引擎。

    负责：
    1. 使用 Playwright 轮询监控聊天列表，检测候选人新回复
    2. 根据聊天状态机推进会话
    3. 调用 LLM 生成上下文相关回复
    4. 持久化聊天记录到 data/chat_logs/

    Args:
        page: Playwright Page 对象（需已登录 Boss 直聘并处于聊天页）
        kb: KnowledgeBase 实例（知识库，提供话术模式和岗位需求）
        llm_config: LLM 配置文件字典（来自 config/llm.json）
        poll_interval: 轮询间隔（秒），默认 30 秒
    """

    # Boss 直聘聊天页选择器（参考 references/boss-api.md）
    # CSS 选择器优先，XPath 降级策略在 _robust_locator() 中实现
    SELECTORS = {
        "session_list": "aside li, [class*='session'], [class*='conversation'], a[href*='chat'], [role='listitem']",
        "message_area": "main, [class*='message'], [class*='chat-content'], [class*='msg-list'], [role='main']",
        "message_item": "[class*='message-item'], [class*='msg'], li, [class*='chat-msg']",
        "input_box": "textarea, div[contenteditable='true'], [role='textbox'], [contenteditable]",
        "send_button": (
            "button:has-text('发送'), button:has-text('发 送'), "
            "button:has-text('send'), [class*='send-btn'], [class*='sendBtn']"
        ),
        "unread_badge": "[class*='unread'], [class*='badge'], [class*='unread-count']",
        "candidate_name": "h3, h4, strong, [class*='name'], [class*='candidate-name'], [class*='user-name']",
        "last_message": "[class*='message-item']:last-child, [class*='msg']:last-child, li:last-child, [class*='preview']:last-child",
    }

    # XPath 降级选择器（当 CSS 失败时使用）
    XPATH_SELECTORS = {
        "session_list": "//aside//li | //a[contains(@href, 'chat')]",
        "message_area": "//main | //*[contains(@class, 'message')] | //*[contains(@class, 'chat-content')]",
        "input_box": "//textarea | //div[@contenteditable='true'] | //*[@role='textbox']",
        "send_button": "//button[contains(text(), '发送')] | //button[contains(@class, 'send')]",
    }

    def _robust_locator(self, key: str):
        """
        获取定位器：CSS 优先，XPath 降级

        Args:
            key: SELECTORS 字典的键名

        Returns:
            Playwright Locator
        """
        css = self.SELECTORS.get(key, "")
        xpath = self.XPATH_SELECTORS.get(key, "")
        if not css:
            return None
        try:
            locator = self.page.locator(css)
            elem = locator.first
            if elem:
                return locator
        except Exception:
            pass
        # CSS 失败，尝试 XPath
        if xpath:
            try:
                xlocator = self.page.locator(f"xpath={xpath}")
                elem = xlocator.first
                if elem:
                    print(f"[ChatEngine] CSS 选择器失败，降级到 XPath: {key}")
                    return xlocator
            except Exception:
                pass
        # 最后兜底：返回原始 CSS
        return self.page.locator(css)

    def __init__(
        self,
        page,                           # Playwright Page
        kb,                             # KnowledgeBase instance
        llm_config: dict,
        poll_interval: int = 30,
        chat_log_dir: Path = CHAT_LOGS_DIR,
    ):
        self.page = page
        self.kb = kb
        self.poll_interval = poll_interval
        self.log_dir = chat_log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # LLM Provider（兼容旧配置中 provider=openrouter 的用法）
        provider_name = llm_config.get("provider", "")
        self.llm = create_llm_provider(llm_config)
        self.llm_system_prompt = llm_config.get(
            "system_prompt",
            "你是一位专业的HR招聘助手，擅长与候选人沟通，推动面试流程。"
        )

        # 状态机：candidate_id -> CandidateSession
        self._sessions: dict[str, CandidateSession] = {}

        # 面试信息提取器
        self._interview_extractor = InterviewExtractor()

        # 候选人ID生成计数器
        self._id_counter = 0

        # 运行时标志
        self._running = False
        self._stop_event = asyncio.Event()

        # 新消息缓存（用于去重，避免重复处理同一条消息）
        self._seen_messages: set[str] = set()

    # ========================================================================
    # 公共 API
    # ========================================================================

    async def start(self) -> None:
        """启动聊天监控引擎（异步主循环）"""
        self._running = True
        self._stop_event.clear()
        print(f"[ChatEngine] 启动聊天监控引擎，轮询间隔 {self.poll_interval}s")

        try:
            while self._running and not self._stop_event.is_set():
                try:
                    await self._poll_once()
                except Exception as e:
                    print(f"[ChatEngine] 轮询异常: {e}")
                # 等待下一次轮询或停止信号
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self.poll_interval
                    )
                except asyncio.TimeoutError:
                    pass  # 正常超时，继续下一轮
        finally:
            self._running = False
            print("[ChatEngine] 聊天监控引擎已停止")

    async def stop(self) -> None:
        """停止聊天监控引擎"""
        self._running = False
        self._stop_event.set()

    async def process_session(self, candidate_id: str) -> None:
        """
        处理指定候选人的聊天会话。

        Args:
            candidate_id: 候选人唯一标识
        """
        if candidate_id not in self._sessions:
            print(f"[ChatEngine] 未知 candidate_id: {candidate_id}")
            return

        session = self._sessions[candidate_id]
        try:
            new_messages = await self._fetch_new_messages(session)
            for msg in new_messages:
                await self._handle_candidate_message(session, msg)
        except Exception as e:
            print(f"[ChatEngine] 处理会话 {candidate_id} 异常: {e}")

    # ========================================================================
    # 内部：轮询逻辑
    # ========================================================================

    async def _poll_once(self) -> None:
        """
        执行一次轮询：
        1. 获取会话列表
        2. 遍历每个会话，检测新消息
        3. 对有新消息的会话进行处理
        """
        sessions = await self._fetch_session_list()
        if not sessions:
            print(f"[ChatEngine] [{datetime.now():%H:%M:%S}] 未检测到聊天会话")
            return

        print(f"[ChatEngine] [{datetime.now():%H:%M:%S}] 检测到 {len(sessions)} 个会话")

        for session_info in sessions:
            candidate_id = session_info["candidate_id"]
            session = self._sessions.get(candidate_id)

            if session is None:
                # 新会话，初始化
                session = CandidateSession(
                    candidate_id=candidate_id,
                    candidate_name=session_info.get("name", ""),
                    position=session_info.get("position", ""),
                    state=ChatState.GREETING,
                    created_at=datetime.now().isoformat(),
                )
                self._sessions[candidate_id] = session
                print(f"[ChatEngine] 新会话: {session.candidate_name} ({candidate_id})")

            # 获取新消息
            try:
                new_messages = await self._fetch_new_messages(session)
                for msg in new_messages:
                    await self._handle_candidate_message(session, msg)
            except Exception as e:
                print(f"[ChatEngine] 处理会话 {candidate_id} 异常: {e}")

    async def _fetch_session_list(self) -> list[dict]:
        """
        获取当前会话列表（聊天列表页左侧栏）。
        返回 [{candidate_id, name, position, last_msg_preview}, ...]
        """
        sessions = []
        try:
            # 等待会话列表加载
            await asyncio.sleep(2)  # 等 SPA 渲染

            # 尝试多个选择器
            list_selectors = [
                "aside li",
                "[class*='session']",
                "[class*='conversation']",
                "aside a[href*='chat']",
            ]

            items = None
            for sel in list_selectors:
                try:
                    locator = self.page.locator(sel)
                    count = await locator.count()
                    if count > 0:
                        items = locator
                        print(f"[ChatEngine] 会话列表选择器命中: {sel}, 数量: {count}")
                        break
                except Exception:
                    pass

            if items is None:
                return sessions

            for i in range(await items.count()):
                try:
                    item = items.nth(i)
                    if not await item.is_visible():
                        continue

                    # 提取候选人姓名
                    name = ""
                    for name_sel in ["h3", "h4", "strong", "[class*='name']"]:
                        try:
                            name_elem = item.locator(name_sel).first
                            if await name_elem.is_visible(timeout=1000):
                                name = (await name_elem.inner_text()).strip()
                                if name:
                                    break
                        except Exception:
                            pass

                    # 提取最后一条消息预览
                    preview = ""
                    try:
                        msg_elem = item.locator("[class*='last'], [class*='preview'], [class*='msg']").first
                        if await msg_elem.is_visible(timeout=1000):
                            preview = (await msg_elem.inner_text()).strip()[:100]
                    except Exception:
                        pass

                    # 生成 candidate_id（使用 name + index 作为唯一标识）
                    candidate_id = self._generate_candidate_id(name, i)

                    sessions.append({
                        "candidate_id": candidate_id,
                        "name": name,
                        "position": "",
                        "last_msg_preview": preview,
                    })
                except Exception as e:
                    print(f"[ChatEngine] 遍历会话项 {i} 异常: {e}")

        except Exception as e:
            print(f"[ChatEngine] 获取会话列表异常: {e}")

        return sessions

    async def _fetch_new_messages(self, session: CandidateSession) -> list[ChatMessage]:
        """
        获取候选人的新消息（自上次处理之后）。

        Returns:
            新消息列表（ChatMessage 对象）
        """
        new_messages = []

        try:
            # 点击该候选人的会话，进入聊天详情
            # 先找到对应的会话元素并点击
            session_items = self.page.locator("aside li, [class*='session']")
            count = await session_items.count()

            target_item = None
            for i in range(count):
                try:
                    item = session_items.nth(i)
                    if not await item.is_visible():
                        continue
                    # 提取名字对比
                    for name_sel in ["h3", "h4", "strong", "[class*='name']"]:
                        try:
                            name_elem = item.locator(name_sel).first
                            if await name_elem.is_visible(timeout=1000):
                                name = (await name_elem.inner_text()).strip()
                                if name == session.candidate_name:
                                    target_item = item
                                    break
                        except Exception:
                            pass
                    if target_item:
                        break
                except Exception:
                    pass

            if target_item:
                await target_item.click()
                await asyncio.sleep(3)  # 等待聊天详情加载

            # 获取消息列表
            msg_items = self.page.locator(
                "[class*='message-item'], [class*='msg'], li"
            )
            msg_count = await msg_items.count()

            for i in range(msg_count):
                try:
                    msg_elem = msg_items.nth(i)
                    if not await msg_elem.is_visible():
                        continue

                    text = (await msg_elem.inner_text()).strip()
                    if not text:
                        continue

                    # 生成消息唯一标识（用于去重）
                    msg_key = f"{session.candidate_id}:{text[:50]}"
                    if msg_key in self._seen_messages:
                        continue
                    self._seen_messages.add(msg_key)

                    # 限制缓存大小
                    if len(self._seen_messages) > 1000:
                        # 保留最新的 500 个
                        kept = list(self._seen_messages)[-500:]
                        self._seen_messages = set(kept)

                    # 判断发送者方向（通过 class 或位置）
                    sender = self._detect_sender(msg_elem)

                    # 跳过 boss 自己的消息（我们发送的不需要处理）
                    if sender == "boss":
                        continue

                    # 提取时间戳
                    timestamp = datetime.now().isoformat()

                    new_messages.append(ChatMessage(
                        sender=sender,
                        text=text,
                        timestamp=timestamp,
                    ))

                except Exception as e:
                    print(f"[ChatEngine] 解析消息 {i} 异常: {e}")

        except Exception as e:
            print(f"[ChatEngine] 获取新消息异常: {e}")

        return new_messages

    def _detect_sender(self, msg_elem) -> str:
        """
        检测消息发送者方向。

        通过 class 属性判断：
        - boss 发的消息通常在右侧，或 class 含 "boss" / "hr" / "mine"
        - candidate 发的消息通常在左侧，或 class 含 "candidate" / "other"
        """
        try:
            classes = msg_elem.get_attribute("class") or ""
            classes_lower = classes.lower()

            if any(kw in classes_lower for kw in ["boss", "hr", "mine", "right"]):
                return "boss"
            elif any(kw in classes_lower for kw in ["candidate", "other", "left"]):
                return "candidate"
            else:
                # 默认通过 DOM 结构判断（左侧 vs 右侧）
                style = msg_elem.get_attribute("style") or ""
                if "right" in style.lower():
                    return "boss"
                elif "left" in style.lower():
                    return "candidate"
        except Exception:
            pass

        return "unknown"

    # ========================================================================
    # 内部：消息处理 & 状态机
    # ========================================================================

    async def _handle_candidate_message(
        self, session: CandidateSession, msg: ChatMessage
    ) -> None:
        """
        处理候选人的单条消息，驱动状态机前进，并决定是否需要回复。
        """
        # 追加到聊天记录
        session.messages.append(msg)
        session.updated_at = datetime.now().isoformat()

        print(f"[ChatEngine] [{session.candidate_name}] 新消息({msg.sender}): {msg.text[:80]}")

        # ---- 拒绝检测（所有状态都做） ----
        is_reject, reject_kw = detect_rejection(msg.text)
        if is_reject:
            await self._transition_to(
                session, ChatState.REJECTED,
                reject_reason=f"检测到拒绝关键词: {reject_kw}"
            )
            reply = await self._generate_reject_reply(session, reject_kw)
            await self._send_reply(session, reply)
            session.save(self.log_dir)
            return

        # ---- 面试详情提取（TIME_PLACE_CONFIRM 状态） ----
        if session.state == ChatState.TIME_PLACE_CONFIRM:
            interview = self._interview_extractor.extract(msg.text)
            if interview.date or interview.time or interview.address:
                session.interview_details = interview
                print(f"[ChatEngine] 提取到面试详情: {interview.to_dict()}")

        # ---- 状态机推进 ----
        next_state = self._compute_next_state(session, msg)
        if next_state and next_state != session.state:
            await self._transition_to(session, next_state)

        # ---- 生成并发送回复 ----
        reply = await self._generate_reply(session, msg)
        if reply:
            await self._send_reply(session, reply)

        # ---- 持久化 ----
        session.save(self.log_dir)

    async def _transition_to(
        self, session: CandidateSession, new_state: ChatState,
        **extra
    ) -> None:
        """状态转换（带日志）"""
        old = session.state.value
        session.state = new_state
        session.updated_at = datetime.now().isoformat()

        for k, v in extra.items():
            setattr(session, k, v)

        print(
            f"[ChatEngine] [{session.candidate_name}] 状态: {old} → {new_state.value}"
        )

    def _compute_next_state(
        self, session: CandidateSession, msg: ChatMessage
    ) -> ChatState:
        """
        根据当前状态和消息内容，计算下一状态。
        """
        text = msg.text
        state = session.state

        if state == ChatState.UNKNOWN:
            return ChatState.GREETING

        if state == ChatState.GREETING:
            # 候选人回复了打招呼 → 进入兴趣确认
            return ChatState.INTEREST_CONFIRM

        if state == ChatState.INTEREST_CONFIRM:
            # 确认意向关键词
            positive_kw = ["感兴趣", "可以", "好的", "没问题", "聊聊", "有兴趣",
                            "了解", "看下", "感兴趣", "在招"]
            if any(kw in text for kw in positive_kw):
                return ChatState.INTERVIEW_INTENT
            # 继续问问题 → 保持在当前状态
            return state

        if state == ChatState.INTERVIEW_INTENT:
            # 表达面试意向 → 进入时间地点确认
            intent_kw = ["面试", "面谈", "可以", "好", "去", "来", "约"]
            if any(kw in text for kw in intent_kw):
                return ChatState.TIME_PLACE_CONFIRM
            return state

        if state == ChatState.TIME_PLACE_CONFIRM:
            # 已确认时间地点（候选人明确回复时间/地点）→ COMPLETED
            interview = self._interview_extractor.extract(text)
            if interview.date and interview.time:
                return ChatState.COMPLETED
            return state

        # COMPLETED / REJECTED 为终态，不变
        return state

    # ========================================================================
    # 内部：LLM 回复生成
    # ========================================================================

    async def _generate_reply(
        self, session: CandidateSession, msg: ChatMessage
    ) -> str:
        """
        调用 LLM 生成回复。

        构建 prompt 时包含：
        1. 系统提示词（HR 人设）
        2. 当前聊天状态
        3. 岗位需求（从知识库）
        4. 候选人背景（resume_parser 结果）
        5. 历史聊天上下文（最近 6 条）
        6. 知识库的聊天话术模式（如果有匹配的）
        """
        # 状态提示
        state_hints = {
            ChatState.GREETING: "候选人是刚刚打招呼，需要先用友好的方式介绍自己和岗位。",
            ChatState.INTEREST_CONFIRM: "候选人表达了初步兴趣，需要确认对方是否真的对这个岗位感兴趣，询问是否有面试意向。",
            ChatState.INTERVIEW_INTENT: "候选人表达了面试意向，需要引导对方确认时间和地点。",
            ChatState.TIME_PLACE_CONFIRM: "正在确认面试时间和地点，请根据候选人的回复确认具体安排。",
        }
        state_hint = state_hints.get(session.state, "")

        # 知识库岗位需求
        position_info = ""
        if session.position:
            pos = self.kb.get_position_by_name(session.position)
            if pos:
                position_info = (
                    f"岗位名称：{pos.get('name', '')}\n"
                    f"技能要求：{', '.join(pos.get('skills', []))}\n"
                    f"薪资范围：{pos.get('salary_range', '')}\n"
                    f"工作地点：{pos.get('location', '')}\n"
                    f"岗位描述：{pos.get('description', '')}"
                )
        else:
            positions = self.kb.list_positions()
            if positions:
                pos = positions[0]
                position_info = (
                    f"岗位名称：{pos.get('name', '')}\n"
                    f"技能要求：{', '.join(pos.get('skills', []))}\n"
                    f"薪资范围：{pos.get('salary_range', '')}\n"
                    f"工作地点：{pos.get('location', '')}"
                )

        # 候选人背景（简历信息）
        resume_info = ""
        if session.resume_info:
            ri = session.resume_info
            resume_info = (
                f"候选人姓名：{ri.get('name', '')}\n"
                f"最近公司：{ri.get('latest_company', '')}\n"
                f"最近职位：{ri.get('latest_title', '')}\n"
                f"工作年限：{ri.get('years_of_experience', '')}\n"
                f"技能：{', '.join(ri.get('skills', []))}\n"
                f"期望薪资：{ri.get('expected_salary', '')}"
            )

        # 历史聊天上下文（最近 6 条）
        history = session.messages[-6:] if session.messages else []
        history_text = "\n".join(
            f"{'候选人' if m.sender == 'candidate' else 'HR'}: {m.text}"
            for m in history
        )

        # 知识库话术匹配
        pattern_hint = ""
        matched = self.kb.match_chat_pattern(msg.text)
        if matched:
            pattern_hint = (
                f"\n[知识库匹配话术场景: {matched.get('scenario', '')}]\n"
                f"推荐回复参考: {matched.get('selected_response', '')}"
            )

        # 面试详情（如果有）
        interview_info = ""
        if session.interview_details:
            d = session.interview_details
            interview_info = (
                f"已确认的面试安排：\n"
                f"  日期：{d.date}\n"
                f"  时间：{d.time}\n"
                f"  地点/方式：{d.address or d.method}"
            )

        prompt = f"""你是一位专业的HR招聘助手，正在与候选人进行聊天。

## 当前聊天状态
{state_hint}

## 岗位信息
{position_info}

## 候选人背景
{resume_info}

## 当前已确认的面试安排（如有）
{interview_info}

## 历史聊天上下文（最近消息）
{history_text}

## 候选人最新消息
{msg.text}
{pattern_hint}

## 你的任务
根据以上信息，生成一条自然的HR回复消息。要求：
1. 专业、友善、亲切，不要过于生硬
2. 结合岗位需求和候选人背景，突出双方匹配点
3. 符合当前聊天阶段的推进目标
4. 简短有力，一般不超过 100 字
5. 只输出回复内容，不要额外解释

HR回复："""

        try:
            reply = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm.generate(
                    prompt=prompt,
                    system_prompt=self.llm_system_prompt,
                )
            )
            session.llm_reply_count += 1
            return reply
        except Exception as e:
            print(f"[ChatEngine] LLM 生成回复失败: {e}")
            # fallback 到知识库模板
            return self._fallback_reply(session)

    async def _generate_reject_reply(
        self, session: CandidateSession, reject_kw: str
    ) -> str:
        """生成礼貌的拒绝回复"""
        prompt = f"""候选人说了「{reject_kw}」，表示不想继续面试流程。
请生成一条简短的、礼貌的结束语，感谢候选人的时间，并表示如有需要可以再联系。
要求：不超过 50 字，语气友好，不要给压力。

回复："""

        try:
            reply = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.llm.generate(prompt=prompt, system_prompt=self.llm_system_prompt)
            )
            return reply
        except Exception:
            # 完全 fallback
            return "好的，感谢您的时间，祝您早日找到合适的岗位！有需要随时联系~"

    def _fallback_reply(self, session: CandidateSession) -> str:
        """知识库模板兜底回复（无 LLM 时）"""
        state = session.state
        if state == ChatState.GREETING:
            return "您好！我是 HR，看到您的简历很感兴趣，方便聊聊吗？"
        elif state == ChatState.INTEREST_CONFIRM:
            return "很高兴您对这个岗位有兴趣！请问您方便安排一次面试吗？"
        elif state == ChatState.INTERVIEW_INTENT:
            return "好的，我们约个时间面试吧！请问您方便什么时间呢？"
        elif state == ChatState.TIME_PLACE_CONFIRM:
            return "好的，我来确认一下面试安排，稍后给您发确认信息~"
        else:
            return "好的，感谢您的回复，我这边记录一下~"

    # ========================================================================
    # 内部：发送消息
    # ========================================================================

    async def _send_reply(self, session: CandidateSession, text: str) -> bool:
        """
        将回复文本写入 Boss 直聘聊天输入框并点击发送。

        Returns:
            True 表示发送成功，False 表示失败
        """
        if not text:
            return False

        try:
            # 记录我们发送的消息
            boss_msg = ChatMessage(
                sender="boss",
                text=text,
                timestamp=datetime.now().isoformat(),
            )
            session.messages.append(boss_msg)

            # 定位输入框
            input_box = (
                self.page.locator("textarea").first
                .or_(self.page.locator('div[contenteditable="true"]').first)
                .or_(self.page.locator('[role="textbox"]').first)
            )

            await input_box.click()
            await asyncio.sleep(0.5)

            # 清空并填写（避免追加）
            await input_box.fill("")
            await input_box.fill(text)

            # 点击发送按钮
            send_btn = self.page.get_by_role("button", name=re.compile(r"发送"))
            await send_btn.click()
            await asyncio.sleep(2)  # 等待消息发送

            print(f"[ChatEngine] [{session.candidate_name}] 已发送: {text[:50]}...")
            return True

        except Exception as e:
            print(f"[ChatEngine] 发送消息失败: {e}")
            return False

    # ========================================================================
    # 工具方法
    # ========================================================================

    def _generate_candidate_id(self, name: str, index: int) -> str:
        """生成稳定的候选人 ID"""
        # 使用 name + index 组合，相同 name 不一定相同人，需要加上时间戳前缀
        ts = int(time.time())
        return f"{name or 'unknown'}_{index}_{ts}"

    def get_sessions_summary(self) -> list[dict]:
        """获取所有会话摘要（供外部监控）"""
        return [
            {
                "candidate_id": s.candidate_id,
                "candidate_name": s.candidate_name,
                "state": s.state.value,
                "message_count": len(s.messages),
                "llm_reply_count": s.llm_reply_count,
                "updated_at": s.updated_at,
                "interview_details": s.interview_details.to_dict() if s.interview_details else None,
            }
            for s in self._sessions.values()
        ]


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="OpenHR 智能聊天跟进引擎")
    parser.add_argument("--poll-interval", type=int, default=30,
                        help="轮询间隔（秒），默认 30")
    parser.add_argument("--chat-url", type=str,
                        default="https://www.zhipin.com/web/boss/chat",
                        help="聊天页 URL")
    parser.add_argument("--llm-config", type=str,
                        default=str(PROJECT_ROOT / "config" / "llm.json"),
                        help="LLM 配置文件路径")
    parser.add_argument("--log-dir", type=str,
                        default=str(CHAT_LOGS_DIR),
                        help="聊天日志目录")
    args = parser.parse_args()

    # 加载 LLM 配置
    llm_config_path = Path(args.llm_config)
    if llm_config_path.exists():
        with open(llm_config_path, "r", encoding="utf-8") as f:
            llm_config = json.load(f)
        print(f"[ChatEngine] LLM 配置已加载: {llm_config.get('provider', '?')} / {llm_config.get('model', '?')}")
    else:
        print(f"[ChatEngine] ⚠️ LLM 配置文件不存在: {llm_config_path}，使用默认配置")
        llm_config = {
            "provider": "openrouter",
            "api_key_env": "OPENROUTER_API_KEY",
            "model": "anthropic/claude-3.5-sonnet",
            "system_prompt": "你是一位专业的HR招聘助手，擅长与候选人沟通，推动面试流程。",
        }

    # 导入所需模块
    try:
        from scripts.boss_login import load_cookies, _get_browser_context, check_login
        from scripts.knowledge_base import KnowledgeBase
    except ImportError as e:
        print(f"ERROR: 缺少依赖模块: {e}")
        print("请确保 scripts/ 目录下的模块存在且可用")
        sys.exit(1)

    # 初始化知识库
    kb = KnowledgeBase()
    print(f"[ChatEngine] 知识库已加载，岗位数量: {kb.get_statistics()['positions_count']}")

    # 启动 Playwright
    print(f"[ChatEngine] 启动浏览器...")
    pw, browser, context = await _get_browser_context()

    # 尝试加载 cookies
    cookies_loaded = load_cookies(context)
    if not cookies_loaded:
        print("[ChatEngine] ❌ 未检测到有效 cookies，请先运行 boss_login.py")
        await browser.close()
        await pw.stop()
        sys.exit(1)

    page = await context.new_page()
    await page.goto(args.chat_url, wait_until="domcontentloaded", timeout=20000)
    await asyncio.sleep(3)

    # 检查登录态
    is_logged_in = await check_login(page)
    if not is_logged_in:
        print("[ChatEngine] ❌ 登录态失效，请重新运行 boss_login.py")
        await browser.close()
        await pw.stop()
        sys.exit(1)

    print("[ChatEngine] ✅ 已登录，开始聊天监控...")

    # 创建引擎
    engine = ChatEngine(
        page=page,
        kb=kb,
        llm_config=llm_config,
        poll_interval=args.poll_interval,
        chat_log_dir=Path(args.log_dir),
    )

    # 捕获 Ctrl+C 优雅退出
    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\n[ChatEngine] 收到中断信号，正在停止...")
        await engine.stop()
    finally:
        # 保存所有会话
        for session in engine._sessions.values():
            try:
                path = session.save(Path(args.log_dir))
                print(f"[ChatEngine] 已保存会话: {path}")
            except Exception as e:
                print(f"[ChatEngine] 保存会话异常: {e}")

        await context.close()
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    # 添加项目根目录到 sys.path，方便导入 scripts 模块
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    asyncio.run(main())
