from __future__ import annotations

import json
import os
import random
import re
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, unquote_to_bytes

from bs4 import BeautifulSoup


BASE_TIEBA_URL = "https://tieba.baidu.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class TiebaError(RuntimeError):
    pass


@dataclass
class Forum:
    name: str
    url: str


@dataclass
class SignResult:
    forum: str
    ok: bool
    message: str


@dataclass
class AccountResult:
    label: str
    ok: bool
    message: str
    details: list[str] = field(default_factory=list)


def progress(message: str) -> None:
    print(message, flush=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if minimum is not None:
        value = max(minimum, value)
    return value


def parse_interval(value: str, default: str = "3-8") -> tuple[float, float]:
    raw = (value or default).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*[-~]\s*(\d+(?:\.\d+)?))?", raw)
    if not match:
        raw = default
        match = re.fullmatch(r"(\d+(?:\.\d+)?)(?:\s*[-~]\s*(\d+(?:\.\d+)?))?", raw)
    assert match is not None
    start = max(0.0, float(match.group(1)))
    end = max(0.0, float(match.group(2) or match.group(1)))
    if start > end:
        start, end = end, start
    return start, end


def random_interval_seconds() -> float:
    start, end = parse_interval(os.getenv("TIEBA_INTERVAL_SECONDS", "3-8"))
    if start == end:
        return start
    return random.uniform(start, end)


def sleep_between_actions() -> None:
    seconds = random_interval_seconds()
    if seconds > 0:
        time.sleep(seconds)


def decode_forum_name(value: str) -> str:
    if not value:
        return ""
    if "%" not in value:
        return value.strip()
    raw = unquote_to_bytes(value)
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return raw.decode(encoding).strip()
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace").strip()


def load_cookie_json(raw: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TiebaError("TIEBA_COOKIES is not valid JSON.") from exc
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise TiebaError("TIEBA_COOKIES must be a JSON cookie object or list.")
    cookies: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        value = item.get("value")
        if name and value is not None:
            cookie = dict(item)
            cookie["name"] = name
            cookie["value"] = str(value)
            cookie.setdefault("domain", ".baidu.com")
            cookie.setdefault("path", "/")
            cookies.append(cookie)
    if not cookies:
        raise TiebaError("TIEBA_COOKIES did not contain cookie name/value pairs.")
    return cookies


def split_accounts(raw: str) -> list[str]:
    return [part.strip() for part in re.split(r"[\r\n]+|#{3,}", raw) if part.strip()]


def load_accounts() -> list[tuple[str, list[dict[str, Any]]]]:
    raw = os.getenv("TIEBA_COOKIES", "").strip()
    if not raw:
        raise TiebaError("Missing TIEBA_COOKIES. Add exported Tieba cookies to GitHub Secrets.")
    accounts: list[tuple[str, list[dict[str, Any]]]] = []
    for index, account_raw in enumerate(split_accounts(raw), start=1):
        accounts.append((f"account-{index}", load_cookie_json(account_raw)))
    return accounts


def chromium_browser_path() -> str | None:
    for name in (
        "chromium-browser",
        "chromium",
        "google-chrome",
        "google-chrome-stable",
        "chrome",
    ):
        path = shutil.which(name)
        if path:
            return path
    return None


def create_page() -> Any:
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError as exc:
        raise TiebaError("DrissionPage is not installed.") from exc

    user_data_dir = tempfile.mkdtemp(prefix="tieba-browser-")
    port = random.randint(9300, 9999)
    options = ChromiumOptions()
    options.headless(True)
    for argument in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--disable-extensions",
        "--window-size=1365,900",
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        f"--user-agent={USER_AGENT}",
    ):
        options.set_argument(argument)
    browser_path = chromium_browser_path()
    if browser_path:
        options.set_browser_path(browser_path)
        progress(f"Chromium path: {browser_path}")
    else:
        progress("Chromium path: auto")
    progress("Starting Chromium...")
    return ChromiumPage(options)


def page_html(page: Any) -> str:
    html = getattr(page, "html", "")
    return html() if callable(html) else str(html or "")


def safe_text(element: Any) -> str:
    if not element:
        return ""
    try:
        return str(element.text or "").strip()
    except Exception:
        return ""


def is_logged_in(page: Any) -> bool:
    html = page_html(page)
    logged_out_markers = ("登录百度账号", "立即登录", "name=\"userName\"")
    logged_in_markers = ("我的贴吧", "退出", "个人中心", "i/i/forum")
    return any(marker in html for marker in logged_in_markers) and not any(
        marker in html for marker in logged_out_markers
    )


def inject_cookies(page: Any, cookies: list[dict[str, Any]]) -> None:
    page.get(BASE_TIEBA_URL)
    page.set.cookies(cookies)
    page.refresh()
    page._wait_loaded(15)


def forum_from_link(link: Any) -> Forum | None:
    try:
        href = link.attr("href") or ""
    except Exception:
        return None
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    elif href.startswith("/"):
        href = BASE_TIEBA_URL + href
    match = re.search(r"[?&]kw=([^&]+)", href)
    title = ""
    try:
        title = str(link.attr("title") or "").strip()
    except Exception:
        title = ""
    text = safe_text(link)
    name = title or (decode_forum_name(match.group(1)) if match else "") or text
    name = name.replace("吧", "").strip() if name.endswith("吧") else name.strip()
    if not name or "javascript:" in href:
        return None
    return Forum(name=name, url=href)


def parse_forums_from_html(html: str) -> list[Forum]:
    soup = BeautifulSoup(html, "html.parser")
    forums: list[Forum] = []
    seen: set[str] = set()
    selectors = [
        '#like_pagelet a[href*="/f?kw="]',
        '#like_pagelet a[href*="kw="]',
        'a[href*="/f?kw="]',
    ]
    for selector in selectors:
        for link in soup.select(selector):
            href = link.get("href") or ""
            if "kw=" not in href:
                continue
            if href.startswith("//"):
                href = "https:" + href
            elif href.startswith("/"):
                href = BASE_TIEBA_URL + href
            match = re.search(r"[?&]kw=([^&]+)", href)
            title = (link.get("title") or "").strip()
            text = link.get_text(" ", strip=True)
            name = title or (decode_forum_name(match.group(1)) if match else "") or text
            name = name.replace("吧", "").strip() if name.endswith("吧") else name.strip()
            if name and name not in seen:
                seen.add(name)
                forums.append(Forum(name=name, url=href))
    return forums


def collect_followed_forums(page: Any) -> list[Forum]:
    max_pages = env_int("TIEBA_MAX_PAGES", 50, minimum=1)
    max_forums = env_int("TIEBA_MAX_FORUMS", 0, minimum=0)
    empty_pages_to_stop = env_int("TIEBA_EMPTY_PAGES_TO_STOP", 2, minimum=1)
    forums: list[Forum] = []
    seen: set[str] = set()
    empty_pages = 0

    for page_number in range(1, max_pages + 1):
        progress(f"Scanning followed forum page {page_number}/{max_pages}...")
        page.get(f"{BASE_TIEBA_URL}/i/i/forum?&pn={page_number}")
        page._wait_loaded(15)
        page_forums = parse_forums_from_html(page_html(page))
        progress(f"Page {page_number} found {len(page_forums)} forum link(s).")

        if not page_forums:
            empty_pages += 1
            if empty_pages >= empty_pages_to_stop:
                break
            continue
        empty_pages = 0

        for forum in page_forums:
            if forum.name not in seen:
                seen.add(forum.name)
                forums.append(forum)
                if max_forums and len(forums) >= max_forums:
                    progress(f"Reached TIEBA_MAX_FORUMS={max_forums}.")
                    return forums
        sleep_between_actions()
    return forums


def already_signed(page: Any) -> bool:
    html = page_html(page)
    if any(marker in html for marker in ("已签到", "连续签到", "签到排名")):
        return True
    for xpath in (
        'xpath://*[@id="signstar_wrapper"]/a/span[1]',
        'xpath://span[contains(text(), "连续")]',
        'xpath://span[contains(text(), "已签到")]',
    ):
        try:
            element = page.ele(xpath, timeout=2)
        except Exception:
            element = None
        text = safe_text(element)
        if text.startswith("连续") or "已签到" in text:
            return True
    return False


def find_sign_button(page: Any) -> Any | None:
    selectors = (
        'xpath://a[contains(@class, "j_signbtn") and not(contains(@class, "sign_btn_signed"))]',
        'xpath://a[contains(@class, "sign_btn_bright")]',
        'xpath://a[contains(@class, "j_cansign")]',
        'xpath://*[@id="signstar_wrapper"]//a[contains(@class, "sign")]',
        'xpath://a[contains(text(), "签到")]',
        'xpath://span[contains(text(), "签到")]/parent::a',
    )
    for selector in selectors:
        try:
            element = page.ele(selector, timeout=5)
        except Exception:
            element = None
        if element:
            return element
    return None


def sign_one_forum(page: Any, forum: Forum) -> SignResult:
    retries = env_int("TIEBA_SIGN_RETRIES", 2, minimum=1)
    for attempt in range(1, retries + 1):
        progress(f"Signing {forum.name} (attempt {attempt}/{retries})...")
        page.get(f"{BASE_TIEBA_URL}/f?kw={quote(forum.name)}")
        page._wait_loaded(15)
        time.sleep(1.2)

        if already_signed(page):
            return SignResult(forum.name, True, "already signed")

        button = find_sign_button(page)
        if button:
            try:
                button.click()
                time.sleep(2.5)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
                page.refresh()
                page._wait_loaded(10)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
            except Exception as exc:
                last_message = f"click failed: {exc}"
            else:
                last_message = "clicked but sign state was not confirmed"
        else:
            last_message = "sign button not found"

        if attempt < retries:
            sleep_between_actions()
    return SignResult(forum.name, False, last_message)


def sign_account(label: str, cookies: list[dict[str, Any]]) -> AccountResult:
    page = None
    details: list[str] = []
    try:
        page = create_page()
        progress(f"Injecting cookies for {label}...")
        inject_cookies(page, cookies)
        if not is_logged_in(page):
            details.append("Cookie was injected, but Tieba still looks logged out.")

        forums = collect_followed_forums(page)
        details.append(f"Found {len(forums)} followed forum(s).")
        if not forums:
            return AccountResult(label, False, "no followed forums found", details)

        signed = 0
        already = 0
        failed = 0
        for index, forum in enumerate(forums, start=1):
            progress(f"Progress {index}/{len(forums)}: {forum.name}")
            result = sign_one_forum(page, forum)
            if result.ok and result.message == "already signed":
                already += 1
            elif result.ok:
                signed += 1
            else:
                failed += 1
            details.append(
                f"{'OK' if result.ok else 'FAIL'} {result.forum}: {result.message}"
            )
            if index < len(forums):
                sleep_between_actions()

        ok = failed == 0
        return AccountResult(
            label,
            ok,
            f"signed {signed}, already signed {already}, failed {failed}, total {len(forums)}",
            details,
        )
    except Exception as exc:
        return AccountResult(label, False, f"browser run failed: {exc}", details)
    finally:
        if page is not None:
            try:
                page.close()
            except Exception:
                pass


def result_to_markdown(results: list[AccountResult]) -> str:
    lines = ["# Baidu Tieba sign-in summary", ""]
    for result in results:
        status = "OK" if result.ok else "FAIL"
        lines.append(f"- **{result.label}**: {status} - {result.message}")
        for detail in result.details:
            lines.append(f"  - {detail}")
    return "\n".join(lines) + "\n"


def write_github_summary(markdown: str) -> None:
    path = os.getenv("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as summary:
        summary.write(markdown)


def main() -> int:
    try:
        accounts = load_accounts()
    except TiebaError as exc:
        result = AccountResult("runtime", False, str(exc))
        markdown = result_to_markdown([result])
        print(markdown)
        write_github_summary(markdown)
        return 1

    progress(f"Loaded {len(accounts)} account(s).")
    results = []
    for label, cookies in accounts:
        progress(f"Starting {label}.")
        results.append(sign_account(label, cookies))

    markdown = result_to_markdown(results)
    print(markdown)
    write_github_summary(markdown)
    return 0 if all(result.ok for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
