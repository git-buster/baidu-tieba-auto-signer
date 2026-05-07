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
FOLLOWED_FORUM_PATH = "/i/i/forum"
FOLLOWED_FORUM_URL = f"{BASE_TIEBA_URL}{FOLLOWED_FORUM_PATH}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SIGN_TEXT = "\u7b7e\u5230"
SIGNED_TEXT = "\u5df2\u7b7e\u5230"
CONTINUOUS_SIGN_TEXT = "\u8fde\u7eed"
STREAK_SIGN_TEXT = "\u8fde\u7b7e"
OLD_VERSION_TEXTS = ("\u65e7\u7248", "\u8001\u7248", "\u8fd4\u56de\u65e7\u7248")
TAIL_PAGE_TEXT = "\u5c3e\u9875"


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


def parse_interval(value: str, default: str = "2-4") -> tuple[float, float]:
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
    start, end = parse_interval(os.getenv("TIEBA_INTERVAL_SECONDS", "2-4"))
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
    raw = raw.strip()
    if not raw:
        return []
    try:
        json.loads(raw)
    except json.JSONDecodeError:
        return [part.strip() for part in re.split(r"#{3,}", raw) if part.strip()]
    return [raw]


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


def ensure_local_browser_proxy_bypass() -> None:
    bypass = "localhost,127.0.0.1,::1"
    for name in ("NO_PROXY", "no_proxy"):
        current = os.getenv(name, "")
        parts = [part.strip() for part in current.split(",") if part.strip()]
        for host in bypass.split(","):
            if host not in parts:
                parts.append(host)
        os.environ[name] = ",".join(parts)


def create_page() -> Any:
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage
    except ImportError as exc:
        raise TiebaError("DrissionPage is not installed.") from exc

    ensure_local_browser_proxy_bypass()
    user_data_dir = tempfile.mkdtemp(prefix="tieba-browser-")
    port = random.randint(9300, 9999)
    options = ChromiumOptions()
    options.headless(True)
    options.set_load_mode("eager")
    options.set_timeouts(base=8, page_load=20, script=8)
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


def open_page(page: Any, url: str, timeout: int = 20, wait: int = 8) -> None:
    page.get(url, retry=1, interval=1, timeout=timeout)
    page._wait_loaded(wait)


def page_url(page: Any) -> str:
    url = getattr(page, "url", "")
    return str(url() if callable(url) else url or "")


def safe_text(element: Any) -> str:
    if not element:
        return ""
    try:
        return str(element.text or "").strip()
    except Exception:
        return ""


def text_indicates_signed(text: str) -> bool:
    return (
        SIGNED_TEXT in text
        or CONTINUOUS_SIGN_TEXT in text
        or STREAK_SIGN_TEXT in text
        or "already signed" in text.lower()
    )


def is_logged_in(page: Any) -> bool:
    html = page_html(page)
    logged_out_markers = ("登录百度账号", "立即登录", "name=\"userName\"")
    logged_in_markers = ("我的贴吧", "退出", "个人中心", "i/i/forum")
    return any(marker in html for marker in logged_in_markers) and not any(
        marker in html for marker in logged_out_markers
    )


def inject_cookies(page: Any, cookies: list[dict[str, Any]]) -> None:
    open_page(page, BASE_TIEBA_URL, timeout=20, wait=8)
    page.set.cookies(cookies)
    page.refresh()
    page._wait_loaded(8)


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
    pagelet = soup.select_one("#like_pagelet")
    if not pagelet:
        return forums

    rows = pagelet.select("table tbody tr")
    candidates = []
    if rows:
        for row in rows:
            link = row.select_one('td a[href*="/f?kw="], td a[href*="kw="]')
            if link:
                candidates.append(link)
    else:
        candidates = pagelet.select('a[href*="/f?kw="], a[href*="kw="]')

    for link in candidates:
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


def parse_followed_forum_total_pages(html: str) -> int | None:
    info = parse_followed_forum_pagination(html)
    if info is None:
        return None
    return info["total_pages"]


def normalize_tieba_url(href: str) -> str:
    href = href.strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return BASE_TIEBA_URL + href
    return href


def parse_pn_from_url(url: str) -> int | None:
    match = re.search(r"[?&]pn=(\d+)", url)
    return int(match.group(1)) if match else None


def parse_followed_forum_pagination(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "html.parser")
    pagelet = soup.select_one("#like_pagelet")
    if not pagelet:
        return None

    pages: list[int] = []
    tail_url = ""
    for link in pagelet.select('a[href*="pn="]'):
        href = link.get("href") or ""
        page_number = parse_pn_from_url(href)
        if page_number:
            pages.append(page_number)
        if TAIL_PAGE_TEXT in link.get_text(" ", strip=True) and href:
            tail_url = normalize_tieba_url(href)

    total_pages = max(pages) if pages else 1
    if not tail_url and pages:
        for link in pagelet.select('a[href*="pn="]'):
            href = link.get("href") or ""
            if parse_pn_from_url(href) == total_pages:
                tail_url = normalize_tieba_url(href)
                break
    return {"total_pages": total_pages, "tail_url": tail_url}


def click_old_version_switch(page: Any) -> bool:
    for text in OLD_VERSION_TEXTS:
        for selector in (
            f'xpath://a[contains(text(), "{text}")]',
            f'xpath://button[contains(text(), "{text}")]',
            f'xpath://*[contains(text(), "{text}") and (@role="button" or contains(@class, "button"))]',
        ):
            try:
                element = page.ele(selector, timeout=1)
            except Exception:
                element = None
            if element:
                try:
                    element.click()
                    time.sleep(1.5)
                    return True
                except Exception:
                    continue

    script = r'''
(() => {
  const labels = ['\u65e7\u7248', '\u8001\u7248', '\u8fd4\u56de\u65e7\u7248'];
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const nodes = [...document.querySelectorAll('a, button, [role="button"], span, div')]
    .filter(el => visible(el) && labels.some(label => (el.innerText || el.textContent || '').includes(label)));
  const node = nodes[0];
  if (!node) return false;
  const target = node.closest('a, button, [role="button"]') || node;
  target.scrollIntoView({block: 'center', inline: 'center'});
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
    target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
  }
  return true;
})()
'''
    try:
        clicked = bool(page.run_js(script))
    except Exception:
        clicked = False
    if clicked:
        time.sleep(1.5)
    return clicked


def open_followed_forum_page(page: Any, page_number: int) -> str:
    target_url = f"{FOLLOWED_FORUM_URL}?&pn={page_number}"
    open_page(page, target_url, timeout=20, wait=8)
    html = page_html(page)
    if BeautifulSoup(html, "html.parser").select_one("#like_pagelet"):
        return html

    progress("Old followed-forum list was not visible; trying to switch from the new Tieba UI.")
    try:
        open_page(page, BASE_TIEBA_URL, timeout=20, wait=8)
    except Exception:
        pass
    if click_old_version_switch(page):
        progress("Clicked old-version switch; reopening followed-forum list.")
    else:
        progress("Old-version switch was not found; reopening the old followed-forum URL directly.")
    open_page(page, target_url, timeout=20, wait=8)
    return page_html(page)


def verify_followed_forum_tail_page(page: Any, tail_url: str, reported_pages: int) -> int:
    if not tail_url:
        return reported_pages
    progress(f"Opening tail page to verify followed forum page count: {tail_url}")
    open_page(page, tail_url, timeout=20, wait=8)
    html = page_html(page)
    verified_pages = parse_pn_from_url(page_url(page)) or parse_pn_from_url(tail_url) or reported_pages
    pagination = parse_followed_forum_pagination(html)
    if pagination:
        verified_pages = max(verified_pages, int(pagination["total_pages"]))
    page_forums = parse_forums_from_html(html)
    progress(f"Tail page verified as page {verified_pages}; it contains {len(page_forums)} forum link(s).")
    return max(1, verified_pages)


def collect_followed_forums(page: Any) -> list[Forum]:
    max_pages = env_int("TIEBA_MAX_PAGES", 100, minimum=1)
    max_forums = env_int("TIEBA_MAX_FORUMS", 0, minimum=0)
    empty_pages_to_stop = env_int("TIEBA_EMPTY_PAGES_TO_STOP", 1, minimum=1)
    forums: list[Forum] = []
    seen: set[str] = set()
    empty_pages = 0
    page_number = 1
    scan_pages = max_pages

    while page_number <= scan_pages:
        progress(f"Scanning followed forum page {page_number}/{scan_pages}...")
        html = open_followed_forum_page(page, page_number)
        if page_number == 1:
            pagination = parse_followed_forum_pagination(html)
            if pagination:
                total_pages = int(pagination["total_pages"])
                tail_url = str(pagination["tail_url"])
                if tail_url and total_pages > 1:
                    total_pages = verify_followed_forum_tail_page(page, tail_url, total_pages)
                scan_pages = min(max_pages, total_pages)
                progress(f"Followed forum list reports {total_pages} page(s); scanning {scan_pages}.")
            else:
                progress(f"Could not read followed forum pagination; scanning up to {scan_pages} page(s).")
        page_forums = parse_forums_from_html(html)
        progress(f"Page {page_number} found {len(page_forums)} forum link(s).")

        if not page_forums:
            empty_pages += 1
            if empty_pages >= empty_pages_to_stop:
                progress(f"Stopping forum scan after {empty_pages} empty page(s).")
                break
            page_number += 1
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
        page_number += 1
    return forums


def already_signed(page: Any) -> bool:
    html = page_html(page)
    if text_indicates_signed(html) or "\u7b7e\u5230\u6392\u540d" in html:
        return True
    for xpath in (
        'xpath://*[@id="signstar_wrapper"]/a/span[1]',
        f'xpath://span[contains(text(), "{CONTINUOUS_SIGN_TEXT}")]',
        f'xpath://span[contains(text(), "{STREAK_SIGN_TEXT}")]',
        f'xpath://span[contains(text(), "{SIGNED_TEXT}")]',
        'css:.follow-sign',
    ):
        try:
            element = page.ele(xpath, timeout=1)
        except Exception:
            element = None
        text = safe_text(element)
        if text_indicates_signed(text):
            return True
    return False


def find_sign_button(page: Any) -> Any | None:
    selectors = (
        "css:.follow-sign",
        'xpath://a[contains(@class, "j_signbtn") and not(contains(@class, "sign_btn_signed"))]',
        'xpath://a[contains(@class, "sign_btn_bright")]',
        'xpath://a[contains(@class, "j_cansign")]',
        'xpath://*[@id="signstar_wrapper"]//a[contains(@class, "sign")]',
        f'xpath://a[contains(text(), "{SIGN_TEXT}")]',
        f'xpath://span[contains(text(), "{SIGN_TEXT}")]/parent::a',
        f'xpath://div[contains(text(), "{SIGN_TEXT}")]/ancestor::*[contains(@class, "operate-btn")][1]',
    )
    for selector in selectors:
        try:
            element = page.ele(selector, timeout=2)
        except Exception:
            element = None
        if element and SIGN_TEXT in safe_text(element) and not text_indicates_signed(safe_text(element)):
            return element
    return None


def click_new_ui_sign_button(page: Any) -> bool:
    script = r'''
(() => {
  const signText = '\u7b7e\u5230';
  const signedWords = ['\u5df2\u7b7e\u5230', '\u8fde\u7eed', '\u8fde\u7b7e'];
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const candidates = [...document.querySelectorAll('.follow-sign, .operate-btn, .button-wrapper')]
    .filter(el => visible(el) && (el.innerText || '').includes(signText))
    .filter(el => !signedWords.some(word => (el.innerText || '').includes(word)));
  const button = candidates[0];
  if (!button) return false;
  button.scrollIntoView({block: 'center', inline: 'center'});
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
    button.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
  }
  return true;
})()
'''
    try:
        return bool(page.run_js(script))
    except Exception:
        return False


def sign_one_forum(page: Any, forum: Forum) -> SignResult:
    retries = env_int("TIEBA_SIGN_RETRIES", 2, minimum=1)
    for attempt in range(1, retries + 1):
        progress(f"Signing {forum.name} (attempt {attempt}/{retries})...")
        try:
            target_url = forum.url or f"{BASE_TIEBA_URL}/f?kw={quote(forum.name)}"
            open_page(page, target_url, timeout=20, wait=8)
        except Exception as exc:
            last_message = f"page load failed: {exc}"
            if attempt < retries:
                sleep_between_actions()
                continue
            return SignResult(forum.name, False, last_message)
        time.sleep(0.8)

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
                page._wait_loaded(8)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
            except Exception as exc:
                last_message = f"click failed: {exc}"
            else:
                last_message = "clicked but sign state was not confirmed"
        else:
            if click_new_ui_sign_button(page):
                time.sleep(2.5)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
                last_message = "new UI sign click was sent but sign state was not confirmed"
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
