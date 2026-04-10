# -*- coding: utf-8 -*-
"""
OpenHR 飞书多维表格上传模块 (c4)
===============================
将候选人简历信息写入飞书多维表格（Bitable）。

功能：
  - 飞书 OpenAPI 认证（tenant_access_token）
  - 多维表格记录创建 / 更新
  - 基于手机号 / 姓名+公司+岗位 的去重逻辑
  - 字段映射：CandidateInfo → 飞书字段名
  - 配置从 config/feishu.json 读取

依赖：
    pip install requests
    参考: references/feishu-bitable-api.md

用法：
    # 命令行
    python scripts/feishu_upload.py --config config/feishu.json --debug

    # 作为模块
    from scripts.feishu_upload import FeishuUploader, upload_candidate

    uploader = FeishuUploader.from_config("config/feishu.json", org="hanxing")
    record_id, is_new = uploader.upsert_candidate(candidate_info_dict)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional

import requests

# ---------------------------------------------------------------------------
# 配置结构
# ---------------------------------------------------------------------------

@dataclass
class FeishuOrgConfig:
    """单个组织的飞书配置"""
    app_id: str
    app_secret: str
    app_token: str = ""
    table_id: str = ""
    field_mapping: dict = field(default_factory=dict)
    _tenant_token: Optional[str] = field(default=None, repr=False)
    _token_expire_at: float = field(default=0.0, repr=False)

    def get_tenant_token(self, force_refresh: bool = False) -> str:
        """
        获取 tenant_access_token，自动刷新过期 token。

        Returns:
            token 字符串

        Raises:
            RuntimeError: 认证失败
            requests.RequestException: 网络错误
        """
        now = time.time()
        if not force_refresh and self._tenant_token and now < self._token_expire_at - 60:
            return self._tenant_token

        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(
            url,
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=20,
            headers={"Content-Type": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"飞书认证失败: code={data.get('code')}, msg={data.get('msg')}")

        self._tenant_token = data["tenant_access_token"]
        expire = data.get("expire", 7200)
        self._token_expire_at = now + expire - 60  # 提前60秒刷新
        return self._tenant_token

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_tenant_token()}",
            "Content-Type": "application/json",
        }


@dataclass
class FeishuConfig:
    """完整配置（支持多组织）"""
    hanxing: Optional[FeishuOrgConfig] = None

    @classmethod
    def from_file(cls, path: str | Path) -> "FeishuConfig":
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        cfg = cls()
        for org_name, org_data in raw.items():
            if org_name.startswith("_"):
                continue
            org_cfg = FeishuOrgConfig(
                app_id=org_data.get("app_id", ""),
                app_secret=org_data.get("app_secret", ""),
                app_token=org_data.get("app_token", ""),
                table_id=org_data.get("table_id", ""),
                field_mapping=org_data.get("field_mapping", {}),
            )
            setattr(cfg, org_name, org_cfg)
        return cfg


# ---------------------------------------------------------------------------
# 主类
# ---------------------------------------------------------------------------

class FeishuUploader:
    """
    飞书多维表格上传器

    用法：
        uploader = FeishuUploader.from_config("config/feishu.json", org="hanxing")
        record_id, is_new = uploader.upsert_candidate(candidate_info)
    """

    def __init__(self, org_config: FeishuOrgConfig):
        self.cfg = org_config
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})

    @classmethod
    def from_config(cls, config_path: str | Path, org: str = "hanxing") -> "FeishuUploader":
        """
        从配置文件加载。

        Args:
            config_path: config/feishu.json 路径
            org: 组织名（默认 hanxing）

        Returns:
            FeishuUploader 实例
        """
        cfg = FeishuConfig.from_file(config_path)
        org_cfg = getattr(cfg, org, None)
        if org_cfg is None:
            raise ValueError(f"配置中未找到组织: {org}，可用: {[k for k in cfg.__dataclass_fields__ if not k.startswith('_')]}")
        if not org_cfg.app_id or not org_cfg.app_secret:
            raise ValueError(f"组织 {org} 的 app_id 或 app_secret 未配置，请检查 config/feishu.json")
        return cls(org_cfg)

    # ---- API 基础 ----

    def _api_url(self, path: str) -> str:
        base = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.cfg.app_token}"
        return f"{base}{path}"

    def _get(self, path: str, params: dict | None = None, retry: int = 2) -> dict:
        url = self._api_url(path)
        for attempt in range(retry + 1):
            try:
                resp = self._session.get(url, headers=self.cfg.headers(), params=params, timeout=20)
                if resp.status_code == 429:
                    # 限流：指数退避
                    wait = int(resp.headers.get("Retry-After", 5)) * (attempt + 1)
                    print(f"[FeishuUploader] 429限流，等待 {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    if data.get("code") == 99991664 and attempt < retry:
                        # token 无效，强制刷新重试
                        self.cfg.get_tenant_token(force_refresh=True)
                        continue
                    raise RuntimeError(f"飞书 API 错误: code={data.get('code')}, msg={data.get('msg')}")
                return data.get("data", {})
            except requests.RequestException as e:
                if attempt < retry:
                    time.sleep(2 ** attempt)
                    continue
                raise
        return {}

    def _post(self, path: str, payload: dict, retry: int = 2) -> dict:
        url = self._api_url(path)
        for attempt in range(retry + 1):
            try:
                resp = self._session.post(url, headers=self.cfg.headers(), json=payload, timeout=20)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5)) * (attempt + 1)
                    print(f"[FeishuUploader] 429限流，等待 {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    if data.get("code") == 99991664 and attempt < retry:
                        self.cfg.get_tenant_token(force_refresh=True)
                        continue
                    raise RuntimeError(f"飞书 API 错误: code={data.get('code')}, msg={data.get('msg')}")
                return data.get("data", {})
            except requests.RequestException as e:
                if attempt < retry:
                    time.sleep(2 ** attempt)
                    continue
                raise
        return {}

    def _put(self, path: str, payload: dict, retry: int = 2) -> dict:
        url = self._api_url(path)
        for attempt in range(retry + 1):
            try:
                resp = self._session.put(url, headers=self.cfg.headers(), json=payload, timeout=20)
                if resp.status_code == 429:
                    wait = int(resp.headers.get("Retry-After", 5)) * (attempt + 1)
                    print(f"[FeishuUploader] 429限流，等待 {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if data.get("code") != 0:
                    if data.get("code") == 99991664 and attempt < retry:
                        self.cfg.get_tenant_token(force_refresh=True)
                        continue
                    raise RuntimeError(f"飞书 API 错误: code={data.get('code')}, msg={data.get('msg')}")
                return data.get("data", {})
            except requests.RequestException as e:
                if attempt < retry:
                    time.sleep(2 ** attempt)
                    continue
                raise
        return {}

    # ---- 记录操作 ----

    def list_records(
        self,
        page_size: int = 100,
        filter_expr: str | None = None,
        page_token: str | None = None,
    ) -> dict:
        """
        列出多维表格记录。

        Args:
            page_size: 每页数量（最大500）
            filter_expr: 过滤表达式
            page_token: 分页游标

        Returns:
            {"items": [...], "total": int, "page_token": str, "has_more": bool}
        """
        params: dict[str, Any] = {"page_size": min(page_size, 500)}
        if filter_expr:
            params["filter"] = filter_expr
        if page_token:
            params["page_token"] = page_token

        data = self._get(f"/tables/{self.cfg.table_id}/records", params=params)
        return {
            "items": data.get("items", []),
            "total": data.get("total", 0),
            "page_token": data.get("page_token", ""),
            "has_more": data.get("has_more", False),
        }

    def get_record(self, record_id: str) -> dict:
        """获取单条记录"""
        data = self._get(f"/tables/{self.cfg.table_id}/records/{record_id}")
        return data.get("record", {})

    def create_record(self, fields: dict) -> tuple[str, dict]:
        """
        创建一条记录。

        Returns:
            (record_id, record_dict)
        """
        data = self._post(f"/tables/{self.cfg.table_id}/records", {"fields": fields})
        record = data.get("record", {})
        return record.get("record_id", ""), record

    def update_record(self, record_id: str, fields: dict) -> tuple[str, dict]:
        """
        更新一条记录。

        Returns:
            (record_id, record_dict)
        """
        data = self._put(f"/tables/{self.cfg.table_id}/records/{record_id}", {"fields": fields})
        record = data.get("record", {})
        return record.get("record_id", ""), record

    # ---- 去重查询 ----

    def find_by_phone(self, phone: str) -> list[dict]:
        """
        按手机号查询候选人记录。

        Args:
            phone: 手机号（纯数字）

        Returns:
            匹配的 record 列表
        """
        if not phone:
            return []
        phone_col = self.cfg.field_mapping.get("phone", "手机号")
        # 飞书过滤表达式：精确匹配
        filter_expr = f'CurrentValue.[{phone_col}]="{phone}"'
        result = self.list_records(filter_expr=filter_expr, page_size=20)
        return result.get("items", [])

    def find_by_dedup_key(self, dedup_key: str) -> list[dict]:
        """
        按去重 key 查询候选人记录。

        Args:
            dedup_key: build_dedup_key() 生成的值

        Returns:
            匹配的 record 列表
        """
        if not dedup_key:
            return []
        dedup_col = self.cfg.field_mapping.get("dedup_key", "去重Key")
        if not dedup_col:
            return []
        filter_expr = f'CurrentValue.[{dedup_col}]="{dedup_key}"'
        result = self.list_records(filter_expr=filter_expr, page_size=20)
        return result.get("items", [])

    def find_by_name_company_title(
        self, name: str, company: str, title: str
    ) -> list[dict]:
        """
        按姓名+公司+岗位组合查询（兜底去重）。
        """
        if not name:
            return []
        name_col = self.cfg.field_mapping.get("name", "姓名")
        filter_parts = [f'CurrentValue.[{name_col}]="{name}"']
        if company:
            company_col = self.cfg.field_mapping.get("latest_company", "最近公司")
            filter_parts.append(f'CurrentValue.[{company_col}]="{company}"')
        if title:
            title_col = self.cfg.field_mapping.get("latest_title", "最近岗位")
            filter_parts.append(f'CurrentValue.[{title_col}]="{title}"')
        filter_expr = " AND ".join(filter_parts)
        result = self.list_records(filter_expr=filter_expr, page_size=20)
        return result.get("items", [])

    # ---- 核心写入方法 ----

    def upsert_candidate(self, candidate: dict) -> tuple[str, bool]:
        """
        写入或更新候选人记录（核心方法）。

        去重策略（优先级）：
          1. 手机号精确匹配
          2. 去重 key 匹配（name + phone + company + title 的 SHA1）
          3. 姓名 + 公司 + 岗位 组合匹配

        Args:
            candidate: CandidateInfo.to_dict() 或等效结构

        Returns:
            (record_id, is_new)
            - is_new=True 表示新建，False 表示更新

        Raises:
            RuntimeError: API 调用失败
        """
        name = candidate.get("name", "")
        phone = candidate.get("phone", "")
        dedup_key = candidate.get("dedup_key", "")
        company = candidate.get("latest_company", "")
        title = candidate.get("latest_title", "")

        # ---- 1. 先尝试按手机号查找 ----
        existing = self.find_by_phone(phone) if phone else []

        # ---- 2. 按去重 key 找 ----
        if not existing and dedup_key:
            existing = self.find_by_dedup_key(dedup_key)

        # ---- 3. 姓名+公司+岗位兜底 ----
        if not existing and name:
            existing = self.find_by_name_company_title(name, company, title)

        # 构建字段
        fields = self._map_to_feishu_fields(candidate)

        if existing:
            # 更新（取第一条匹配）
            record_id = existing[0].get("record_id", "")
            if record_id:
                print(f"[FeishuUploader] 更新已有记录: record_id={record_id}, name={name}")
                self.update_record(record_id, fields)
                return record_id, False

        # 新建
        print(f"[FeishuUploader] 新建记录: name={name}, phone={phone}")
        record_id, _ = self.create_record(fields)
        return record_id, True

    def _map_to_feishu_fields(self, candidate: dict) -> dict:
        """
        将候选人字段映射到飞书多维表格字段名。

        Args:
            candidate: 候选人 dict

        Returns:
            飞书 fields dict（键为飞书列名，值为对应值）
        """
        fm = self.cfg.field_mapping
        result = {}

        def put(our_key: str, feishu_col: str | None = None):
            if feishu_col is None:
                feishu_col = fm.get(our_key, our_key)
            val = candidate.get(our_key, "")
            if isinstance(val, list):
                val = ", ".join(val)
            result[feishu_col] = val

        put("name", fm.get("name"))
        put("age_gender", fm.get("age_gender"))
        put("education", fm.get("education"))
        put("experience_summary", fm.get("experience"))
        put("latest_company", fm.get("latest_company"))
        put("latest_title", fm.get("latest_title"))
        put("skills", fm.get("skills"))
        put("expected_salary", fm.get("expected_salary"))
        put("phone", fm.get("phone"))
        put("source", fm.get("source"))
        put("self_summary", fm.get("self_summary"))
        put("project_summary", fm.get("project_summary"))
        put("dedup_key", fm.get("dedup_key"))

        # 沟通状态
        if "status" in fm:
            result[fm["status"]] = candidate.get("status", "新入库")

        # 录入时间
        if "created_at" in fm:
            from datetime import datetime
            result[fm["created_at"]] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Boss 链接
        if "boss_url" in fm:
            result[fm["boss_url"]] = candidate.get("boss_url", "")

        return result

    # ---- 批量写入（推荐） ----

    def upsert_batch(self, candidates: list[dict]) -> dict:
        """
        批量写入候选人记录。

        Returns:
            {"created": int, "updated": int, "failed": int, "errors": list}
        """
        created = updated = failed = 0
        errors: list[dict] = []

        for c in candidates:
            try:
                _, is_new = self.upsert_candidate(c)
                if is_new:
                    created += 1
                else:
                    updated += 1
            except Exception as e:
                failed += 1
                errors.append({"candidate": c.get("name", ""), "error": str(e)})
                print(f"[FeishuUploader] 写入失败: {c.get('name')}: {e}")

        return {"created": created, "updated": updated, "failed": failed, "errors": errors}


# ---------------------------------------------------------------------------
# 便捷函数
# ---------------------------------------------------------------------------

def upload_candidate(
    candidate: dict,
    config_path: str = "config/feishu.json",
    org: str = "hanxing",
) -> tuple[str, bool]:
    """
    单条候选人写入（便捷入口）。

    用法：
        record_id, is_new = upload_candidate(candidate_info.to_dict())
    """
    uploader = FeishuUploader.from_config(config_path, org=org)
    return uploader.upsert_candidate(candidate)


# ---------------------------------------------------------------------------
# 命令行入口
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="飞书多维表格上传模块")
    parser.add_argument("--config", default="config/feishu.json",
                        help="配置文件路径")
    parser.add_argument("--org", default="hanxing",
                        help="组织名（配置中的 key）")
    parser.add_argument("--debug", action="store_true",
                        help="打印调试信息（不实际写入）")
    parser.add_argument("--test", action="store_true",
                        help="测试模式：模拟一条记录，不实际写入")
    args = parser.parse_args()

    # 测试数据
    test_candidate = {
        "name": "张三",
        "age_gender": "28岁/男",
        "education": "本科",
        "years_of_experience": "5年",
        "city": "上海",
        "expected_role": "Python开发",
        "expected_salary": "25-35K",
        "latest_company": "字节跳动",
        "latest_title": "高级后端工程师",
        "experience_summary": "2019-2022 字节跳动 Python开发\n2022-至今 字节跳动 高级后端工程师",
        "skills": ["Python", "Go", "Redis", "K8s", "MySQL"],
        "phone": "13800138000",
        "source": "Boss直聘",
        "status": "新入库",
        "boss_url": "https://www.zhipin.com/web/boss/resume/example",
    }

    # 计算去重 key
    from scripts.resume_parser import build_dedup_key
    test_candidate["dedup_key"] = build_dedup_key(
        name=test_candidate["name"],
        phone=test_candidate["phone"],
        latest_company=test_candidate["latest_company"],
        latest_title=test_candidate["latest_title"],
    )

    print("[feishu_upload] 配置路径:", args.config)
    print("[feishu_upload] 组织:", args.org)

    if args.test:
        print("[feishu_upload] 测试模式：打印映射结果")
        uploader = FeishuUploader.from_config(args.config, org=args.org)
        fields = uploader._map_to_feishu_fields(test_candidate)
        print(json.dumps(fields, ensure_ascii=False, indent=2))
        return

    if args.debug:
        print("[feishu_upload] 调试模式：不执行写入")
        uploader = FeishuUploader.from_config(args.config, org=args.org)
        print(f"  app_id: {uploader.cfg.app_id}")
        print(f"  app_token: {uploader.cfg.app_token}")
        print(f"  table_id: {uploader.cfg.table_id}")
        print(f"  field_mapping: {uploader.cfg.field_mapping}")
        print(f"  测试 candidate dedup_key: {test_candidate['dedup_key']}")
        return

    # 实际写入
    try:
        uploader = FeishuUploader.from_config(args.config, org=args.org)
        record_id, is_new = uploader.upsert_candidate(test_candidate)
        print(f"[feishu_upload] 完成: record_id={record_id}, is_new={is_new}")
    except Exception as e:
        print(f"[feishu_upload] 错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
