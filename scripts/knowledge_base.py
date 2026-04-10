# -*- coding: utf-8 -*-
"""
知识库管理模块 (Knowledge Base)
OpenHR 自动化招聘智能体专用

管理话术库、岗位需求库、反馈模板，支持从历史聊天记录中提取话术模式。
数据以 JSON 格式存储在 data/knowledge/ 目录下。
"""

import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ============================================================================
# 数据结构定义
# ============================================================================

@dataclass
class GreetingTemplate:
    """打招呼模板"""
    id: str                    # 模板唯一标识
    text: str                   # 模板文本，支持变量插值 {name}, {position}
    tags: list[str] = field(default_factory=list)   # 标签，如 ["热情", "简洁", "针对新人"]
    priority: int = 0           # 优先级，数值越大越优先
    enabled: bool = True       # 是否启用


@dataclass
class ChatPattern:
    """聊天话术模式"""
    id: str                    # 模式唯一标识
    scenario: str              # 场景，如 "主动回复", "拒绝回应", "约面试"
    conditions: list[str] = field(default_factory=list)   # 触发条件关键词
    patterns: list[str] = field(default_factory=list)     # 回复模板列表
    follow_up: str = ""        # 后续动作提示


@dataclass
class PositionRequirement:
    """岗位需求"""
    id: str                    # 岗位唯一标识
    name: str                  # 岗位名称，如 "Python后端开发"
    department: str = ""       # 部门
    skills: list[str] = field(default_factory=list)   # 技能要求
    experience_years: str = "" # 经验要求，如 "3-5年", "不限"
    education: str = ""        # 学历要求，如 "本科及以上"
    salary_range: str = ""     # 薪资范围，如 "25k-40k"
    location: str = ""         # 工作地点
    description: str = ""      # 岗位描述
    keywords: list[str] = field(default_factory=list)    # 筛选关键词
    exclude_keywords: list[str] = field(default_factory=list)  # 排除关键词


@dataclass
class FeedbackTemplate:
    """反馈模板"""
    id: str                    # 模板唯一标识
    type: str                  # 模板类型: "interview_confirm", "interview_reject", "follow_up"
    title: str                 # 模板标题
    text: str                  # 模板文本，支持变量插值
    enabled: bool = True


# ============================================================================
# 工具函数
# ============================================================================

def interpolate(text: str, variables: dict[str, Any]) -> str:
    """
    模板变量插值

    Args:
        text: 模板文本，可能包含 {name}, {position} 等占位符
        variables: 变量字典

    Returns:
        插值后的文本

    Example:
        interpolate("您好 {name}，我是 {company} 的 HR", {"name": "张三", "company": "XX科技"})
        -> "您好 张三，我是 XX科技 的 HR"
    """
    result = text
    for key, value in variables.items():
        result = result.replace(f"{{{key}}}", str(value))
    return result


def extract_variables(text: str) -> list[str]:
    """
    从文本中提取所有变量占位符

    Args:
        text: 模板文本

    Returns:
        变量名列表，如 ["name", "position", "company"]
    """
    return re.findall(r"\{(\w+)\}", text)


# ============================================================================
# 知识库主类
# ============================================================================

class KnowledgeBase:
    """
    OpenHR 知识库管理器

    线程安全，支持多模块并发读取。
    数据存储在 data/knowledge/ 目录下的 JSON 文件中。

    Attributes:
        base_dir: 知识库数据目录路径
        greetings: 打招呼话术列表
        chat_patterns: 聊天话术模式列表
        positions: 岗位需求列表
        feedback_templates: 反馈模板列表
    """

    # 默认知识库目录
    DEFAULT_KB_DIR = Path(__file__).parent.parent / "data" / "knowledge"

    def __init__(self, kb_dir: str | Path | None = None):
        """
        初始化知识库

        Args:
            kb_dir: 知识库数据目录，默认使用项目目录下的 data/knowledge/
        """
        if kb_dir is None:
            self.base_dir = self.DEFAULT_KB_DIR
        else:
            self.base_dir = Path(kb_dir)

        # 确保目录存在
        self.base_dir.mkdir(parents=True, exist_ok=True)

        # 文件路径
        self._greetings_path = self.base_dir / "greetings.json"
        self._chat_patterns_path = self.base_dir / "chat_patterns.json"
        self._positions_path = self.base_dir / "position_requirements.json"
        self._feedback_path = self.base_dir / "feedback_templates.json"

        # 线程锁
        self._lock = threading.RLock()

        # 数据容器
        self.greetings: list[dict] = []
        self.chat_patterns: list[dict] = []
        self.positions: list[dict] = []
        self.feedback_templates: list[dict] = []

        # 加载所有数据
        self._load_all()

    # ========================================================================
    # 加载与保存
    # ========================================================================

    def _load_all(self) -> None:
        """加载所有知识库数据（线程安全）"""
        with self._lock:
            self.greetings = self._load_json(self._greetings_path, [])
            self.chat_patterns = self._load_json(self._chat_patterns_path, [])
            self.positions = self._load_json(self._positions_path, [])
            self.feedback_templates = self._load_json(self._feedback_path, [])

    def _load_json(self, path: Path, default: Any) -> Any:
        """
        加载单个 JSON 文件

        Args:
            path: 文件路径
            default: 文件不存在时的默认值

        Returns:
            解析后的数据
        """
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[KnowledgeBase] 加载文件失败 {path}: {e}")
            return default

    def _save_json(self, path: Path, data: Any) -> bool:
        """
        保存数据到 JSON 文件

        Args:
            path: 文件路径
            data: 要保存的数据

        Returns:
            是否保存成功
        """
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except IOError as e:
            print(f"[KnowledgeBase] 保存文件失败 {path}: {e}")
            return False

    def load(self) -> None:
        """重新加载所有知识库数据（公开接口）"""
        self._load_all()

    def save(self) -> dict[str, bool]:
        """
        保存所有知识库数据到磁盘

        Returns:
            各文件的保存结果字典
        """
        with self._lock:
            results = {
                "greetings": self._save_json(self._greetings_path, self.greetings),
                "chat_patterns": self._save_json(self._chat_patterns_path, self.chat_patterns),
                "positions": self._save_json(self._positions_path, self.positions),
                "feedback_templates": self._save_json(self._feedback_path, self.feedback_templates),
            }
            return results

    # ========================================================================
    # 打招呼话术库操作
    # ========================================================================

    def get_greeting(self, position: str = "", name: str = "") -> str:
        """
        获取一条打招呼话术，自动进行变量插值

        Args:
            position: 岗位名称，用于填充 {position} 变量
            name: 候选人姓名，用于填充 {name} 变量

        Returns:
            插值后的打招呼话术，如果没有可用话术返回空字符串
        """
        with self._lock:
            enabled = [g for g in self.greetings if g.get("enabled", True)]
            if not enabled:
                return ""
            # 简单策略：随机选一条，再做变量插值
            import random
            template = random.choice(enabled)
            text = template.get("text", "")
            return interpolate(text, {"position": position, "name": name})

    def add_greeting(self, text: str, tags: list[str] | None = None,
                    priority: int = 0, enabled: bool = True) -> dict:
        """
        添加一条打招呼话术

        Args:
            text: 话术文本，支持 {name}, {position} 等变量
            tags: 标签列表
            priority: 优先级
            enabled: 是否启用

        Returns:
            添加的话术对象（包含生成的 id）
        """
        with self._lock:
            # 提取变量
            variables = extract_variables(text)
            greeting = {
                "id": f"greet_{len(self.greetings) + 1}_{hash(text) % 10000}",
                "text": text,
                "tags": tags or [],
                "priority": priority,
                "enabled": enabled,
                "variables": variables,
            }
            self.greetings.append(greeting)
            return greeting

    def update_greeting(self, greeting_id: str, updates: dict) -> bool:
        """
        更新一条打招呼话术

        Args:
            greeting_id: 话术 ID
            updates: 要更新的字段

        Returns:
            是否更新成功
        """
        with self._lock:
            for i, g in enumerate(self.greetings):
                if g.get("id") == greeting_id:
                    self.greetings[i].update(updates)
                    # 如果文本更新了，重新提取变量
                    if "text" in updates:
                        self.greetings[i]["variables"] = extract_variables(updates["text"])
                    return True
            return False

    def delete_greeting(self, greeting_id: str) -> bool:
        """
        删除一条打招呼话术

        Args:
            greeting_id: 话术 ID

        Returns:
            是否删除成功
        """
        with self._lock:
            for i, g in enumerate(self.greetings):
                if g.get("id") == greeting_id:
                    self.greetings.pop(i)
                    return True
            return False

    def list_greetings(self) -> list[dict]:
        """返回所有打招呼话术的副本"""
        with self._lock:
            return list(self.greetings)

    # ========================================================================
    # 聊天话术模式操作
    # ========================================================================

    def match_chat_pattern(self, message: str) -> dict | None:
        """
        根据消息内容匹配聊天话术模式

        Args:
            message: 候选人的消息内容

        Returns:
            匹配到的模式对象，如果没有匹配返回 None
        """
        with self._lock:
            message_lower = message.lower()
            for pattern in self.chat_patterns:
                conditions = pattern.get("conditions", [])
                # 只要消息包含任意一个条件关键词就匹配
                if any(cond.lower() in message_lower for cond in conditions):
                    # 随机返回其中一个模板
                    import random
                    templates = pattern.get("patterns", [])
                    if templates:
                        return {
                            **pattern,
                            "selected_response": random.choice(templates)
                        }
            return None

    def add_chat_pattern(self, scenario: str, conditions: list[str],
                        patterns: list[str], follow_up: str = "") -> dict:
        """
        添加一条聊天话术模式

        Args:
            scenario: 场景名称
            conditions: 触发条件关键词列表
            patterns: 回复模板列表
            follow_up: 后续动作提示

        Returns:
            添加的模式对象
        """
        with self._lock:
            pattern = {
                "id": f"chat_{len(self.chat_patterns) + 1}_{hash(scenario) % 10000}",
                "scenario": scenario,
                "conditions": conditions,
                "patterns": patterns,
                "follow_up": follow_up,
            }
            self.chat_patterns.append(pattern)
            return pattern

    def delete_chat_pattern(self, pattern_id: str) -> bool:
        """删除一条聊天话术模式"""
        with self._lock:
            for i, p in enumerate(self.chat_patterns):
                if p.get("id") == pattern_id:
                    self.chat_patterns.pop(i)
                    return True
            return False

    def list_chat_patterns(self) -> list[dict]:
        """返回所有聊天话术模式的副本"""
        with self._lock:
            return list(self.chat_patterns)

    # ========================================================================
    # 岗位需求库操作
    # ========================================================================

    def get_position(self, position_id: str) -> dict | None:
        """
        根据 ID 获取岗位需求

        Args:
            position_id: 岗位 ID

        Returns:
            岗位需求对象，如果不存在返回 None
        """
        with self._lock:
            for pos in self.positions:
                if pos.get("id") == position_id:
                    return dict(pos)
            return None

    def get_position_by_name(self, name: str) -> dict | None:
        """
        根据名称模糊匹配岗位

        Args:
            name: 岗位名称（模糊匹配）

        Returns:
            匹配到的第一个岗位需求对象
        """
        with self._lock:
            name_lower = name.lower()
            for pos in self.positions:
                if name_lower in pos.get("name", "").lower():
                    return dict(pos)
            return None

    def add_position(self, name: str, department: str = "",
                    skills: list[str] | None = None,
                    experience_years: str = "", education: str = "",
                    salary_range: str = "", location: str = "",
                    description: str = "",
                    keywords: list[str] | None = None,
                    exclude_keywords: list[str] | None = None) -> dict:
        """
        添加一个岗位需求

        Args:
            name: 岗位名称
            department: 部门
            skills: 技能要求列表
            experience_years: 经验要求
            education: 学历要求
            salary_range: 薪资范围
            location: 工作地点
            description: 岗位描述
            keywords: 筛选关键词
            exclude_keywords: 排除关键词

        Returns:
            添加的岗位需求对象
        """
        with self._lock:
            position = {
                "id": f"pos_{len(self.positions) + 1}_{hash(name) % 10000}",
                "name": name,
                "department": department,
                "skills": skills or [],
                "experience_years": experience_years,
                "education": education,
                "salary_range": salary_range,
                "location": location,
                "description": description,
                "keywords": keywords or [],
                "exclude_keywords": exclude_keywords or [],
            }
            self.positions.append(position)
            return position

    def update_position(self, position_id: str, updates: dict) -> bool:
        """更新一个岗位需求"""
        with self._lock:
            for i, p in enumerate(self.positions):
                if p.get("id") == position_id:
                    self.positions[i].update(updates)
                    return True
            return False

    def delete_position(self, position_id: str) -> bool:
        """删除一个岗位需求"""
        with self._lock:
            for i, p in enumerate(self.positions):
                if p.get("id") == position_id:
                    self.positions.pop(i)
                    return True
            return False

    def match_candidate_to_position(self, candidate_info: dict) -> list[dict]:
        """
        将候选人信息与岗位需求匹配，返回匹配的岗位列表

        Args:
            candidate_info: 候选人信息字典，包含以下可选字段:
                - skills: 技能列表
                - experience_years: 工作年限（字符串或数字）
                - education: 学历
                - position: 期望职位
                - salary: 期望薪资

        Returns:
            按匹配度排序的岗位列表（包含匹配分数）
        """
        with self._lock:
            matches = []
            for pos in self.positions:
                score = 0
                reasons = []

                # 技能匹配
                pos_skills = [s.lower() for s in pos.get("skills", [])]
                cand_skills = [s.lower() for s in candidate_info.get("skills", [])]
                matched_skills = set(pos_skills) & set(cand_skills)
                if matched_skills:
                    skill_score = len(matched_skills) / max(len(pos_skills), 1) * 40
                    score += skill_score
                    reasons.append(f"技能匹配: {', '.join(matched_skills)}")

                # 关键词匹配
                pos_keywords = [k.lower() for k in pos.get("keywords", [])]
                cand_text = " ".join([
                    str(candidate_info.get("position", "")),
                    str(candidate_info.get("skills", "")),
                    " ".join(candidate_info.get("skills", []))
                ]).lower()
                matched_kw = [k for k in pos_keywords if k in cand_text]
                if matched_kw:
                    score += len(matched_kw) * 10
                    reasons.append(f"关键词匹配: {', '.join(matched_kw)}")

                # 排除词检测
                exclude = [k.lower() for k in pos.get("exclude_keywords", [])]
                if any(k in cand_text for k in exclude):
                    score = 0
                    reasons = ["命中排除关键词"]

                if score > 0:
                    matches.append({
                        **pos,
                        "match_score": round(score, 1),
                        "match_reasons": reasons
                    })

            # 按匹配度排序
            matches.sort(key=lambda x: x["match_score"], reverse=True)
            return matches

    def list_positions(self) -> list[dict]:
        """返回所有岗位需求的副本"""
        with self._lock:
            return list(self.positions)

    # ========================================================================
    # 反馈模板操作
    # ========================================================================

    def get_feedback_template(self, template_type: str, variables: dict | None = None) -> dict | None:
        """
        获取指定类型的反馈模板，并进行变量插值

        Args:
            template_type: 模板类型，如 "interview_confirm", "interview_reject", "follow_up"
            variables: 变量字典，用于填充模板中的占位符

        Returns:
            插值后的模板对象，如果不存在返回 None
        """
        with self._lock:
            for tpl in self.feedback_templates:
                if tpl.get("type") == template_type and tpl.get("enabled", True):
                    result = dict(tpl)
                    result["text"] = interpolate(tpl.get("text", ""), variables or {})
                    return result
            return None

    def add_feedback_template(self, template_type: str, title: str, text: str,
                              enabled: bool = True) -> dict:
        """
        添加一条反馈模板

        Args:
            template_type: 模板类型
            title: 模板标题
            text: 模板文本
            enabled: 是否启用

        Returns:
            添加的模板对象
        """
        with self._lock:
            template = {
                "id": f"feedback_{len(self.feedback_templates) + 1}_{hash(text) % 10000}",
                "type": template_type,
                "title": title,
                "text": text,
                "enabled": enabled,
                "variables": extract_variables(text),
            }
            self.feedback_templates.append(template)
            return template

    def update_feedback_template(self, template_id: str, updates: dict) -> bool:
        """更新一条反馈模板"""
        with self._lock:
            for i, t in enumerate(self.feedback_templates):
                if t.get("id") == template_id:
                    self.feedback_templates[i].update(updates)
                    if "text" in updates:
                        self.feedback_templates[i]["variables"] = extract_variables(updates["text"])
                    return True
            return False

    def delete_feedback_template(self, template_id: str) -> bool:
        """删除一条反馈模板"""
        with self._lock:
            for i, t in enumerate(self.feedback_templates):
                if t.get("id") == template_id:
                    self.feedback_templates.pop(i)
                    return True
            return False

    def list_feedback_templates(self) -> list[dict]:
        """返回所有反馈模板的副本"""
        with self._lock:
            return list(self.feedback_templates)

    # ========================================================================
    # 历史聊天记录分析
    # ========================================================================

    def learn_from_chat_history(self, chat_history: list[dict]) -> dict:
        """
        从历史聊天记录中提取话术模式并学习

        Args:
            chat_history: 聊天记录列表，每条记录包含:
                - role: "hr" 或 "candidate"
                - message: 消息内容
                - timestamp: 时间戳（可选）

        Returns:
            学习结果报告，包含新增的话术模式列表

        Example:
            chat_history = [
                {"role": "hr", "message": "您好，请问您对 Python 后端开发岗位感兴趣吗？"},
                {"role": "candidate", "message": "感兴趣，请问薪资范围是多少？"},
                {"role": "hr", "message": "月薪 20-30k，13 薪，五险一金全交。"},
            ]
            result = kb.learn_from_chat_history(chat_history)
        """
        with self._lock:
            report = {
                "greetings_added": [],
                "patterns_added": [],
                "total_processed": len(chat_history),
            }

            # 提取 HR 的有效话术（去重）
            hr_messages = [
                msg["message"] for msg in chat_history
                if msg.get("role") == "hr" and len(msg.get("message", "")) > 5
            ]

            # 检测打招呼话术（通常在前 3 条消息中）
            for msg_text in hr_messages[:3]:
                # 检查是否已存在
                if not any(g.get("text") == msg_text for g in self.greetings):
                    greeting = self.add_greeting(
                        text=msg_text,
                        tags=["从聊天记录学习"],
                        priority=0,
                        enabled=False  # 新学习的默认不启用，待人工审核
                    )
                    report["greetings_added"].append(greeting["id"])

            # 提取候选人的常见问题模式
            cand_messages = [
                msg["message"] for msg in chat_history
                if msg.get("role") == "candidate"
            ]

            # 常见问题关键词
            question_keywords = {
                "薪资": ["薪资", "工资", "薪酬", "待遇", "salary"],
                "地点": ["地址", "地点", "位置", "通勤", "location"],
                "经验": ["经验", "年限", "要求", "experience"],
                "技能": ["技能", "技术", "要求", "skill"],
                "面试": ["面试", "时间", "流程", "interview"],
            }

            for keyword, keywords_list in question_keywords.items():
                matching = [
                    msg for msg in cand_messages
                    if any(kw in msg for kw in keywords_list)
                ]
                if matching:
                    # 检查是否已存在该场景的模式
                    existing_scenarios = [p.get("scenario") for p in self.chat_patterns]
                    scenario_name = f"候选人询问{keyword}"
                    if scenario_name not in existing_scenarios:
                        # 收集 HR 对应的回复
                        idx = chat_history.index({"role": "candidate", "message": matching[0]})
                        hr_responses = []
                        for i in range(idx + 1, min(idx + 3, len(chat_history))):
                            if chat_history[i].get("role") == "hr":
                                hr_responses.append(chat_history[i]["message"])
                                break

                        if hr_responses:
                            pattern = self.add_chat_pattern(
                                scenario=scenario_name,
                                conditions=keywords_list,
                                patterns=hr_responses,
                                follow_up=""
                            )
                            report["patterns_added"].append(pattern["id"])

            return report

    # ========================================================================
    # 辅助方法
    # ========================================================================

    def get_statistics(self) -> dict:
        """
        获取知识库统计信息

        Returns:
            包含各模块数量的统计字典
        """
        with self._lock:
            return {
                "greetings_count": len(self.greetings),
                "chat_patterns_count": len(self.chat_patterns),
                "positions_count": len(self.positions),
                "feedback_templates_count": len(self.feedback_templates),
                "enabled_greetings_count": len([g for g in self.greetings if g.get("enabled", True)]),
                "data_directory": str(self.base_dir),
            }

    def export_all(self) -> dict:
        """
        导出所有知识库数据的副本（用于调试或备份）

        Returns:
            包含所有数据的字典
        """
        with self._lock:
            return {
                "greetings": list(self.greetings),
                "chat_patterns": list(self.chat_patterns),
                "positions": list(self.positions),
                "feedback_templates": list(self.feedback_templates),
                "metadata": {
                    "exported_at": str(Path(__file__).parent),
                    "statistics": self.get_statistics(),
                }
            }


# ============================================================================
# 便捷函数
# ============================================================================

# 全局单例实例（延迟初始化）
_global_kb: KnowledgeBase | None = None


def get_knowledge_base(kb_dir: str | Path | None = None) -> KnowledgeBase:
    """
    获取知识库全局单例实例

    Args:
        kb_dir: 可选的指定知识库目录

    Returns:
        KnowledgeBase 实例
    """
    global _global_kb
    if _global_kb is None:
        _global_kb = KnowledgeBase(kb_dir)
    return _global_kb


# ============================================================================
# 主程序入口（用于测试）
# ============================================================================

if __name__ == "__main__":
    print("[KnowledgeBase] 运行自检...")

    # 初始化知识库
    kb = KnowledgeBase()

    # 打印统计信息
    stats = kb.get_statistics()
    print(f"  统计: {stats}")

    # 测试打招呼话术
    greeting = kb.get_greeting(position="Python后端开发", name="张三")
    print(f"  打招呼示例: {greeting}")

    # 测试模板匹配
    pattern = kb.match_chat_pattern("请问薪资是多少？")
    if pattern:
        print(f"  匹配到的模式: {pattern.get('scenario')}")
        print(f"  推荐回复: {pattern.get('selected_response')}")

    # 测试反馈模板
    feedback = kb.get_feedback_template(
        "interview_confirm",
        {"name": "张三", "time": "周三 15:00", "address": "北京市朝阳区XX大厦"}
    )
    if feedback:
        print(f"  面试确认模板: {feedback.get('text', '')[:50]}...")

    # 测试候选人匹配
    matches = kb.match_candidate_to_position({
        "skills": ["Python", "Django", "PostgreSQL", "Redis"],
        "experience_years": "3年",
    })
    if matches:
        print(f"  最佳匹配岗位: {matches[0].get('name')} (分数: {matches[0].get('match_score')})")

    print("\n[KnowledgeBase] 自检完成 ✓")
