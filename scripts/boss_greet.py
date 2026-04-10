# -*- coding: utf-8 -*-
"""
Boss直聘主动打招呼模块 (M2)
============================
职责：
  - 自动遍历 Boss 直聘候选人推荐列表
  - 按岗位需求筛选合适候选人
  - 发送个性化打招呼消息（基于知识库模板 + 候选人信息）
  - 每日打招呼次数限制（默认100次/天）
  - 操作间隔随机化（防风控）

依赖：
  - scripts.boss_login   : get_logged_in_page() 获取已登录 Page
  - scripts.anti_detect  : AntiDetect 随机间隔/验证码检测/封号预警
  - scripts.knowledge_base: KnowledgeBase 岗位匹配/打招呼话术

用法：
  python scripts/boss_greet.py                          # 标准运行
  python scripts/boss_greet.py --dry-run                # 干跑测试
  python scripts/boss_greet.py --max-greets 50         # 指定上限
  python scripts/boss_greet.py --position-id pos_1     # 指定岗位
  python scripts/boss_greet.py --filter-skills Python,Django  # 技能筛选
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# ---- 项目路径设置 ----------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

# ---- 第三方依赖 -------------------------------------------------------
try:
    from playwright.async_api import async_playwright, Page, BrowserContext
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# ---- 内部模块 -------------------------------------------------------
from scripts.boss_login import (
    load_cookies,
    save_cookies,
    check_login,
    generate_qr_code,
    LOGIN_URL,
    HOME_URL,
    _get_browser_context,
)
from scripts.anti_detect import AntiDetect
from scripts.knowledge_base import KnowledgeBase, interpolate

# ============================================================================
# 常量配置
# ============================================================================

# 候选人推荐列表页 URL（招聘者入口）
RECOMMEND_URL = "https://www.zhipin.com/web/boss/recommend"

# 打招呼计数文件
GREET_COUNT_FILE = PROJECT_ROOT / "data" / "greet_count.json"

# 每日打招呼上限（默认100次，Boss直聘限制）
DEFAULT_DAILY_LIMIT = 100

# 滚动批次上限（防止无限滚动）
MAX_SCROLL_BATCHES = 10

# 每批次候选人数量（预估，每批加载约20个）
CANDIDATES_PER_BATCH = 20

# 调试输出目录
DEBUG_DIR = PROJECT_ROOT / "data" / "debug"


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class CandidateInfo:
    """候选人结构化信息"""
    uid: str                    # 唯一标识（Boss用户ID）
    name: str                   # 姓名
    position: str               # 当前/期望职位
    skills: list[str] = field(default_factory=list)   # 技能标签列表
    experience_years: str = ""  # 工作年限，如 "3年"
    education: str = ""         # 学历，如 "本科"
    city: str = ""              # 所在城市
    salary: str = ""            # 期望薪资
    last_company: str = ""      # 最近公司
    raw_text: str = ""         # 原始卡片文本（用于调试）
    card_element = None         # Playwright 卡片元素引用（不在结构里序列化）


@dataclass
class GreetResult:
    """打招呼任务结果"""
    total_candidates: int = 0       # 遍历到的候选人总数
    matched: int = 0                 # 匹配成功数
    greeted: int = 0                # 实际打招呼数
    skipped: int = 0                # 跳过数（不符合条件）
    captchas_detected: int = 0      # 检测到验证码次数
    reached_limit: bool = False     # 是否达到每日上限
    daily_count: int = 0            # 当日累计打招呼数
    duration_seconds: float = 0.0   # 总耗时（秒）
    errors: list[str] = field(default_factory=list)   # 错误列表


@dataclass
class GreetFilters:
    """筛选条件"""
    education: Optional[str] = None      # 学历要求，如 "本科"
    experience: Optional[str] = None     # 工作经验要求，如 "3-5年"
    skills: Optional[list[str]] = None   # 必备技能列表
    exclude_keywords: Optional[list[str]] = None  # 排除关键词


# ============================================================================
# 工具函数
# ============================================================================

def _ensure_debug_dir() -> Path:
    """确保调试目录存在"""
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    return DEBUG_DIR


def _load_greet_count() -> dict:
    """
    加载当日打招呼计数

    Returns:
        {"date": "2026-04-07", "count": 42, "greeted_ids": ["uid_xxx"]}
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not GREET_COUNT_FILE.exists():
        return {"date": today, "count": 0, "greeted_ids": []}

    try:
        with open(GREET_COUNT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 跨天后自动重置
        if data.get("date") != today:
            return {"date": today, "count": 0, "greeted_ids": []}
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[boss_greet] 加载计数文件失败: {e}，重置为0")
        return {"date": today, "count": 0, "greeted_ids": []}


def _save_greet_count(data: dict) -> None:
    """保存当日打招呼计数"""
    GREET_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(GREET_COUNT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _save_debug_screenshot(page: Page, label: str) -> str:
    """保存调试截图"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = DEBUG_DIR / f"debug_{label}_{ts}.png"
    _ensure_debug_dir()
    asyncio.create_task(page.screenshot(path=str(path), full_page=False))
    print(f"[boss_greet] 调试截图已保存: {path}")
    return str(path)


def load_filters(config_path: str | None = None) -> dict:
    """从 config/filters.json 加载筛选配置"""
    if config_path is None:
        config_path = str(PROJECT_ROOT / "config" / "filters.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            filters = json.load(f)
        print(f"[boss_greet] 已加载筛选配置: {filters}")
        return filters
    except (json.JSONDecodeError, IOError) as e:
        print(f"[boss_greet] 加载筛选配置失败: {e}，使用空配置（不过滤）")
        return {}


def filter_candidates(candidates: list, filters: dict) -> list:
    """
    按配置篪选候选人

    支持字段:
      - education: 学历列表，如 ["本科", "硕士"]
      - experience_years: {"min": 1, "max": 10}
      - salary_range: {"min": 5000, "max": 30000}
      - filter_mode: "all" (AND) 或 "any" (OR)

    Args:
        candidates: 候选人列表
        filters: 筛选配置字典

    Returns:
        过滤后的候选人列表
    """
    if not filters:
        return candidates

    filter_mode = filters.get("filter_mode", "all")
    filtered = []

    for c in candidates:
        reasons_passed = []
        reasons_failed = []

        # 学历筛选
        if "education" in filters and filters["education"]:
            edu = c.get("education", "")
            if edu in filters["education"]:
                reasons_passed.append("education")
            else:
                reasons_failed.append(f"education({edu} not in {filters['education']})")

        # 工作年限筛选
        if "experience_years" in filters:
            exp_range = filters["experience_years"]
            exp_str = c.get("experience_years", "0")
            # 从字符串提取数字，如 "3年" -> 3
            import re
            m = re.search(r'(\d+)', exp_str)
            exp = int(m.group(1)) if m else 0
            exp_min = exp_range.get("min", 0)
            exp_max = exp_range.get("max", 999)
            if exp_min <= exp <= exp_max:
                reasons_passed.append("experience_years")
            else:
                reasons_failed.append(f"experience_years({exp} not in [{exp_min},{exp_max}])")

        # 薪资筛选
        if "salary_range" in filters:
            sal_range = filters["salary_range"]
            sal_str = c.get("salary", "0")
            # 提取数字，如 "20-30K" -> 20000 (取中值)
            m = re.search(r'(\d+)[\-–](\d+)', sal_str)
            if m:
                sal_min = int(m.group(1)) * 1000
                sal_max = int(m.group(2)) * 1000
            else:
                m2 = re.search(r'(\d+)', sal_str)
                sal_min = sal_max = int(m2.group(1)) * 1000 if m2 else 0
            sal_min_cfg = sal_range.get("min", 0)
            sal_max_cfg = sal_range.get("max", 999999)
            if sal_min_cfg <= sal_min and sal_max <= sal_max_cfg:
                reasons_passed.append("salary")
            else:
                reasons_failed.append(f"salary({sal_str} not in range)")

        # 根据 filter_mode 决定去留
        if filter_mode == "all":
            if not reasons_failed:
                filtered.append(c)
            else:
                if reasons_failed:
                    print(f"[filter] 候选人 {c.get('name','?')} 未通过: {reasons_failed}")
        else:  # any mode
            if reasons_passed:
                filtered.append(c)

    print(f"[filter] 筛选完成: {len(candidates)} -> {len(filtered)} (mode={filter_mode})")
    return filtered


async def _css_or_xpath_fallback(page: Page, css_selector: str, xpath_selector: str, timeout: int = 5000):
    """
    尝试 CSS 选择器，失败后降级到 XPath

    Args:
        page: Playwright Page
        css_selector: CSS 选择器
        xpath_selector: XPath 选择器（当 CSS 失败时使用）
        timeout: 超时时间（毫秒）

    Returns:
        Playwright Locator 或 None
    """
    try:
        locator = page.locator(css_selector)
        elem = locator.first
        if await elem.is_visible(timeout=timeout):
            return elem
    except Exception:
        pass
    # CSS 失败，尝试 XPath
    try:
        xpath_locator = page.locator(f"xpath={xpath_selector}")
        elem = xpath_locator.first
        if await elem.is_visible(timeout=timeout):
            print(f"[boss_greet] CSS 选择器失败，降级到 XPath: {xpath_selector}")
            return elem
    except Exception:
        pass
    return None


def _parse_experience_years(text: str) -> str:
    """从文本中提取工作年限"""
    patterns = [
        r"(\d+)\s*[-~]\s*(\d+)\s*年",
        r"(\d+)\s*年+\s*经验",
        r"经验\s*(\d+)\s*年",
        r"(\d+)\s*年$",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return f"{m.group(1)}-{m.group(2)}年" if m.lastindex >= 2 else f"{m.group(1)}年"
    # 特殊值
    if "不限" in text or "应届" in text:
        return "不限"
    if "10年" in text or "10年以上" in text:
        return "10年以上"
    return ""


def _parse_education(text: str) -> str:
    """从文本中提取学历"""
    levels = ["博士", "硕士", "本科", "大专", "高中", "中专", "中技"]
    for lvl in levels:
        if lvl in text:
            return lvl
    return ""


async def _extract_candidate_from_card(card_locator, page: Page) -> Optional[CandidateInfo]:
    """
    从候选人卡片元素中解析出结构化信息

    Args:
        card_locator: Playwright 卡片元素定位器
        page: Playwright Page 对象

    Returns:
        CandidateInfo 对象，解析失败返回 None
    """
    try:
        # 获取卡片完整文本
        raw_text = (await card_locator.inner_text()).strip()

        # ---- 提取姓名 ----
        # 优先用语义标签，其次正则
        name = ""
        try:
            name_elem = card_locator.locator("h3, h4, [class*='name'], strong").first
            name = (await name_elem.inner_text()).strip()
            name = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9]", "", name)
        except Exception:
            pass
        if not name:
            m = re.search(r"^([\u4e00-\u9fa5]{2,4})", raw_text)
            name = m.group(1) if m else "未知"

        # ---- 提取职位 ----
        position = ""
        try:
            pos_elem = card_locator.locator("[class*='position'], [class*='job'], [class*='title']").first
            position = (await pos_elem.inner_text()).strip()
        except Exception:
            pass
        if not position:
            m = re.search(r"[\u4e00-\u9fa5]+[\u4e00-\u9fa5a-zA-Z0-9]*开发", raw_text)
            position = m.group(0) if m else ""

        # ---- 提取技能标签 ----
        skills = []
        try:
            tag_elems = card_locator.locator("[class*='tag'], [class*='label'], span").all()
            for elem in tag_elems:
                text = (await elem.inner_text() or "").strip()
                if text and len(text) < 20 and not any(
                    k in text for k in ["查看", "更多", "收起", "跳过"]
                ):
                    skills.append(text)
        except Exception:
            pass

        # ---- 提取学历 ----
        education = _parse_education(raw_text)

        # ---- 提取工作年限 ----
        experience = _parse_experience_years(raw_text)

        # ---- 提取UID ----
        uid = ""
        try:
            href = await card_locator.locator("a[href*='resume'], a[href*='geek'], a[href*='candidate']").first.get_attribute("href")
            if href:
                m = re.search(r"(\d+)", href)
                uid = m.group(0) if m else ""
        except Exception:
            pass
        if not uid:
            # 兜底：用姓名+前100字符做 MD5 哈希（跨进程稳定，12位确保一致性）
            uid = hashlib.md5((name + raw_text[:100]).encode()).hexdigest()[:12]

        return CandidateInfo(
            uid=uid,
            name=name,
            position=position,
            skills=skills,
            experience_years=experience,
            education=education,
            raw_text=raw_text,
        )
    except Exception as e:
        print(f"[boss_greet] 解析候选人卡片失败: {e}")
        return None


def _match_candidate(
    candidate: CandidateInfo,
    kb: KnowledgeBase,
    position_id: Optional[str] = None,
    filters: Optional[GreetFilters] = None,
) -> tuple[bool, str, dict]:
    """
    判断候选人是否匹配岗位需求

    Args:
        candidate: 候选人信息
        kb: 知识库实例
        position_id: 指定岗位ID，不指定则用知识库所有岗位
        filters: 额外筛选条件

    Returns:
        (是否匹配, 匹配描述, 匹配到的岗位信息)
    """
    # ---- 技能匹配（从知识库） ----
    cand_info = {
        "skills": candidate.skills,
        "experience_years": candidate.experience_years,
        "education": candidate.education,
        "position": candidate.position,
    }
    matches = kb.match_candidate_to_position(cand_info)

    # 按 position_id 过滤
    if position_id:
        matches = [m for m in matches if m.get("id") == position_id]

    if not matches:
        return False, "知识库无匹配岗位", {}

    best_match = matches[0]
    match_score = best_match.get("match_score", 0)

    # ---- 硬性筛选：分数门槛 ----
    if match_score < 20:
        return False, f"匹配分数 {match_score} 过低(<20)", best_match

    # ---- 额外筛选条件 ----
    f = filters or GreetFilters()

    # 学历筛选
    if f.education and candidate.education:
        edu_order = ["博士", "硕士", "本科", "大专", "高中", "中专", "中技"]
        cand_edu_idx = next((i for i, e in enumerate(edu_order) if e in candidate.education), -1)
        required_edu_idx = next((i for i, e in enumerate(edu_order) if f.education in e), -1)
        if cand_edu_idx > required_edu_idx >= 0:
            return False, f"学历不满足({candidate.education} < {f.education})", best_match

    # 技能筛选
    if f.skills and candidate.skills:
        cand_skills_lower = [s.lower() for s in candidate.skills]
        required = [s.lower() for s in f.skills]
        matched = set(cand_skills_lower) & set(required)
        if not matched:
            return False, f"必备技能未命中({f.skills})", best_match

    # 排除关键词
    if f.exclude_keywords:
        text = (candidate.position + " " + " ".join(candidate.skills)).lower()
        for kw in f.exclude_keywords:
            if kw.lower() in text:
                return False, f"命中排除词: {kw}", best_match

    return True, f"匹配岗位 {best_match.get('name')} (分数:{match_score})", best_match


def _load_position_config() -> dict:
    """加载 config/position.json 岗位配置（如果存在）"""
    pos_file = PROJECT_ROOT / "config" / "position.json"
    if pos_file.exists():
        try:
            with open(pos_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _select_greeting_template(
    candidate: CandidateInfo,
    matched_position: dict,
    template_config: list,
) -> str:
    """
    从配置中选择一条最合适的打招呼模板，并进行变量填充

    R3 优化：支持 {keyword}, {exp_years}, {position_title},
    {salary_range}, {company_advantage}, {position_highlight} 等新变量。

    Args:
        candidate: 候选人信息
        matched_position: 匹配到的岗位信息
        template_config: 模板配置列表

    Returns:
        填充后的打招呼消息文本
    """
    # 加载岗位配置（用于个性化变量）
    pos_cfg = _load_position_config()
    greeting_extras = pos_cfg.get("greeting_extras", {})

    # 按优先级排序，筛选启用模板
    enabled = sorted(
        [t for t in template_config if t.get("enabled", True)],
        key=lambda x: x.get("priority", 0),
        reverse=True,
    )
    if not enabled:
        # 兜底：最简单的话术
        return f"您好 {candidate.name}，我们正在招聘 {candidate.position}，有兴趣聊聊吗？"

    # 策略：根据候选人特征选择模板风格
    # 经验丰富的候选人 → 精英/经验型
    # 年轻候选人 → 成长/亲和型
    # 默认 → 从 top-3 随机
    exp_str = candidate.experience_years or ""
    try:
        exp_num = int(re.search(r"(\d+)", exp_str).group(1)) if exp_str else 0
    except (AttributeError, ValueError):
        exp_num = 0

    # 找最佳匹配关键词（从候选人技能中匹配岗位关键词）
    pos_keywords = [k.lower() for k in pos_cfg.get("keywords", [])]
    best_keyword = ""
    for skill in (candidate.skills or []):
        if skill.lower() in pos_keywords:
            best_keyword = skill
            break
    if not best_keyword and candidate.skills:
        best_keyword = candidate.skills[0]
    elif not best_keyword and pos_cfg.get("keywords"):
        best_keyword = pos_cfg["keywords"][0]

    # 构建薪资范围文本
    s_min = pos_cfg.get("salary_min")
    s_max = pos_cfg.get("salary_max")
    if s_min and s_max:
        salary_range = f"{s_min // 1000}K-{s_max // 1000}K"
    else:
        salary_range = matched_position.get("salary_range", "")

    # 根据经验年限选择模板
    chosen_template = None
    if exp_num >= 5:
        # 资深：优先选精英猎头型或经验亮点型
        for t in enabled:
            tags = " ".join(t.get("tags", []))
            if "精英" in tags or "经验" in tags or "深度" in tags:
                chosen_template = t
                break
    elif exp_num <= 2:
        # 年轻：优先选成长吸引型或轻松亲和型
        for t in enabled:
            tags = " ".join(t.get("tags", []))
            if "成长" in tags or "亲和" in tags or "轻松" in tags:
                chosen_template = t
                break

    if not chosen_template:
        # 默认策略：从高优先级 top-3 随机选
        top_templates = enabled[:3]
        chosen_template = random.choice(top_templates)

    text = chosen_template.get("text", "")

    # 构建变量字典（R3 扩展）
    position_title = (
        pos_cfg.get("title")
        or matched_position.get("name", candidate.position)
        or candidate.position
    )
    variables = {
        # 基础变量（向后兼容）
        "name": candidate.name,
        "position": position_title,
        "skill": ", ".join(candidate.skills[:2]) if candidate.skills else best_keyword,
        "company": pos_cfg.get("company_brief", "我们公司"),
        "salary": salary_range,
        "education": candidate.education,
        "experience": candidate.experience_years,
        # R3 新增变量
        "keyword": best_keyword,
        "exp_years": exp_str,
        "position_title": position_title,
        "salary_range": salary_range,
        "company_advantage": greeting_extras.get("company_advantage", ""),
        "position_highlight": greeting_extras.get("position_highlight", ""),
    }

    return interpolate(text, variables)


# ============================================================================
# 主执行器
# ============================================================================

class BossGreetRunner:
    """
    Boss 直聘主动打招呼任务执行器

    Attributes:
        max_daily_greets: 每日打招呼上限
        position_id: 指定岗位ID（不指定则用知识库所有岗位）
        filters: 筛选条件
        dry_run: 是否干跑（不实际打招呼）
        templates: 打招呼模板配置列表
    """

    def __init__(
        self,
        max_daily_greets: int = DEFAULT_DAILY_LIMIT,
        position_id: Optional[str] = None,
        filters: Optional[GreetFilters] = None,
        dry_run: bool = False,
        templates_path: Optional[str] = None,
        config_dir: Optional[str] = None,
    ):
        self.max_daily_greets = max_daily_greets
        self.position_id = position_id
        self.filters = filters or GreetFilters()
        self.dry_run = dry_run

        # 加载模板配置
        if config_dir is None:
            config_dir = PROJECT_ROOT / "config"
        templates_path = templates_path or str(config_dir / "templates.json")
        self.templates = self._load_templates(templates_path)

        # 加载知识库
        kb_dir = PROJECT_ROOT / "data" / "knowledge"
        self.kb = KnowledgeBase(kb_dir)

        # 加载风控模块
        anti_cfg_path = PROJECT_ROOT / "config" / "anti_detect.json"
        self.ad = AntiDetect(anti_cfg_path if anti_cfg_path.exists() else None)

        # 加载候选人筛选配置（filters.json）
        filters_config_path = str(PROJECT_ROOT / "config" / "filters.json")
        self._filters_config = load_filters(filters_config_path)

        # 结果
        self.result = GreetResult()
        self._start_time: float = 0

    def _load_templates(self, path: str) -> list:
        """加载打招呼模板配置"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            templates = data.get("templates", [])
            print(f"[boss_greet] 已加载 {len(templates)} 个打招呼模板")
            return templates
        except (json.JSONDecodeError, IOError) as e:
            print(f"[boss_greet] 加载模板失败: {e}，使用内置默认模板")
            return [
                {
                    "id": "default",
                    "text": "您好 {name}，我是 HR，看到您的简历和我们招聘的 {position} 岗位很匹配，方便聊聊吗？",
                    "enabled": True,
                    "priority": 1,
                }
            ]

    async def _ensure_logged_in_page(self) -> Page:
        """
        确保获得一个已登录的 Playwright Page

        Returns:
            已登录的 Page 对象

        Raises:
            RuntimeError: 无法获得登录态时抛出
        """
        print("[boss_greet] 初始化浏览器...")
        pw, browser, context = await _get_browser_context()
        page = await context.new_page()

        # 应用风控 stealth
        await self.ad.apply_stealth(page)

        # 尝试加载已有 cookies
        cookies_loaded = load_cookies(context)
        if cookies_loaded:
            print("[boss_greet] 已加载 cookies，验证登录态...")
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)

        is_logged_in = await check_login(page)

        if not is_logged_in:
            print("[boss_greet] 未登录，开始扫码登录流程...")
            qr_path = await generate_qr_code()
            print(f"[boss_greet] 请扫码登录: {qr_path}")

            # 轮询等待扫码
            login_timeout = 600
            start = time.time()
            while time.time() - start < login_timeout:
                await asyncio.sleep(5)
                try:
                    if await check_login(page):
                        print("[boss_greet] ✅ 扫码登录成功！")
                        break
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"[boss_greet] 检测异常: {e}")
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
            else:
                raise RuntimeError("扫码登录超时（10分钟）")

        # 保存 cookies（下次可直接用）
        save_cookies(context)

        # 将 browser/context 保存到 runner（用于最后关闭）
        self._pw = pw
        self._browser = browser
        self._context = context

        return page

    async def _get_greet_button(self, page: Page):
        """
        获取打招呼按钮定位器（CSS 优先，XPath 降级）

        Playwright 推荐策略（按优先级）：
          1. 按钮文本包含"打招呼"/"立即沟通"/"立即开聊"
          2. a 标签包含上述文本
        """
        css = (
            'a.op-btn-chat, button:has-text("打招呼"), '
            'a:has-text("立即沟通"), a:has-text("立即开聊")'
        )
        xpath = (
            "//a[contains(@class, 'op-btn-chat') or contains(text(), '打招呼') or contains(text(), '立即沟通') or contains(text(), '立即开聊')] | "
            "//button[contains(text(), '打招呼')]"
        )
        result = await _css_or_xpath_fallback(page, css, xpath, timeout=5000)
        if result:
            return result
        # 兜底：直接用 CSS
        return page.locator(css).first

    async def _send_greet(
        self,
        page: Page,
        candidate: CandidateInfo,
        message: str,
    ) -> bool:
        """
        向单个候选人发送打招呼消息

        Args:
            page: Playwright Page
            candidate: 候选人信息
            message: 填充后的打招呼消息

        Returns:
            是否发送成功
        """
        try:
            # 找到并点击"打招呼"按钮
            greet_btn = await self._get_greet_button(page)
            await greet_btn.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)

            # 使用鼠标模拟点击（降低被检测风险）
            box = await greet_btn.bounding_box()
            if box:
                await self.ad.simulate_mouse(page, int(box["x"] + box["width"] / 2), int(box["y"] + box["height"] / 2))
            else:
                await greet_btn.click()

            await asyncio.sleep(2)  # 等待弹窗出现

            # ---- 查找并填写打招呼输入框 ----
            input_box = (
                page.locator("textarea")
                .or_(page.locator('div[contenteditable="true"]'))
                .or_(page.locator('[role="textbox"]'))
            )
            try:
                input_elem = input_box.first
                await input_elem.wait_for(timeout=5000)
                await input_elem.fill(message)
            except Exception as e:
                print(f"[boss_greet] 未找到打招呼输入框: {e}")
                # 尝试 ESC 关闭弹窗
                await page.keyboard.press("Escape")
                return False

            await asyncio.sleep(1)

            # ---- 点击发送按钮 ----
            send_btn = page.get_by_role("button", name=re.compile(r"发\s*送|确认|发送"))
            try:
                await send_btn.first.click(timeout=5000)
            except Exception:
                # 兜底：尝试按回车发送
                await page.keyboard.press("Enter")

            print(f"[boss_greet] ✅ 已发送: {candidate.name} -> {message[:30]}...")
            return True

        except Exception as e:
            print(f"[boss_greet] 发送打招呼失败: {candidate.name}, 错误: {e}")
            self.result.errors.append(f"发送失败 {candidate.name}: {e}")
            # 保存失败截图
            try:
                _save_debug_screenshot(page, f"greet_fail_{candidate.uid}")
            except Exception:
                pass
            return False

    async def _scroll_and_load_candidates(self, page: Page) -> list:
        """
        滚动页面，加载新候选人，返回当前屏所有候选人卡片元素

        Returns:
            候选人卡片元素列表
        """
        # 记录滚动前高度
        prev_height = await page.evaluate("document.body.scrollHeight")

        # 模拟人类滚动行为
        await self.ad.simulate_scroll(page)

        # 等待新内容加载
        await asyncio.sleep(2)

        # 检查是否有"正在加载中"提示
        try:
            loading_elem = page.locator("text=正在加载, text=加载中").first
            if await loading_elem.is_visible(timeout=3000):
                await loading_elem.wait_for(state="hidden", timeout=10000)
        except Exception:
            pass

        # 获取当前屏所有候选人卡片
        # CSS 选择器列表（优先级从高到低）
        card_selectors = [
            # 精确匹配 Boss 直聘已知结构
            "div.job-card-wrapper",
            "div.card-inner-wrapper",
            "ul.recommend-list > li",
            "div.candidate-card",
            "div.job-list-box > div",
            "div[class*='job-card']",
            # 通配链接类（兜底）
            "a[href*='resume']",
            "a[href*='geek']",
            "a[href*='candidate']",
        ]

        cards = []
        for sel in card_selectors:
            try:
                elems = page.locator(sel).all()
                count = len(elems)
                if count > 0:
                    print(f"[boss_greet] 卡片选择器命中: {sel}, 数量: {count}")
                    cards = elems
                    break
            except Exception:
                pass

        # 如果 CSS 全失败，尝试 XPath 降级
        if not cards:
            xpath_selectors = [
                "//div[contains(@class, 'job-card')]",
                "//li[contains(@class, 'recommend')]",
                "//a[contains(@href, 'resume') or contains(@href, 'geek')]",
            ]
            for xpath in xpath_selectors:
                try:
                    elems = page.locator(f"xpath={xpath}").all()
                    count = len(elems)
                    if count > 0:
                        print(f"[boss_greet] XPath 降级成功: {xpath}, 数量: {count}")
                        cards = elems
                        break
                except Exception:
                    pass

        return cards

    async def run(self) -> GreetResult:
        """
        执行主动打招呼任务

        Returns:
            GreetResult 任务结果
        """
        self._start_time = time.time()
        print("\n" + "=" * 50)
        print("  Boss直聘主动打招呼任务开始")
        print("=" * 50 + "\n")

        # ---- 加载当日计数 ----
        greet_data = _load_greet_count()
        self.result.daily_count = greet_data["count"]
        greeted_ids = set(greet_data.get("greeted_ids", []))

        print(f"[boss_greet] 当日已打招呼: {self.result.daily_count} / {self.max_daily_greets}")

        if self.result.daily_count >= self.max_daily_greets:
            print("[boss_greet] ⚠️ 已达到每日上限，任务退出")
            self.result.reached_limit = True
            return self.result

        try:
            # ---- 获取已登录 Page ----
            page = await self._ensure_logged_in_page()

            # ---- 导航到候选人推荐页 ----
            print(f"[boss_greet] 导航到: {RECOMMEND_URL}")
            await page.goto(RECOMMEND_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            # 验证码检测
            if await self.ad.detect_captcha(page):
                print("[boss_greet] 🚨 检测到验证码，任务暂停！")
                _save_debug_screenshot(page, "captcha_detected")
                self.result.captchas_detected += 1
                self.result.errors.append("检测到验证码，需要人工处理")
                return self.result

            # ---- 主循环：滚动 → 加载 → 筛选 → 打招呼 ----
            for batch in range(1, MAX_SCROLL_BATCHES + 1):
                # 检查每日上限
                if self.result.daily_count >= self.max_daily_greets:
                    print(f"[boss_greet] ⚠️ 达到每日上限 {self.max_daily_greets}，停止")
                    self.result.reached_limit = True
                    break

                print(f"\n[boss_greet] 滚动批次 {batch}/{MAX_SCROLL_BATCHES}...")

                # 滚动并获取当前屏候选人卡片
                cards = await self._scroll_and_load_candidates(page)
                print(f"[boss_greet] 当前屏找到 {len(cards)} 个候选人链接/卡片")

                if len(cards) == 0:
                    print("[boss_greet] 无更多候选人，结束")
                    break

                # ---- 遍历每个候选人 ----
                for i, card in enumerate(cards):
                    # 检查每日上限
                    if self.result.daily_count >= self.max_daily_greets:
                        self.result.reached_limit = True
                        break

                    try:
                        # 解析候选人信息
                        candidate = await _extract_candidate_from_card(card, page)
                        if not candidate:
                            self.result.skipped += 1
                            continue

                        # ---- 按 config/filters.json 筛选 ----
                        if self._filters_config:
                            cand_dict = {
                                "name": candidate.name,
                                "education": candidate.education,
                                "experience_years": candidate.experience_years,
                                "salary": candidate.salary,
                            }
                            if not filter_candidates([cand_dict], self._filters_config):
                                print(f"[boss_greet] ⏭ 筛选未通过: {candidate.name}")
                                self.result.skipped += 1
                                continue

                        self.result.total_candidates += 1

                        # ---- 去重检查 ----
                        if candidate.uid in greeted_ids:
                            print(f"[boss_greet] ⏭ 跳过（已打过招呼）: {candidate.name}")
                            self.result.skipped += 1
                            continue

                        # ---- 岗位匹配筛选 ----
                        is_match, reason, matched_pos = _match_candidate(
                            candidate, self.kb, self.position_id, self.filters
                        )
                        print(f"[boss_greet] 候选人: {candidate.name} | {reason}")

                        if not is_match:
                            self.result.skipped += 1
                            continue

                        self.result.matched += 1

                        # ---- 生成个性化消息 ----
                        message = _select_greeting_template(candidate, matched_pos, self.templates)
                        print(f"[boss_greet] 消息: {message[:50]}...")

                        # ---- 干跑模式 ----
                        if self.dry_run:
                            print(f"[boss_greet] 🟡 干跑模式，跳过实际发送")
                            self.result.greeted += 1
                        else:
                            # ---- 实际发送打招呼 ----
                            success = await self._send_greet(page, candidate, message)
                            if success:
                                self.result.greeted += 1
                                greeted_ids.add(candidate.uid)
                                # 更新计数文件
                                self.result.daily_count += 1
                                greet_data["count"] = self.result.daily_count
                                greet_data["greeted_ids"] = list(greeted_ids)
                                _save_greet_count(greet_data)

                        # ---- 风控：随机停顿 ----
                        if not self.dry_run:
                            delay = await self.ad.random_delay()

                        # ---- 验证码检测（每次操作后） ----
                        if await self.ad.detect_captcha(page):
                            print("[boss_greet] 🚨 检测到验证码，任务暂停！")
                            _save_debug_screenshot(page, "captcha_during_greet")
                            self.result.captchas_detected += 1
                            self.result.errors.append("操作中检测到验证码")
                            return self.result

                        # ---- 预警检测 ----
                        state = await self.ad.check_warning(page)
                        if state == "paused":
                            print("[boss_greet] ⏸️ 风控预警，进入暂停状态")
                            self.result.errors.append("风控预警自动暂停")
                            return self.result

                    except Exception as e:
                        print(f"[boss_greet] 处理候选人时出错: {e}")
                        self.result.errors.append(f"处理出错: {e}")
                        try:
                            _save_debug_screenshot(page, f"error_batch{batch}_idx{i}")
                        except Exception:
                            pass
                        continue

                # 每批次结束，验证码检测
                if await self.ad.detect_captcha(page):
                    _save_debug_screenshot(page, f"captcha_after_batch{batch}")
                    self.result.captchas_detected += 1
                    break

        except Exception as e:
            print(f"[boss_greet] 任务异常: {e}")
            self.result.errors.append(f"任务异常: {e}")
            try:
                if "page" in dir():
                    _save_debug_screenshot(page, "task_error")
            except Exception:
                pass

        finally:
            # ---- 清理资源 ----
            try:
                await self._context.close()
                await self._browser.close()
                await self._pw.stop()
            except Exception:
                pass

        # ---- 打印最终报告 ----
        self.result.duration_seconds = time.time() - self._start_time
        self._print_report()

        return self.result

    def _print_report(self):
        """打印任务完成报告"""
        r = self.result
        print("\n" + "=" * 50)
        print("  打招呼任务完成报告")
        print("=" * 50)
        print(f"  总耗时:          {r.duration_seconds:.1f}s")
        print(f"  遍历候选人数:    {r.total_candidates}")
        print(f"  匹配成功数:      {r.matched}")
        print(f"  实际打招呼数:    {r.greeted}")
        print(f"  跳过数:          {r.skipped}")
        print(f"  当日累计:        {r.daily_count}/{self.max_daily_greets}")
        print(f"  验证码检测:      {r.captchas_detected}")
        print(f"  达到上限:        {'是 ⚠️' if r.reached_limit else '否'}")
        if r.errors:
            print(f"  错误列表:")
            for err in r.errors:
                print(f"    - {err}")
        print("=" * 50 + "\n")


# ============================================================================
# CLI 入口
# ============================================================================

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Boss直聘主动打招呼模块 (M2)")
    parser.add_argument(
        "--max-greets",
        type=int,
        default=DEFAULT_DAILY_LIMIT,
        help=f"每日打招呼上限（默认{DEFAULT_DAILY_LIMIT}）",
    )
    parser.add_argument(
        "--position-id",
        type=str,
        default=None,
        help="指定岗位ID（不指定则用知识库所有岗位匹配）",
    )
    parser.add_argument(
        "--filter-education",
        type=str,
        default=None,
        help="学历筛选，如 '本科'",
    )
    parser.add_argument(
        "--filter-experience",
        type=str,
        default=None,
        help="工作经验筛选，如 '3-5年'",
    )
    parser.add_argument(
        "--filter-skills",
        type=str,
        default=None,
        help="必备技能筛选，逗号分隔，如 'Python,Django'",
    )
    parser.add_argument(
        "--filter-exclude",
        type=str,
        default=None,
        help="排除关键词，逗号分隔",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="干跑模式（不实际发送消息，仅测试流程）",
    )
    parser.add_argument(
        "--templates",
        type=str,
        default=None,
        help="自定义模板配置文件路径",
    )

    args = parser.parse_args()

    # 构建筛选条件
    filters = GreetFilters(
        education=args.filter_education,
        experience=args.filter_experience,
        skills=args.filter_skills.split(",") if args.filter_skills else None,
        exclude_keywords=args.filter_exclude.split(",") if args.filter_exclude else None,
    )

    runner = BossGreetRunner(
        max_daily_greets=args.max_greets,
        position_id=args.position_id,
        filters=filters,
        dry_run=args.dry_run,
        templates_path=args.templates,
    )

    result = await runner.run()

    # 退出码：有问题返回1
    if result.errors or result.captchas_detected > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
