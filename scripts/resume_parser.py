# -*- coding: utf-8 -*-
"""
OpenHR 简历解析模块 (c4)
========================
从 Boss 直聘聊天窗口或简历详情页提取候选人结构化信息。

依赖:
    - playwright: pip install playwright && playwright install chromium
    - 参考: references/boss-api.md, scripts/anti_detect.py

用法:
    # 从当前页面（需已导航到简历或聊天页）提取
    python scripts/resume_parser.py --mode chat

    # 直接传入页面文本（供其他模块调用）
    python scripts/resume_parser.py --text "张三\n28岁\n本科\nPython开发工程师..."

    # 作为模块导入
    from scripts.resume_parser import extract_from_page, extract_from_text
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------

@dataclass
class CandidateInfo:
    """候选人结构化信息"""
    name: str = ""                      # 姓名
    age_gender: str = ""                # 年龄/性别，如 "28岁/男"
    education: str = ""                 # 学历，如 "本科"
    years_of_experience: str = ""      # 工作年限，如 "5年"
    city: str = ""                      # 当前城市
    expected_role: str = ""             # 期望岗位
    expected_salary: str = ""          # 期望薪资，如 "20-30K"
    latest_company: str = ""            # 最近公司
    latest_title: str = ""             # 最近岗位
    experience_summary: str = ""       # 工作经历摘要
    project_summary: str = ""          # 项目经历摘要
    education_summary: str = ""        # 教育经历摘要
    skills: list[str] = field(default_factory=list)   # 技能标签
    self_summary: str = ""              # 自我评价
    phone: str = ""                    # 手机号
    boss_url: str = ""                 # Boss 候选人链接
    source: str = "Boss直聘"           # 来源平台
    raw_text: str = ""                 # 原始文本（供调试/溯源）
    dedup_key: str = ""               # 去重 key（基于 phone / name+company+title）

    def to_dict(self) -> dict:
        d = asdict(self)
        # 去重 key 内部使用，不对外暴露
        return d

    def to_feishu_fields(self, field_mapping: dict) -> dict:
        """映射到飞书多维表格字段名"""
        result = {}
        mapping = {
            "name": "name",
            "age_gender": "age_gender",
            "education": "education",
            "experience": "experience_summary",
            "skills": "skills",
            "expected_salary": "expected_salary",
            "phone": "phone",
            "source": "source",
        }
        for feishu_col, our_field in mapping.items():
            if feishu_col in field_mapping:
                col_name = field_mapping[feishu_col]
                val = getattr(self, our_field, "")
                if our_field == "skills" and isinstance(val, list):
                    val = ", ".join(val)
                result[col_name] = val
        # 额外字段
        if "age_gender" in field_mapping:
            result[field_mapping["age_gender"]] = self.age_gender
        if "created_at" in field_mapping:
            from datetime import datetime
            result[field_mapping["created_at"]] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if "status" in field_mapping:
            result[field_mapping["status"]] = "新入库"
        return result


# ---------------------------------------------------------------------------
# 文本正则解析
# ---------------------------------------------------------------------------

class ResumeTextParser:
    """
    从原始简历文本中提取结构化字段。
    Boss 直聘简历格式有一定规律，但也常有变体，
    所以用正则 + 规则双重提取，取置信度最高的结果。
    """

    # 姓名：行首或"姓名"后面跟非空白字符
    PAT_NAME = re.compile(
        r'(?:姓名\s*[:：]\s*|^(.{2,4})(?:\s*[/,\|]|$))',
        re.MULTILINE
    )

    # 年龄/性别
    PAT_AGE_GENDER = re.compile(
        r'(\d{1,3})\s*[岁年]\s*[/\s]?\s*([男女])\b'
    )

    # 学历
    PAT_EDUCATION = re.compile(
        r'(?:学历|教育程度)\s*[:：]\s*([初中高中中专大专本科硕士博士及以上]+)'
    )
    # 常见学历前置
    EDU_KEYWORDS = ["博士", "硕士", "本科", "大专", "中专", "高中", "初中"]

    # 工作年限
    PAT_YEARS = re.compile(
        r'(\d{1,2})\s*年(?:工作经验?|工作年限)?'
    )

    # 期望薪资
    PAT_SALARY = re.compile(
        r'(?:期望薪资|期望工资|薪资期待)\s*[:：]?\s*'
        r'(\d{1,3}[\-–]?\d{0,3}K|\d{1,3}[\-–]?\d{0,3}k|\d{1,3}[\-–]?\d{0,3})'
    )
    # 更宽松的薪资匹配
    PAT_SALARY_LOOSE = re.compile(
        r'(\d{1,3})[\-–千kK](\d{1,3})[千kK]?'
    )

    # 手机号
    PAT_PHONE = re.compile(
        r'(?:手机|电话|联系[电话]?)\s*[:：]?\s*'
        r'(1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4})'
    )

    # 技能标签（方括号/标签样式 or 逗号分隔）
    PAT_SKILLS_BRACKET = re.compile(r'\[([^\]]+)\]')
    PAT_SKILLS_TAG = re.compile(r'(?:技能|特长|技术)\s*[:：]\s*([^\n]{2,100})')

    # 公司 + 岗位
    PAT_COMPANY_TITLE = re.compile(
        r'(?:公司|任职|职位|工作单位)\s*[:：]\s*([^\n，,]{2,30})'
        r'(?:[\n\s]+([^\n，,]{2,30}))?'
    )

    # 城市
    PAT_CITY = re.compile(
        r'(?:现居地|所在城市|所在地区|城市|位置)\s*[:：]\s*([^\n，,]{2,15})'
    )

    # 工作经历 section
    PAT_EXPERIENCE_HEADER = re.compile(
        r'(?:工作经历|职业经历|从业经历|经历)', re.IGNORECASE
    )
    # 教育经历 section
    PAT_EDUCATION_HEADER = re.compile(
        r'(?:教育经历|教育背景|学习经历)', re.IGNORECASE
    )
    # 项目经历 section
    PAT_PROJECT_HEADER = re.compile(
        r'(?:项目经历|项目经验)', re.IGNORECASE
    )
    # 自我评价 section
    PAT_SELF_HEADER = re.compile(
        r'(?:自我评价|个人优势|个人简介|关于我)', re.IGNORECASE
    )

    def __init__(self, text: str):
        self.text = text
        self.lines = text.split("\n")

    # ---- name ----
    def extract_name(self) -> str:
        # 优先：直接搜索"姓名："
        m = re.search(r'姓名\s*[:：]\s*(.{2,5})', self.text)
        if m:
            return m.group(1).strip()
        # 其次：找"姓名"字段
        m = re.search(r'"姓名"\s*:\s*"([^"]+)"', self.text)
        if m:
            return m.group(1).strip()
        # 再次：搜索常见姓名用字（2-4字，开头不能是职位关键词）
        for line in self.lines[:10]:
            line = line.strip()
            if len(line) >= 2 and len(line) <= 5:
                if not any(kw in line for kw in ["简历", "Boss", "期望", "岗位", "薪资", "职位", "公司"]):
                    if re.match(r'^[\u4e00-\u9fff·]+$', line):
                        return line
        return ""

    # ---- age / gender ----
    def extract_age_gender(self) -> str:
        m = self.PAT_AGE_GENDER.search(self.text)
        if m:
            return f"{m.group(1)}岁/{m.group(2)}"
        return ""

    # ---- education ----
    def extract_education(self) -> str:
        m = self.PAT_EDUCATION.search(self.text)
        if m:
            return m.group(1).strip()
        # 直接在文本中找最高学历关键词
        for kw in self.EDU_KEYWORDS:
            if kw in self.text:
                return kw
        return ""

    # ---- years of experience ----
    def extract_years(self) -> str:
        m = self.PAT_YEARS.search(self.text)
        if m:
            return f"{m.group(1)}年"
        return ""

    # ---- city ----
    def extract_city(self) -> str:
        m = self.PAT_CITY.search(self.text)
        if m:
            return m.group(1).strip()
        # 常见城市名匹配
        cities = ["北京", "上海", "广州", "深圳", "杭州", "南京", "苏州", "成都",
                  "武汉", "西安", "长沙", "重庆", "天津", "东莞", "佛山", "宁波", "青岛", "济南"]
        for line in self.lines[:15]:
            for city in cities:
                if city in line:
                    return city
        return ""

    # ---- expected salary ----
    def extract_salary(self) -> str:
        m = self.PAT_SALARY.search(self.text)
        if m:
            return m.group(0).strip()
        m = self.PAT_SALARY_LOOSE.search(self.text)
        if m:
            return f"{m.group(1)}-{m.group(2)}K"
        return ""

    # ---- phone ----
    def extract_phone(self) -> str:
        m = self.PAT_PHONE.search(self.text)
        if m:
            phone = re.sub(r'[\s\-]+', '', m.group(1))
            return phone
        # 纯手机号正则兜底
        m = re.search(r'\b(1[3-9]\d{9})\b', self.text)
        if m:
            return m.group(1)
        return ""

    # ---- skills ----
    def extract_skills(self) -> list[str]:
        skills = set()
        # [标签] 形式
        for m in self.PAT_SKILLS_BRACKET.finditer(self.text):
            tags = [t.strip() for t in m.group(1).split(",")
                    if t.strip() and len(t.strip()) <= 15]
            skills.update(tags)
        # "技能：" 形式
        m = self.PAT_SKILLS_TAG.search(self.text)
        if m:
            tags = [t.strip() for t in re.split(r'[,，、\s]+', m.group(1))
                    if t.strip() and len(t.strip()) <= 15]
            skills.update(tags)
        # 常见技术关键词（高频出现词频统计）
        tech_keywords = [
            "Python", "Java", "Go", "Rust", "C++", "C#", "JavaScript", "TypeScript",
            "React", "Vue", "Angular", "Node.js", "Django", "Flask", "FastAPI",
            "Spring", "Spring Boot", "MySQL", "PostgreSQL", "Redis", "MongoDB",
            "Docker", "Kubernetes", "K8s", "AWS", "GCP", "Azure", "Linux",
            "Git", "Nginx", "Kafka", "RabbitMQ", "GraphQL", "REST", "API",
            "机器学习", "深度学习", "TensorFlow", "PyTorch", "NLP",
            "Vue3", "前端", "后端", "全栈", "移动端", "Android", "iOS",
            "FastAPI", "Tornado", "Sanic", "爬虫", "数据挖掘", "大数据",
        ]
        text_lower = self.text
        for kw in tech_keywords:
            if kw.lower() in text_lower.lower():
                skills.add(kw)
        return list(skills)[:20]  # 最多20个

    # ---- latest company & title ----
    def extract_company_title(self) -> tuple[str, str]:
        # 找"最近公司"块
        m = re.search(
            r'(?:最近公司|当前公司|现公司|工作单位)\s*[:：]\s*([^\n，,]{2,30})',
            self.text
        )
        company = m.group(1).strip() if m else ""

        m = re.search(
            r'(?:职位|岗位|现任职位|最近职位|职位名称)\s*[:：]\s*([^\n，,]{2,30})',
            self.text
        )
        title = m.group(1).strip() if m else ""

        if not company or not title:
            # 尝试从"公司名称 + 职位"相邻行推断
            for i, line in enumerate(self.lines):
                if any(kw in line for kw in ["公司", "科技", "网络", "信息", "技术"]):
                    if i + 1 < len(self.lines):
                        next_line = self.lines[i + 1].strip()
                        if len(next_line) >= 2 and len(next_line) <= 20:
                            if not company and len(line.strip()) >= 2:
                                company = line.strip()
                            if not title and len(next_line) >= 2:
                                title = next_line
                    break

        return company, title

    # ---- section summaries ----
    def _extract_section(self, header_re: re.Pattern, max_lines: int = 30) -> str:
        lines = []
        capture = False
        for line in self.lines:
            if header_re.search(line):
                capture = True
                continue
            if capture:
                # 遇到另一个 section 标题停止
                if any(h.search(line) for h in
                       [self.PAT_EXPERIENCE_HEADER, self.PAT_EDUCATION_HEADER,
                        self.PAT_PROJECT_HEADER, self.PAT_SELF_HEADER]):
                    break
                if line.strip():
                    lines.append(line.strip())
                if len(lines) >= max_lines:
                    break
        return "\n".join(lines[:15])  # 最多15行

    def extract_experience_summary(self) -> str:
        return self._extract_section(self.PAT_EXPERIENCE_HEADER)

    def extract_education_summary(self) -> str:
        return self._extract_section(self.PAT_EDUCATION_HEADER)

    def extract_project_summary(self) -> str:
        return self._extract_section(self.PAT_PROJECT_HEADER)

    def extract_self_summary(self) -> str:
        return self._extract_section(self.PAT_SELF_HEADER)

    # ---- 全量解析 ----
    def parse(self) -> CandidateInfo:
        name = self.extract_name()
        phone = self.extract_phone()
        company, title = self.extract_company_title()

        info = CandidateInfo(
            name=name,
            age_gender=self.extract_age_gender(),
            education=self.extract_education(),
            years_of_experience=self.extract_years(),
            city=self.extract_city(),
            expected_role=self.extract_salary(),  # 期望薪资暂存这里，后面单独处理
            expected_salary=self.extract_salary(),
            latest_company=company,
            latest_title=title,
            experience_summary=self.extract_experience_summary(),
            education_summary=self.extract_education_summary(),
            project_summary=self.extract_project_summary(),
            self_summary=self.extract_self_summary(),
            skills=self.extract_skills(),
            phone=phone,
            raw_text=self.text,
        )

        # 生成去重 key
        info.dedup_key = build_dedup_key(
            name=info.name,
            phone=info.phone,
            latest_company=info.latest_company,
            latest_title=info.latest_title,
        )

        return info


# ---------------------------------------------------------------------------
# 去重 Key 构建
# ---------------------------------------------------------------------------

def build_dedup_key(
    name: str,
    phone: str | None = None,
    latest_company: str | None = None,
    latest_title: str | None = None,
) -> str:
    """生成唯一去重 key（SHA1）"""
    import hashlib
    raw = "|".join([
        phone or "",
        name or "",
        latest_company or "",
        latest_title or "",
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Playwright 页面提取
# ---------------------------------------------------------------------------

async def extract_from_page(page, source: str = "detail") -> CandidateInfo:
    """
    从 Playwright Page 对象提取简历信息。

    Args:
        page: Playwright Page（需已导航到简历页或聊天页）
        source: "detail" = 简历详情页, "chat" = 聊天窗口候选人卡片

    Returns:
        CandidateInfo 结构体
    """
    try:
        # 等待简历主区域出现
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
        await asyncio.sleep(2)  # 等 SPA 渲染

        # 根据来源选择根选择器
        if source == "detail":
            root_selectors = [
                "main", "article",
                "[class*='resume']", "[class*='detail']",
                "[class*='candidate']", "[class*='profile']",
            ]
        else:  # chat
            root_selectors = [
                "[class*='candidate']", "[class*='profile']",
                "[class*='resume']", "[class*='card']",
                "aside [class*='info']", "[class*='user-info']",
            ]

        text = ""
        for sel in root_selectors:
            try:
                elem = page.locator(sel).first
                if await elem.is_visible(timeout=5000):
                    text = await elem.inner_text()
                    if len(text) > 50:  # 内容太少说明选错了
                        break
            except Exception:
                pass

        if not text or len(text) < 50:
            # 兜底：拿整个 body
            body = page.locator("body")
            text = await body.inner_text()

        # 清洗文本（去掉多余空白）
        text = "\n".join(line.strip() for line in text.split("\n") if line.strip())

        parser = ResumeTextParser(text)
        return parser.parse()

    except Exception as e:
        print(f"[resume_parser] 页面提取失败: {e}")
        # 返回空结构，不崩溃
        return CandidateInfo(raw_text=f"ERROR: {e}")


# ---------------------------------------------------------------------------
# 文本直接解析（供其他模块调用）
# ---------------------------------------------------------------------------

def extract_from_text(text: str) -> CandidateInfo:
    """
    从原始文本直接解析候选人信息。

    Args:
        text: 简历纯文本（或含 HTML 的 inner_text）

    Returns:
        CandidateInfo 结构体
    """
    # 清洗
    text = "\n".join(line.strip() for line in text.split("\n") if line.strip())
    parser = ResumeTextParser(text)
    return parser.parse()


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="简历解析模块")
    parser.add_argument("--mode", choices=["detail", "chat"], default="detail",
                        help="页面来源：detail=简历详情页, chat=聊天窗口")
    parser.add_argument("--text", type=str, default="",
                        help="直接传入文本（跳过页面抓取）")
    parser.add_argument("--output", type=str, default="",
                        help="JSON 输出路径（默认打印到 stdout）")
    args = parser.parse_args()

    if args.text:
        # 文本模式
        info = extract_from_text(args.text)
    else:
        # 需要 Playwright 页面
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print("ERROR: playwright not installed")
            sys.exit(1)

        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            current = page.url
            if "resume" in current or "profile" in current or "candidate" in current:
                args.mode = "detail"
            else:
                args.mode = "chat"
            print(f"[resume_parser] 当前 URL: {current}，使用模式: {args.mode}")
            info = await extract_from_page(page, source=args.mode)
        finally:
            await browser.close()
            await pw.stop()

    # 输出
    output = json.dumps(info.to_dict(), ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
        print(f"[resume_parser] 结果已保存: {args.output}")
    else:
        print(output)

    return info


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print(__doc__)
    else:
        asyncio.run(main())
