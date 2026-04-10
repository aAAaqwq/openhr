# Boss直聘 页面结构与自动化参考（OpenHR）

> 更新时间：2026-04-07  
> 用途：为 OpenHR 的登录、候选人浏览、打招呼、聊天、简历抓取模块提供页面 URL、DOM 结构、交互流程参考。  
> 重要说明：Boss 直聘是 **SPA / 动态加载站点**，登录后 DOM 结构、class 名、接口返回和懒加载行为可能与未登录态不同。下面选择器分为：
> - **高置信稳定选择器**：基于 URL / placeholder / 语义属性 / 结构推断，优先使用
> - **候选选择器**：需要在真实登录态里再校准
> - **不推荐**：仅靠动态 class / nth-child

---

## 1. 关键页面 URL 列表

### 通用入口
- 首页：`https://www.zhipin.com/`
- 登录/注册页：`https://www.zhipin.com/web/user/`
- 招聘者入口（我要招聘）：`https://www.zhipin.com/web/user/?intent=1`
- 求职者入口（我要找工作）：`https://www.zhipin.com/web/user/?intent=0`

### 招聘 / 候选人相关（需登录后验证）
> 下面路径在招聘者登录态下通常可访问；实际 URL 可能带 query/hash 参数。

- 候选人推荐列表页（推断）：`https://www.zhipin.com/web/boss/recommend`
- 沟通 / 聊天页（推断）：`https://www.zhipin.com/web/boss/chat`
- 候选人简历详情页（推断）：`https://www.zhipin.com/web/boss/resume`
- 职位管理页（推断）：`https://www.zhipin.com/web/boss/job`

### 公开可观测页面
- 职位搜索页：`https://www.zhipin.com/web/geek/jobs`
- 首页“查看更多职位”：`https://www.zhipin.com/web/geek/job-recommend`
- 公司页：`https://www.zhipin.com/gongsi/`

---

## 2. 已观测到的公共页 DOM 事实

2026-04-07 对公开首页抓取可确认：

- 顶部有登录入口：`a[href="https://www.zhipin.com/web/user/"]`
- 顶部有招聘入口：`a[href="https://www.zhipin.com/web/user/?intent=1"]`
- 首页搜索框存在 placeholder：`input[placeholder*="搜索职位"]`
- 公共职位详情链接形态稳定：`a[href*="/job_detail/"]`
- 首页/列表页为懒加载、分段渲染，页面中会出现“正在加载中”

因此：
- **自动化脚本不要等全页静态渲染完成**，而应等待局部业务节点出现
- **应优先用 URL / role / text / placeholder / data 属性**，少依赖 class 名

---

## 3. 关键 DOM 选择器建议

## 3.1 登录页

### 高置信选择器
```css
/* 登录入口 */
a[href="https://www.zhipin.com/web/user/"]
a[href*="/web/user/"]

/* 招聘者模式入口 */
a[href*="intent=1"]

/* 求职者模式入口 */
a[href*="intent=0"]

/* 页面加载态 */
body
```

### 自动化建议
- 进入招聘者模式时优先打开：`/web/user/?intent=1`
- 不要假设一打开就是二维码登录，Boss 可能先渲染 tab、手机号登录、协议弹层等
- Playwright 建议：
  - 先 `wait_for_load_state("domcontentloaded")`
  - 再等待 “扫码登录 / 手机号登录 / 验证码 / 协议确认” 任一节点出现

### 登录模块判定逻辑
```python
# 已登录判定（建议多信号）
LOGGED_IN_SIGNALS = [
    'a[href*="/web/boss/chat"]',
    'a[href*="/web/boss/recommend"]',
    'img[alt*="头像"]',
    '[class*="user-nav"]',
]

# 未登录判定（建议多信号）
LOGGED_OUT_SIGNALS = [
    'a[href*="/web/user/"]',
    'text=登录',
    'text=注册',
    'text=扫码',
]
```

---

## 3.2 候选人推荐列表页（核心：遍历候选人 + 打招呼）

> 这一页是 OpenHR 的核心作业区。Boss 招聘端大概率采用左侧/中间列表 + 右侧详情抽屉或跳转详情页。

### 推荐 URL（需登录态验证）
- `https://www.zhipin.com/web/boss/recommend`

### 推荐选择器策略

#### A. 候选人卡片容器
优先顺序：
```css
/* 优先找可点击候选人详情链接 */
a[href*="resume"]
a[href*="candidate"]
a[href*="geek"]

/* 次优：带用户信息块的列表项 */
main li
section li
[class*="card"]
[class*="list"] > *
```

#### B. 候选人卡片内部字段
```css
/* 姓名 */
h3, h4, strong, [class*="name"]

/* 标签/学历/年限/期望薪资 */
[class*="tag"], [class*="label"], [class*="info"], [class*="meta"]

/* 地理位置 */
[class*="city"], [class*="location"]
```

#### C. 打招呼按钮
```css
button:has-text("打招呼")
button:has-text("立即沟通")
button:has-text("立即开聊")
a:has-text("打招呼")
```

> Playwright 推荐优先使用：
```python
page.get_by_role("button", name=re.compile("打招呼|立即沟通|立即开聊"))
```

### 候选人卡片抓取建议
推荐不要直接依赖 class，而是：
1. 先枚举当前 viewport 内所有可点击卡片
2. 进入每张卡片后抽取文本块
3. 将卡片文本做结构化解析（正则/LLM）
4. 仅在满足岗位条件时点击“打招呼”

### 列表页分页 / 加载
Boss 为 SPA + 虚拟滚动概率高：
- 向下滚动可能触发下一批候选人加载
- 已渲染元素可能被回收
- DOM 中不一定保留完整历史节点

所以：
- 不要预先抓全量列表再处理
- 应采用 **滚动一屏 → 抽取一屏 → 处理一屏 → 记录游标/ID** 模式

---

## 3.3 聊天页（核心：发送消息 + 读取候选人回复）

### 推荐 URL（需登录态验证）
- `https://www.zhipin.com/web/boss/chat`

### 核心选择器建议

#### 会话列表
```css
aside li
[class*="session"]
[class*="conversation"]
a[href*="chat"]
```

#### 消息流区域
```css
main
[class*="message"]
[class*="chat-content"]
[class*="msg-list"]
```

#### 单条消息
```css
[class*="message-item"]
[class*="msg"]
li
```

#### 聊天输入框
```css
textarea
div[contenteditable="true"]
[role="textbox"]
```

#### 发送按钮
```css
button:has-text("发送")
button:has-text("发 送")
```

### 聊天脚本实现建议
优先级：
1. `textarea`
2. `div[contenteditable="true"]`
3. `[role="textbox"]`

Playwright 示例：
```python
input_box = (
    page.locator("textarea").first
    .or_(page.locator('div[contenteditable="true"]').first)
    .or_(page.locator('[role="textbox"]').first)
)
await input_box.click()
await input_box.fill(message)
await page.get_by_role("button", name="发送").click()
```

### 读取消息方向
可通过以下方式区分我方/对方：
- 左右布局位置
- 头像容器 class 差异
- 文本气泡 class 差异
- 消息节点是否包含“已读/未读/发送失败”等状态

建议代码中抽象为：
```python
{
  "sender": "boss" | "candidate" | "system",
  "text": "...",
  "ts": "...",
  "raw_html": "..."
}
```

---

## 3.4 简历详情页（核心：结构化提取）

### 推荐 URL（需登录态验证）
- `https://www.zhipin.com/web/boss/resume`

### 应抓取的字段
- 姓名
- 性别/年龄
- 学历
- 工作年限
- 当前城市
- 期望职位
- 期望薪资
- 最近公司
- 最近岗位
- 工作经历
- 项目经历
- 教育经历
- 技能标签
- 自我评价

### 选择器策略

#### 简历主区域
```css
main
article
section
[class*="resume"]
[class*="detail"]
```

#### 基本信息块
```css
header
[class*="base"]
[class*="summary"]
```

#### 分节标题
```css
h2, h3, h4
```

#### 结构化信息项
```css
dt, dd
li
p
[class*="item"]
[class*="row"]
```

### 简历解析建议
不要企图只靠 CSS 精准定位每个字段，Boss 页面经常改版。更稳的是：

1. 先抓整个简历主区域纯文本
2. 再按标题切块：
   - 基本信息
   - 工作经历
   - 教育经历
   - 项目经历
   - 个人优势/自我评价
3. 用规则 + LLM 双层抽取

示例：
```python
resume_root = page.locator("main, article, [class*='resume']").first
resume_text = await resume_root.inner_text()
```

---

## 4. 页面交互流程说明

## 4.1 登录流程
1. 打开 `https://www.zhipin.com/web/user/?intent=1`
2. 等待登录组件渲染
3. 如出现协议弹窗，先勾选/确认
4. 识别当前登录方式：
   - 扫码登录
   - 手机验证码登录
5. 若需人工扫码：
   - 截图二维码区域
   - 通知操作者扫码
6. 登录成功后：
   - 保存 cookies / localStorage / sessionStorage
   - 打开招聘端主页验证登录态

### 持久化建议
- 保存 `storage_state.json`
- 每次启动先载入 storage state
- 若访问招聘页被重定向回 `/web/user/`，则判定登录态失效

---

## 4.2 候选人浏览与打招呼流程
1. 进入候选人推荐列表页
2. 等待列表容器出现
3. 抽取当前屏候选人卡片文本
4. 对每张卡片做岗位匹配评分
5. 满足条件才点击“打招呼”
6. 随机等待 5-15 秒
7. 记录候选人唯一标识 + 已沟通状态
8. 滚动加载下一批

### 去重键建议
优先顺序：
- 页面中的候选人 profile/resume URL
- 页面内隐藏 ID / data-id
- 姓名 + 城市 + 最近岗位 + 最近公司

---

## 4.3 聊天跟进流程
1. 进入聊天页
2. 轮询未读会话
3. 读取最后 N 条消息
4. 判断聊天状态：
   - 初次沟通
   - 有意向
   - 约面试
   - 已拒绝
5. 调用 LLM 生成回复
6. 将回复写入输入框，人工审核或自动发送
7. 同步关键信息到飞书

---

## 4.4 简历抓取流程
1. 从候选人卡片或聊天页打开简历详情
2. 等待简历主容器出现
3. 抓取全文文本 / 分节 HTML
4. 结构化解析
5. 写入本地 JSON
6. 上传飞书多维表格

---

## 5. Playwright 选择器实践建议

### 推荐优先级
1. `get_by_role()`
2. `get_by_text()` / `has_text`
3. `placeholder` / `label` / `href`
4. 稳定 `data-*` 属性
5. 语义 class
6. 绝不默认用 `nth-child`

### 示例
```python
# 登录入口
page.locator('a[href*="/web/user/"]')

# 搜索框（公开页已验证可用）
page.locator('input[placeholder*="搜索职位"]')

# 打招呼按钮
page.get_by_role("button", name=re.compile("打招呼|立即沟通|立即开聊"))

# 聊天输入框
page.locator('textarea, div[contenteditable="true"], [role="textbox"]')
```

---

## 6. 风险与注意事项

### 6.1 SPA 风险
- DOM 延迟渲染
- 虚拟滚动导致旧节点消失
- URL 不切换但页面内容已变

### 6.2 反自动化风险
- class/hash 频繁变化
- 高频点击 / 同节奏输入容易触发风控
- 短时间批量打招呼极易出现限制

### 6.3 开发建议
- 所有关键选择器写进配置文件
- 每次定位失败自动截图 + 导出 HTML 片段
- 业务逻辑不要和具体 class 耦合

---

## 7. 建议的 selector 配置结构

```json
{
  "login": {
    "entry": [
      "a[href='https://www.zhipin.com/web/user/']",
      "a[href*='/web/user/']"
    ],
    "recruiter_intent": [
      "a[href*='intent=1']"
    ]
  },
  "recommend": {
    "candidate_cards": [
      "a[href*='resume']",
      "a[href*='candidate']",
      "main li",
      "section li",
      "[class*='card']"
    ],
    "greet_button": [
      "button:has-text('打招呼')",
      "button:has-text('立即沟通')",
      "button:has-text('立即开聊')"
    ]
  },
  "chat": {
    "input": [
      "textarea",
      "div[contenteditable='true']",
      "[role='textbox']"
    ],
    "send": [
      "button:has-text('发送')"
    ]
  },
  "resume": {
    "root": [
      "main",
      "article",
      "[class*='resume']",
      "[class*='detail']"
    ]
  }
}
```

---

## 8. 给开发同学的落地建议

### 最小可用策略
- 登录模块：只做登录态检测 + storage state 保存
- 打招呼模块：只做“遍历候选人卡片 + 点击打招呼”
- 聊天模块：只做“识别输入框 + 发送消息”
- 简历模块：只做“抓全文文本 + LLM 结构化”

### 第二阶段再做
- 候选人智能评分
- 会话优先级队列
- 简历/聊天字段精细抽取
- 自动恢复 / 断点续跑

---

## 9. 结论

Boss 直聘自动化不应理解为“找几个 class 名然后写死脚本”，而应按 **SPA 场景的弹性抓取架构** 去实现：
- URL 只作为导航参考
- 选择器优先使用语义与文本
- 文本抽取优先于像素级 DOM 绑定
- 每个模块必须支持截图、HTML 片段、失败回放

这套思路更适合 OpenHR 后续持续迭代。
