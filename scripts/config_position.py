#!/usr/bin/env python3
"""
岗位配置 CLI — 交互式收集招聘需求并保存到 config/position.json

用法:
    python3 scripts/config_position.py --interactive   # 交互式向导
    python3 scripts/config_position.py --edit           # 编辑已有配置
    python3 scripts/config_position.py --show           # 显示当前配置
    python3 scripts/config_position.py --init           # 用默认值创建配置
"""

import argparse
import json
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
POSITION_FILE = CONFIG_DIR / "position.json"

# 默认配置
DEFAULT_CONFIG = {
    "title": "高级Python工程师",
    "salary_min": 20000,
    "salary_max": 40000,
    "education": ["本科", "硕士"],
    "experience_years": {"min": 3, "max": 8},
    "keywords": ["Python", "FastAPI", "PostgreSQL", "Redis"],
    "job_description": "负责后端核心服务开发，参与系统架构设计，优化系统性能与稳定性。",
    "company_brief": "我们是一家快速成长的科技公司，专注于AI与数据驱动的产品创新。",
    "highlights": [
        "技术栈先进，团队氛围好",
        "弹性工作制，远程友好",
        "有竞争力的薪资和期权",
    ],
    "greeting_extras": {
        "company_advantage": "AI驱动，技术导向",
        "position_highlight": "核心业务线，直接参与产品决策",
    },
}


def load_config() -> dict:
    """加载已有配置，不存在则返回空字典"""
    if POSITION_FILE.exists():
        with open(POSITION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_config(config: dict) -> None:
    """保存配置到文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(POSITION_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"✅ 配置已保存到 {POSITION_FILE}")


def show_config(config: dict) -> None:
    """美观地展示当前配置"""
    if not config:
        print("⚠️  还没有岗位配置。运行 --interactive 或 --init 来创建。")
        return

    print("=" * 50)
    print("📋 当前岗位配置")
    print("=" * 50)
    print(f"  职位名称:   {config.get('title', '-')}")
    print(f"  薪资范围:   {config.get('salary_min', '?'):,} - {config.get('salary_max', '?'):,} 元/月")
    exp = config.get("experience_years", {})
    print(f"  工作年限:   {exp.get('min', '?')}-{exp.get('max', '?')} 年")
    print(f"  学历要求:   {', '.join(config.get('education', []))}")
    print(f"  关键词:     {', '.join(config.get('keywords', []))}")
    print(f"  岗位描述:   {config.get('job_description', '-')[:60]}...")
    print(f"  公司简介:   {config.get('company_brief', '-')[:60]}...")
    highlights = config.get("highlights", [])
    if highlights:
        print("  岗位亮点:")
        for h in highlights:
            print(f"    • {h}")
    extras = config.get("greeting_extras", {})
    if extras:
        print("  打招呼补充信息:")
        for k, v in extras.items():
            print(f"    {k}: {v}")
    print("=" * 50)


def _input_with_default(prompt: str, default: str = "") -> str:
    """带默认值的输入"""
    if default:
        result = input(f"{prompt} [{default}]: ").strip()
        return result if result else default
    return input(f"{prompt}: ").strip()


def _input_int(prompt: str, default: int = 0) -> int:
    """整数输入"""
    while True:
        raw = _input_with_default(prompt, str(default))
        try:
            return int(raw)
        except ValueError:
            print("  ⚠️ 请输入数字")


def _input_list(prompt: str, default: list = None) -> list:
    """逗号分隔的列表输入"""
    default_str = ", ".join(default) if default else ""
    raw = _input_with_default(prompt, default_str)
    if not raw:
        return default or []
    return [item.strip() for item in raw.split(",") if item.strip()]


def interactive_config(existing: dict = None) -> dict:
    """
    交互式配置向导

    Args:
        existing: 已有配置（用于提供默认值）

    Returns:
        新配置字典
    """
    existing = existing or {}
    print()
    print("🔧 OpenHR 岗位配置向导")
    print("-" * 40)
    print("提示：直接回车使用 [默认值]，输入内容覆盖")
    print()

    config = {}

    # 基本信息
    config["title"] = _input_with_default(
        "📌 职位名称",
        existing.get("title", "Python工程师"),
    )

    print()
    print("💰 薪资范围（元/月）")
    config["salary_min"] = _input_int(
        "  最低薪资",
        existing.get("salary_min", 15000),
    )
    config["salary_max"] = _input_int(
        "  最高薪资",
        existing.get("salary_max", 30000),
    )

    print()
    print("🎓 学历要求（逗号分隔，如：本科,硕士,博士）")
    config["education"] = _input_list(
        "  学历列表",
        existing.get("education", ["本科", "硕士"]),
    )

    print()
    print("📅 工作年限")
    exp = existing.get("experience_years", {"min": 1, "max": 5})
    exp_min = _input_int("  最低年限", exp.get("min", 1))
    exp_max = _input_int("  最高年限", exp.get("max", 5))
    config["experience_years"] = {"min": exp_min, "max": exp_max}

    print()
    print("🔑 技能关键词（逗号分隔，用于匹配候选人和个性化打招呼）")
    config["keywords"] = _input_list(
        "  关键词",
        existing.get("keywords", ["Python"]),
    )

    print()
    config["job_description"] = _input_with_default(
        "📝 岗位描述（一句话概括）",
        existing.get("job_description", ""),
    )

    config["company_brief"] = _input_with_default(
        "🏢 公司简介（一句话）",
        existing.get("company_brief", ""),
    )

    print()
    print("✨ 岗位亮点（逗号分隔，用于打招呼模板）")
    config["highlights"] = _input_list(
        "  亮点列表",
        existing.get("highlights", []),
    )

    print()
    print("💬 打招呼补充信息（用于个性化模板）")
    extras = existing.get("greeting_extras", {})
    config["greeting_extras"] = {
        "company_advantage": _input_with_default(
            "  公司优势",
            extras.get("company_advantage", ""),
        ),
        "position_highlight": _input_with_default(
            "  岗位亮点",
            extras.get("position_highlight", ""),
        ),
    }

    print()
    return config


def cmd_show(args):
    """显示当前配置"""
    config = load_config()
    show_config(config)


def cmd_interactive(args):
    """交互式创建配置"""
    existing = load_config()
    if existing:
        print("📄 发现已有配置，将作为默认值。直接回车保留原值。")
    config = interactive_config(existing)
    save_config(config)
    print()
    show_config(config)


def cmd_edit(args):
    """编辑已有配置"""
    existing = load_config()
    if not existing:
        print("⚠️  还没有配置，将创建新配置。")
    config = interactive_config(existing)
    save_config(config)
    print()
    show_config(config)


def cmd_init(args):
    """用默认值初始化配置"""
    if POSITION_FILE.exists():
        print(f"⚠️  配置文件已存在: {POSITION_FILE}")
        confirm = input("覆盖？(y/N): ").strip().lower()
        if confirm != "y":
            print("取消。")
            return
    save_config(DEFAULT_CONFIG)
    show_config(DEFAULT_CONFIG)


def main():
    parser = argparse.ArgumentParser(
        description="OpenHR 岗位配置 CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python3 scripts/config_position.py --interactive   # 交互式向导
  python3 scripts/config_position.py --edit           # 编辑已有配置
  python3 scripts/config_position.py --show           # 查看当前配置
  python3 scripts/config_position.py --init           # 用默认值创建
        """,
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--interactive", action="store_true", help="交互式配置向导")
    group.add_argument("--edit", action="store_true", help="编辑已有配置")
    group.add_argument("--show", action="store_true", help="显示当前配置")
    group.add_argument("--init", action="store_true", help="用默认值初始化配置")

    args = parser.parse_args()

    if args.show:
        cmd_show(args)
    elif args.interactive:
        cmd_interactive(args)
    elif args.edit:
        cmd_edit(args)
    elif args.init:
        cmd_init(args)


if __name__ == "__main__":
    main()
