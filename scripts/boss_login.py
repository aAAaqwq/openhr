"""
Boss 直聘登录模块 (c1)
用于检测登录态、生成二维码、Cookie 持久化

依赖:
    - playwright: pip install playwright && playwright install chromium
    - 参考: references/boss-api.md, references/anti-detect-guide.md

用法:
    python scripts/boss_login.py          # 检测登录态，未登录则生成二维码截图
    python scripts/boss_login.py --check  # 仅检查登录态
    python scripts/boss_login.py --qr    # 强制生成二维码截图
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

# ============================================================
# 常量配置
# ============================================================

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
COOKIES_DIR = PROJECT_ROOT / "data" / "cookies"
COOKIE_FILE = COOKIES_DIR / "boss_cookies.json"
COOKIE_META_FILE = COOKIES_DIR / "boss_cookies_meta.json"

# Boss 直聘登录页（招聘者入口）
LOGIN_URL = "https://www.zhipin.com/web/user/?intent=1"

# 招聘端主页（登录成功后验证用）
HOME_URL = "https://www.zhipin.com/web/boss/"

# 默认 Cookie 有效期（小时）
DEFAULT_COOKIE_EXPIRY_HOURS = 24

# 反检测 stealth JS
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en-US', 'en'] });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4] });
window.chrome = window.chrome || { runtime: {} };
"""


# ============================================================
# 内部工具函数
# ============================================================

def _ensure_cookies_dir() -> Path:
    """确保 cookies 目录存在"""
    COOKIES_DIR.mkdir(parents=True, exist_ok=True)
    return COOKIES_DIR


async def _get_browser_context() -> tuple:
    """创建带反检测配置的 Playwright BrowserContext"""
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=False,  # 有界面模式，降低被检测风险
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
        ],
    )
    context = await browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    await context.add_init_script(STEALTH_JS)
    return pw, browser, context


def _is_cookie_expired(meta: dict) -> bool:
    """检测 cookie 是否过期"""
    if not meta or "saved_at" not in meta:
        return True
    saved_at = datetime.fromisoformat(meta["saved_at"])
    expiry_hours = meta.get("expiry_hours", DEFAULT_COOKIE_EXPIRY_HOURS)
    return datetime.now() > saved_at + timedelta(hours=expiry_hours)


# ============================================================
# 核心函数
# ============================================================

async def check_login(page: Page) -> bool:
    """
    检测当前是否已登录 Boss 直聘（招聘者账号）

    检测策略（多信号判断）:
      - 登录后可见元素：聊天入口、推荐候选人入口、用户头像
      - 未登录信号：顶部有"登录"链接

    Args:
        page: Playwright Page 对象

    Returns:
        True 表示已登录，False 表示未登录
    """
    try:
        # 等待页面加载
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
        await asyncio.sleep(2)  # 等待 SPA 渲染

        # 高置信登录信号
        logged_in_selectors = [
            'a[href*="/web/boss/chat"]',
            'a[href*="/web/boss/recommend"]',
            'img[alt*="头像"]',
            "[class*='user-nav']",
        ]

        for selector in logged_in_selectors:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=3000):
                    print(f"[check_login] 已登录（检测到: {selector}）")
                    return True
            except Exception:
                pass

        # 检查未登录信号
        logged_out_selectors = [
            'a[href*="/web/user/"]',
            'text=登录',
            'text=扫码',
        ]

        for selector in logged_out_selectors:
            try:
                elem = page.locator(selector).first
                if await elem.is_visible(timeout=3000):
                    print(f"[check_login] 未登录（检测到: {selector}）")
                    return False
            except Exception:
                pass

        # 默认：无法判断，尝试访问主页看是否被重定向
        current_url = page.url
        print(f"[check_login] 当前 URL: {current_url}")
        if "/web/user/" in current_url:
            return False
        if "/web/boss/" in current_url:
            return True

        return False

    except Exception as e:
        print(f"[check_login] 检测异常: {e}，默认返回未登录")
        return False


async def generate_qr_code(output_path: Optional[str] = None) -> str:
    """
    生成 Boss 直聘登录二维码截图

    通过 Playwright 打开登录页，等待二维码渲染完成后截图。

    Args:
        output_path: 截图保存路径，默认保存到 data/cookies/boss_qr_{timestamp}.png

    Returns:
        截图文件路径
    """
    _ensure_cookies_dir()

    timestamp = int(time.time())
    default_path = str(COOKIES_DIR / f"boss_qr_{timestamp}.png")
    save_path = output_path or default_path

    print(f"[generate_qr_code] 启动浏览器，打开登录页: {LOGIN_URL}")

    pw, browser, context = await _get_browser_context()
    page = await context.new_page()

    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        print("[generate_qr_code] 等待登录组件渲染...")

        # 等待登录方式出现（扫码 or 手机号登录）
        # Boss 可能先弹出协议层，先处理
        try:
            agree_btn = page.get_by_text("同意").or_(page.get_by_text("确定")).or_(page.get_by_text("我已知晓"))
            if await agree_btn.is_visible(timeout=5000):
                await agree_btn.click()
                print("[generate_qr_code] 已点击协议确认按钮")
                await asyncio.sleep(1)
        except Exception:
            pass

        # 等待扫码登录区域或二维码容器出现
        # CSS 选择器（优先）
        qr_css_selectors = [
            "[class*='qrcode']",
            "[class*='qr-code']",
            "[class*='qr_code']",
            "[class*='qrcode'] img",
            "canvas",
            "img[src*='qr']",
            "img[src*='qrcode']",
            "[class*='login'] img",
        ]

        # XPath 降级选择器
        qr_xpath_selectors = [
            "//*[contains(@class, 'qrcode')]",
            "//*[contains(@class, 'qr-code')]",
            "//canvas",
            "//img[contains(@src, 'qr')]",
        ]

        qr_found = False
        for sel in qr_css_selectors:
            try:
                elem = page.locator(sel).first
                if await elem.is_visible(timeout=8000):
                    print(f"[generate_qr_code] 二维码 CSS 选择器命中: {sel}")
                    qr_found = True
                    break
            except Exception:
                pass

        # CSS 全失败，尝试 XPath 降级
        if not qr_found:
            for xpath in qr_xpath_selectors:
                try:
                    elem = page.locator(f"xpath={xpath}").first
                    if await elem.is_visible(timeout=8000):
                        print(f"[generate_qr_code] 二维码 XPath 降级成功: {xpath}")
                        qr_found = True
                        break
                except Exception:
                    pass

        if not qr_found:
            print("[generate_qr_code] 未能自动识别二维码区域，尝试截取全屏...")

        # 多等一会儿确保二维码完全渲染
        await asyncio.sleep(3)

        # 截图
        await page.screenshot(path=save_path, full_page=False)
        print(f"[generate_qr_code] 二维码已保存: {save_path}")

        # 提示用户
        print("\n" + "=" * 50)
        print("  ⚠️  请打开 Boss直聘 App 扫码登录")
        print("  截图路径: " + save_path)
        print("=" * 50 + "\n")

        return save_path

    except Exception as e:
        print(f"[generate_qr_code] 异常: {e}")
        raise
    finally:
        await context.close()
        await browser.close()
        await pw.stop()


def save_cookies(context: BrowserContext, meta: Optional[dict] = None) -> str:
    """
    将 BrowserContext 的 cookies 持久化到 JSON 文件

    Args:
        context: Playwright BrowserContext
        meta:     额外元数据（如 saved_at, expiry_hours）

    Returns:
        cookie 文件路径
    """
    _ensure_cookies_dir()

    cookies = asyncio.get_event_loop().run_until_complete(
        context.cookies()
    )

    meta_data = {
        "saved_at": datetime.now().isoformat(),
        "expiry_hours": DEFAULT_COOKIE_EXPIRY_HOURS,
        "cookie_count": len(cookies),
        **(meta or {}),
    }

    with open(COOKIE_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)

    with open(COOKIE_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta_data, f, ensure_ascii=False, indent=2)

    print(f"[save_cookies] 已保存 {len(cookies)} 个 cookies 到: {COOKIE_FILE}")
    print(f"[save_cookies] 元数据: {meta_data}")
    return str(COOKIE_FILE)


def load_cookies(context: BrowserContext) -> bool:
    """
    从 JSON 文件加载 cookies 到 BrowserContext

    Args:
        context: Playwright BrowserContext

    Returns:
        True 表示加载成功，False 表示文件不存在或过期
    """
    if not COOKIE_FILE.exists():
        print("[load_cookies] cookie 文件不存在")
        return False

    # 检查过期
    meta = {}
    if COOKIE_META_FILE.exists():
        with open(COOKIE_META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)
        if _is_cookie_expired(meta):
            print("[load_cookies] cookie 已过期，需要重新登录")
            return False

    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    asyncio.get_event_loop().run_until_complete(
        context.add_cookies(cookies)
    )
    print(f"[load_cookies] 已加载 {len(cookies)} 个 cookies")
    return True


# ============================================================
# 主流程
# ============================================================

async def main():
    """主入口：检测登录态，未登录则生成二维码，等待扫码登录后保存 cookies"""
    import argparse

    parser = argparse.ArgumentParser(description="Boss 直聘登录模块")
    parser.add_argument("--check", action="store_true", help="仅检查登录态")
    parser.add_argument("--qr", action="store_true", help="强制生成二维码截图")
    parser.add_argument("--qr-output", type=str, help="二维码截图保存路径")
    args = parser.parse_args()

    _ensure_cookies_dir()

    pw, browser, context = await _get_browser_context()
    page = await context.new_page()

    try:
        # 尝试加载已有 cookies
        cookies_loaded = load_cookies(context)

        if cookies_loaded:
            print("[main] 已加载 cookies，访问主页验证登录态...")
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(3)

        if args.check:
            # 仅检查
            is_logged_in = await check_login(page)
            print(f"登录状态: {'已登录' if is_logged_in else '未登录'}")
            return

        if args.qr or not cookies_loaded:
            # 生成二维码
            qr_path = await generate_qr_code(args.qr_output)
            print(f"[main] 请扫码登录: {qr_path}")

            # 等待用户扫码登录（轮询检查）
            print("[main] 等待扫码登录...（每 5 秒检测一次）")
            login_timeout = 600  # 10 分钟超时
            start = time.time()

            while time.time() - start < login_timeout:
                await asyncio.sleep(5)
                try:
                    is_logged_in = await check_login(page)
                    if is_logged_in:
                        print("[main] ✅ 检测到登录成功！")
                        break
                    # 未登录，重新加载登录页继续等待
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"[main] 检测异常: {e}")
                    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=15000)
            else:
                print("[main] ❌ 扫码登录超时（10分钟）")
                sys.exit(1)

        # 保存 cookies
        save_cookies(context)
        print("[main] ✅ 登录流程完成")

    finally:
        await context.close()
        await browser.close()
        await pw.stop()


if __name__ == "__main__":
    asyncio.run(main())
