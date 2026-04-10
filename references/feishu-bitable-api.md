# 飞书多维表格 API 参考（OpenHR）

> 更新时间：2026-04-07  
> 用途：为 OpenHR 的候选人信息落表提供飞书多维表格（Bitable）认证、查询、创建、更新、去重与字段映射参考。  
> 已知 App ID：
> - 汉兴：`cli_a9f758c0efa2dcc4`
> - 个人：`cli_a83467f9ecba5013`

> 注意：这里记录的是 **服务端 OpenAPI 调用模式**。实际使用前还需要补充：
> - `app_secret`
> - `app_token`（多维表格应用 token）
> - `table_id`
> - 各字段的真实字段名/字段 ID

---

## 1. 基础概念

飞书多维表格常见标识：

- **app_id / app_secret**：应用凭证
- **tenant_access_token**：租户访问令牌
- **app_token**：多维表格应用 token（类似 base id）
- **table_id**：数据表 ID
- **record_id**：记录 ID
- **field name / field id**：字段名 / 字段唯一标识

OpenHR 场景里，常见流程是：
1. 用 `app_id + app_secret` 换 `tenant_access_token`
2. 按姓名/手机号/候选人链接查询是否已存在
3. 不存在则 `create record`
4. 已存在则 `update record`

---

## 2. 认证方式

### 2.1 获取 tenant_access_token

**Endpoint**
```http
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
Content-Type: application/json
```

**Request Body**
```json
{
  "app_id": "cli_xxx",
  "app_secret": "xxx"
}
```

**Response（示意）**
```json
{
  "code": 0,
  "msg": "ok",
  "tenant_access_token": "t-xxx",
  "expire": 7200
}
```

### Python 示例
```python
import requests


def get_tenant_access_token(app_id: str, app_secret: str) -> str:
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    resp = requests.post(url, json={
        "app_id": app_id,
        "app_secret": app_secret,
    }, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"get token failed: {data}")
    return data["tenant_access_token"]
```

---

## 3. 多维表格常用 API

## 3.1 查询记录

### Endpoint
```http
GET https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
Authorization: Bearer {tenant_access_token}
```

### 常用参数
- `page_size`：分页大小
- `page_token`：分页游标
- `filter`：过滤条件
- `sort`：排序
- `view_id`：按视图查询
- `field_names`：限制返回字段

### 示例：按手机号查询
```http
GET /open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=20&filter=CurrentValue.[手机号]="13800138000"
```

> 过滤表达式语法要以飞书当前 OpenAPI 文档为准；落地时建议先在 API 调试台验证。

### Python 示例
```python
import requests


def list_records(token: str, app_token: str, table_id: str, page_size: int = 100, page_token: str | None = None):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"page_size": page_size}
    if page_token:
        params["page_token"] = page_token
    resp = requests.get(url, headers=headers, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"list records failed: {data}")
    return data["data"]
```

---

## 3.2 创建记录

### Endpoint
```http
POST https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records
Authorization: Bearer {tenant_access_token}
Content-Type: application/json
```

### Request Body
```json
{
  "fields": {
    "候选人姓名": "张三",
    "手机号": "13800138000",
    "学历": "本科",
    "工作年限": 3,
    "期望岗位": "Python开发",
    "期望薪资": "15-20K",
    "Boss链接": "https://www.zhipin.com/...",
    "跟进状态": "新入库"
  }
}
```

### Python 示例
```python
import requests


def create_record(token: str, app_token: str, table_id: str, fields: dict):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json={"fields": fields}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"create record failed: {data}")
    return data["data"]["record"]
```

---

## 3.3 更新记录

### Endpoint
```http
PUT https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}
Authorization: Bearer {tenant_access_token}
Content-Type: application/json
```

### Request Body
```json
{
  "fields": {
    "跟进状态": "已打招呼",
    "最新沟通时间": 1712493000,
    "备注": "候选人对薪资有兴趣"
  }
}
```

### Python 示例
```python
import requests


def update_record(token: str, app_token: str, table_id: str, record_id: str, fields: dict):
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    resp = requests.put(url, headers=headers, json={"fields": fields}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"update record failed: {data}")
    return data["data"]["record"]
```

---

## 3.4 批量创建 / 批量更新（推荐）

OpenHR 后续量大时，建议优先使用批量接口，减少限流和往返请求。

常见思路：
- 先收集本轮候选人数据到本地队列
- 每 10~50 条打包一次上传
- 对失败项做重试

> 批量接口的路径、单次上限和 payload 细节，以飞书当前官方文档为准；实现时别硬编码旧版本限制。

---

## 4. 字段类型映射建议

下面是 OpenHR 常见候选人字段 → 飞书多维表格字段类型建议：

| OpenHR 字段 | 飞书字段类型 | 示例 | 说明 |
|---|---|---|---|
| 候选人姓名 | 单行文本 | 张三 | 主展示字段 |
| 手机号 | 单行文本 | 13800138000 | 不建议用数字，避免前导 0/格式化 |
| 年龄 | 数字 | 28 | 可用于筛选 |
| 学历 | 单选 / 单行文本 | 本科 | 值集合固定时优先单选 |
| 工作年限 | 数字 | 3 | 用于排序/筛选 |
| 当前城市 | 单选 / 文本 | 上海 | 城市枚举可单选 |
| 期望岗位 | 单行文本 | Python开发 | |
| 期望薪资 | 单行文本 | 15-20K | 薪资区间不规则，文本更稳 |
| 最近公司 | 单行文本 | 字节跳动 | |
| 最近岗位 | 单行文本 | 后端工程师 | |
| 技能标签 | 多选 | Python, FastAPI, MySQL | 推荐多选 |
| 工作经历摘要 | 多行文本 | ... | |
| 教育经历摘要 | 多行文本 | ... | |
| 自我评价 | 多行文本 | ... | |
| Boss链接 | 超链接 / 文本 | https://... | 推荐超链接 |
| 简历快照JSON | 多行文本 | { ... } | 用于追溯原始结构 |
| 跟进状态 | 单选 | 新入库 / 已打招呼 / 已回复 / 已约面 | 固定状态机 |
| 最新沟通时间 | 日期时间 | 2026-04-07 21:00 | |
| HR备注 | 多行文本 | ... | |

### 推荐状态字段枚举
- 新入库
- 已打招呼
- 已回复
- 待跟进
- 已约面
- 已拒绝
- 不匹配

---

## 5. OpenHR 推荐表结构

建议至少包含以下列：

### 核心主表：`候选人池`
- 候选人姓名
- 手机号
- 学历
- 工作年限
- 当前城市
- 期望岗位
- 期望薪资
- 最近公司
- 最近岗位
- 技能标签
- Boss链接
- 跟进状态
- 最新沟通时间
- HR备注
- 去重Key
- 原始简历JSON

### 可选扩展表
1. `沟通记录`
2. `岗位需求`
3. `面试安排`
4. `黑名单 / 不再联系`

---

## 6. 去重策略（非常重要）

OpenHR 不建议仅靠“姓名”去重。推荐优先级：

1. 手机号
2. Boss 候选人链接 / 简历链接
3. 平台唯一 ID
4. `姓名 + 最近公司 + 最近岗位`

### 推荐实现
新增一个 `去重Key` 字段：
```python
import hashlib


def build_dedup_key(name: str, phone: str | None, boss_url: str | None, latest_company: str | None, latest_title: str | None) -> str:
    raw = "|".join([
        phone or "",
        boss_url or "",
        name or "",
        latest_company or "",
        latest_title or "",
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
```

写入前：
- 先按 `手机号` 或 `去重Key` 查询
- 命中则 update
- 未命中则 create

---

## 7. Python 封装示例（适合直接落到 feishu_upload.py）

```python
from __future__ import annotations
import requests
from typing import Any


class FeishuBitableClient:
    def __init__(self, app_id: str, app_secret: str, app_token: str, table_id: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.app_token = app_token
        self.table_id = table_id
        self._tenant_token = None

    def get_tenant_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={
            "app_id": self.app_id,
            "app_secret": self.app_secret,
        }, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data)
        self._tenant_token = data["tenant_access_token"]
        return self._tenant_token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.get_tenant_token()}",
            "Content-Type": "application/json",
        }

    def list_records(self, page_size: int = 100, filter_expr: str | None = None) -> dict[str, Any]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"
        params = {"page_size": page_size}
        if filter_expr:
            params["filter"] = filter_expr
        resp = requests.get(url, headers=self._headers(), params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data)
        return data["data"]

    def create_record(self, fields: dict[str, Any]) -> dict[str, Any]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records"
        resp = requests.post(url, headers=self._headers(), json={"fields": fields}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data)
        return data["data"]["record"]

    def update_record(self, record_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records/{record_id}"
        resp = requests.put(url, headers=self._headers(), json={"fields": fields}, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(data)
        return data["data"]["record"]
```

---

## 8. HTTP 调试示例（curl）

### 获取 token
```bash
curl -X POST 'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal' \
  -H 'Content-Type: application/json' \
  -d '{
    "app_id": "cli_a9f758c0efa2dcc4",
    "app_secret": "YOUR_APP_SECRET"
  }'
```

### 创建记录
```bash
curl -X POST "https://open.feishu.cn/open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records" \
  -H "Authorization: Bearer ${TENANT_ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "fields": {
      "候选人姓名": "张三",
      "学历": "本科",
      "工作年限": 3,
      "跟进状态": "新入库"
    }
  }'
```

### 更新记录
```bash
curl -X PUT "https://open.feishu.cn/open-apis/bitable/v1/apps/${APP_TOKEN}/tables/${TABLE_ID}/records/${RECORD_ID}" \
  -H "Authorization: Bearer ${TENANT_ACCESS_TOKEN}" \
  -H 'Content-Type: application/json' \
  -d '{
    "fields": {
      "跟进状态": "已打招呼"
    }
  }'
```

---

## 9. 错误处理与限流建议

### 常见错误来源
- token 过期
- app 没开多维表格权限
- table_id / app_token 错
- 字段名拼写不一致
- 字段类型不匹配（例如多选字段传成字符串）

### 建议策略
- token 失败自动刷新 1 次
- 429 / 高频错误做指数退避
- 写入失败时把 payload 落本地 JSON 方便补偿
- 启动时先校验字段 schema，不要跑到一半才发现字段名不对

---

## 10. OpenHR 集成建议

### 推荐字段映射函数
```python
def map_candidate_to_feishu_fields(candidate: dict) -> dict:
    return {
        "候选人姓名": candidate.get("name", ""),
        "手机号": candidate.get("phone", ""),
        "学历": candidate.get("education", ""),
        "工作年限": candidate.get("years_of_experience", 0),
        "当前城市": candidate.get("city", ""),
        "期望岗位": candidate.get("expected_role", ""),
        "期望薪资": candidate.get("expected_salary", ""),
        "最近公司": candidate.get("latest_company", ""),
        "最近岗位": candidate.get("latest_title", ""),
        "Boss链接": candidate.get("boss_url", ""),
        "跟进状态": candidate.get("status", "新入库"),
        "HR备注": candidate.get("remark", ""),
        "去重Key": candidate.get("dedup_key", ""),
        "原始简历JSON": candidate.get("raw_resume_json", ""),
    }
```

### 推荐写入策略
- `resume_parser.py` 输出结构化 JSON
- `feishu_upload.py` 负责：
  - 鉴权
  - 去重查询
  - create / update
  - 错误重试
- 聊天模块只更新状态，不直接改复杂字段

---

## 11. 当前落地所需补充清单

开发前还需要补齐：
- [ ] 选择使用“汉兴”还是“个人”飞书应用
- [ ] 对应 `app_secret`
- [ ] 多维表格 `app_token`
- [ ] 目标表 `table_id`
- [ ] 字段中文名 / field_id 对照表
- [ ] 去重规则最终版本

---

## 12. 结论

飞书多维表格很适合作为 OpenHR 的轻量 CRM：
- 入门快
- 可视化强
- 方便 HR 手工干预
- 适合候选人池 / 跟进状态管理

真正要注意的不是 API 本身，而是：
- 字段建模
- 去重规则
- 错误补偿
- 批量写入与限流

这几件事做好，后面接 Boss 简历和聊天状态就会非常顺。
