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
from pathlib import Path
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
NEXT_PAGE_TEXT = "\u4e0b\u4e00\u9875"
SIGNED_CLASS_MARKERS = ("signstar_signed", "sign_box_bright_signed", "sign_btn_signed")
DIAGNOSTICS_DIR = os.getenv("TIEBA_DIAGNOSTICS_DIR", "tieba_diagnostics")
DEFAULT_FOLLOWED_FORUM_WAIT_SECONDS = 15
SECURITY_MARKERS = (
    "\u767e\u5ea6\u5b89\u5168\u9a8c\u8bc1",
    "\u5b89\u5168\u9a8c\u8bc1",
    "\u9a8c\u8bc1\u7801",
    "\u8bf7\u8f93\u5165\u9a8c\u8bc1\u7801",
    "wappass.baidu.com",
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


def cookie_login_hint(cookies: list[dict[str, Any]]) -> str:
    names = {str(cookie.get("name") or "") for cookie in cookies}
    if not ({"BDUSS", "BDUSS_BFESS"} & names):
        return (
            "Cookie JSON is missing BDUSS/BDUSS_BFESS; export cookies again from a "
            "browser that is already logged in to Baidu Tieba."
        )
    return (
        "The cookie names look like login cookies, but Baidu rejected this session; "
        "refresh TIEBA_COOKIES from the currently logged-in browser."
    )


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


def close_known_popups(page: Any) -> bool:
    script = r'''
(() => {
  const labels = ['\u6211\u77e5\u9053\u4e86', '\u786e\u5b9a', '\u5173\u95ed'];
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  let clicked = false;
  for (const el of [...document.querySelectorAll('a, button, span, div')]) {
    const text = (el.innerText || el.textContent || '').trim();
    if (!visible(el) || !labels.some(label => text.includes(label))) continue;
    el.scrollIntoView({block: 'center', inline: 'center'});
    for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {
      el.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
    }
    clicked = true;
    break;
  }
  return clicked;
})()
'''
    try:
        clicked = bool(page.run_js(script))
    except Exception:
        clicked = False
    if clicked:
        time.sleep(0.8)
    return clicked


def wait_for_followed_forum_content(page: Any, timeout: int | None = None) -> str:
    timeout = timeout or env_int(
        "TIEBA_FOLLOWED_WAIT_SECONDS",
        DEFAULT_FOLLOWED_FORUM_WAIT_SECONDS,
        minimum=1,
    )
    deadline = time.time() + timeout
    last_html = page_html(page)
    while time.time() < deadline:
        close_known_popups(page)
        last_html = page_html(page)
        if parse_forums_from_html(last_html):
            return last_html
        if not has_followed_forum_list(last_html):
            return last_html
        time.sleep(1)
    return last_html


def page_url(page: Any) -> str:
    url = getattr(page, "url", "")
    return str(url() if callable(url) else url or "")


def page_title(page: Any) -> str:
    title = getattr(page, "title", "")
    try:
        return str(title() if callable(title) else title or "").strip()
    except Exception:
        return ""


def diagnostic_slug(value: str, limit: int = 80) -> str:
    slug = re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("._-")
    return (slug or "page")[:limit]


def detect_page_issue(page: Any, html: str | None = None) -> str:
    html = page_html(page) if html is None else html
    haystack = "\n".join((page_url(page), page_title(page), html))
    if not is_logged_in_html(html):
        return "page shows logged-out state"
    if any(marker in haystack for marker in SECURITY_MARKERS):
        return "possible security verification or login challenge"
    return "no obvious challenge marker"


def page_text_excerpt(html: str, limit: int = 1000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(("script", "style", "noscript")):
        node.decompose()
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def page_diagnostic_line(page: Any, html: str | None = None, limit: int = 1000) -> str:
    html = page_html(page) if html is None else html
    return (
        f"diagnosis={detect_page_issue(page, html)}; "
        f"url={page_url(page)}; "
        f"title={page_title(page)}; "
        f"text={page_text_excerpt(html, limit)}"
    )


def save_diagnostic(page: Any, label: str, html: str | None = None) -> None:
    if not env_bool("TIEBA_SAVE_DIAGNOSTICS", True):
        return
    html = page_html(page) if html is None else html
    directory = Path(DIAGNOSTICS_DIR)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        name = diagnostic_slug(label)
        (directory / f"{name}.html").write_text(html, encoding="utf-8", errors="ignore")
        diagnostic_text = (
            f"url={page_url(page)}\n"
            f"title={page_title(page)}\n"
            f"diagnosis={detect_page_issue(page, html)}\n"
            f"text={page_text_excerpt(html, 3000)}\n"
        )
        (directory / f"{name}.txt").write_text(diagnostic_text, encoding="utf-8")
        try:
            page.get_screenshot(path=str(directory), name=f"{name}.png", full_page=True)
        except Exception as exc:
            progress(f"Could not save screenshot for {label}: {exc}")
    except Exception as exc:
        progress(f"Could not save diagnostic for {label}: {exc}")


def safe_text(element: Any) -> str:
    if not element:
        return ""
    try:
        return str(element.text or "").strip()
    except Exception:
        return ""


def safe_attr(element: Any, name: str) -> str:
    if not element:
        return ""
    try:
        return str(element.attr(name) or "")
    except Exception:
        return ""


def text_indicates_signed(text: str) -> bool:
    return (
        SIGNED_TEXT in text
        or CONTINUOUS_SIGN_TEXT in text
        or STREAK_SIGN_TEXT in text
        or "already signed" in text.lower()
    )


def class_indicates_signed(class_name: str) -> bool:
    return any(marker in class_name for marker in SIGNED_CLASS_MARKERS)


def html_indicates_signed(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")

    old_widget = soup.select_one("#signstar_wrapper")
    if old_widget:
        old_classes = " ".join(old_widget.get("class", []))
        old_text = old_widget.get_text(" ", strip=True)
        if class_indicates_signed(old_classes) or text_indicates_signed(old_text):
            return True
        sign_link = old_widget.select_one("a")
        if sign_link:
            link_classes = " ".join(sign_link.get("class", []))
            link_text = sign_link.get_text(" ", strip=True)
            if class_indicates_signed(link_classes) or text_indicates_signed(link_text):
                return True

    for element in soup.select(".follow-sign, .operate-btn"):
        text = element.get_text(" ", strip=True)
        if STREAK_SIGN_TEXT in text or SIGNED_TEXT in text:
            return True

    return False


def is_logged_in_html(html: str) -> bool:
    logged_out_markers = ("登录百度账号", "立即登录", "name=\"userName\"")
    logged_in_markers = ("我的贴吧", "退出", "个人中心", "i/i/forum")
    return any(marker in html for marker in logged_in_markers) and not any(
        marker in html for marker in logged_out_markers
    )


def is_logged_in(page: Any) -> bool:
    return is_logged_in_html(page_html(page))


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


def has_followed_forum_list(html: str) -> bool:
    return BeautifulSoup(html, "html.parser").select_one("#like_pagelet") is not None


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
    script = r'''
(() => {
  const labels = ['\u65e7\u7248', '\u8001\u7248', '\u8fd4\u56de\u65e7\u7248'];
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const byIcon = [...document.querySelectorAll('use')]
    .find(el => (el.getAttribute('href') || el.getAttribute('xlink:href') || '') === '#back_old');
  const iconTarget = byIcon ? byIcon.closest('.menu-item, button, a, [role="button"], div') : null;
  const byText = [...document.querySelectorAll('a, button, [role="button"], span, div')]
    .find(el => visible(el) && labels.some(label => (el.innerText || el.textContent || '').includes(label)));
  const target = iconTarget || (byText ? byText.closest('a, button, [role="button"]') || byText : null);
  if (!target || !visible(target)) return false;
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
        return True

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
    return False


def open_followed_forum_index(page: Any) -> str:
    open_page(page, FOLLOWED_FORUM_URL, timeout=20, wait=8)
    html = wait_for_followed_forum_content(page)
    if has_followed_forum_list(html):
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
    open_page(page, FOLLOWED_FORUM_URL, timeout=20, wait=8)
    html = wait_for_followed_forum_content(page)
    if not has_followed_forum_list(html):
        progress("Followed forum list is still not visible after opening the old followed-forum URL.")
    return html


def click_followed_forum_pagination(page: Any, page_number: int | None = None, text: str = "") -> bool:
    page_number_js = "null" if page_number is None else str(page_number)
    text_js = json.dumps(text, ensure_ascii=False)
    script = f'''
(() => {{
  const pageNumber = {page_number_js};
  const text = {text_js};
  const pagelet = document.querySelector('#like_pagelet');
  if (!pagelet) return false;
  const links = [...pagelet.querySelectorAll('a[href*="pn="]')];
  const target = links.find(link => {{
    const href = link.getAttribute('href') || '';
    const label = (link.innerText || link.textContent || '').trim();
    const match = href.match(/[?&]pn=(\\d+)/);
    if (pageNumber !== null && match && Number(match[1]) === pageNumber) return true;
    return text && label.includes(text);
  }});
  if (!target) return false;
  target.scrollIntoView({{block: 'center', inline: 'center'}});
  for (const type of ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click']) {{
    target.dispatchEvent(new MouseEvent(type, {{bubbles: true, cancelable: true, view: window}}));
  }}
  return true;
}})()
'''
    try:
        clicked = bool(page.run_js(script))
    except Exception:
        clicked = False
    if not clicked:
        return False
    time.sleep(1.5)
    try:
        page._wait_loaded(8)
    except Exception:
        pass
    html = wait_for_followed_forum_content(page)
    return has_followed_forum_list(html)


def verify_followed_forum_tail_page(page: Any, reported_pages: int) -> int:
    progress("Clicking tail page to verify followed forum page count...")
    if not click_followed_forum_pagination(page, text=TAIL_PAGE_TEXT):
        progress("Could not click the tail-page link; using the page count parsed from page 1.")
        return reported_pages
    html = page_html(page)
    verified_pages = parse_pn_from_url(page_url(page)) or reported_pages
    pagination = parse_followed_forum_pagination(html)
    if pagination:
        verified_pages = max(verified_pages, int(pagination["total_pages"]))
    page_forums = parse_forums_from_html(html)
    progress(f"Tail page verified as page {verified_pages}; it contains {len(page_forums)} forum link(s).")
    return max(1, verified_pages)


def open_next_followed_forum_page(page: Any, page_number: int) -> str:
    progress(f"Clicking followed forum pagination to page {page_number}...")
    if click_followed_forum_pagination(page, page_number=page_number):
        return wait_for_followed_forum_content(page)
    if click_followed_forum_pagination(page, text=NEXT_PAGE_TEXT):
        return wait_for_followed_forum_content(page)
    progress(f"Could not click page {page_number}; falling back to the old followed-forum URL.")
    open_page(page, f"{FOLLOWED_FORUM_URL}?&pn={page_number}", timeout=20, wait=8)
    return wait_for_followed_forum_content(page)


def collect_followed_forums(page: Any) -> list[Forum]:
    max_pages = env_int("TIEBA_MAX_PAGES", 100, minimum=1)
    max_forums = env_int("TIEBA_MAX_FORUMS", 0, minimum=0)
    empty_pages_to_stop = env_int("TIEBA_EMPTY_PAGES_TO_STOP", 1, minimum=1)
    page_retries = env_int("TIEBA_PAGE_RETRIES", 2, minimum=0)
    forums: list[Forum] = []
    seen: set[str] = set()
    empty_pages = 0
    page_number = 1
    scan_pages = max_pages
    pagination_known = False

    html = open_followed_forum_index(page)
    pagination = parse_followed_forum_pagination(html)
    if pagination:
        pagination_known = True
        total_pages = int(pagination["total_pages"])
        if str(pagination["tail_url"]) and total_pages > 1:
            total_pages = verify_followed_forum_tail_page(page, total_pages)
            html = open_followed_forum_index(page)
        scan_pages = min(max_pages, total_pages)
        progress(f"Followed forum list reports {total_pages} page(s); scanning {scan_pages}.")
    else:
        progress(f"Could not read followed forum pagination; scanning up to {scan_pages} page(s).")

    while page_number <= scan_pages:
        progress(f"Scanning followed forum page {page_number}/{scan_pages}...")
        page_forums = parse_forums_from_html(html)
        progress(f"Page {page_number} found {len(page_forums)} forum link(s).")

        if not page_forums:
            progress(
                f"Followed forum page {page_number} was empty; "
                f"{page_diagnostic_line(page, html)}"
            )
            save_diagnostic(page, f"followed-page-{page_number}-empty", html)
            for retry in range(1, page_retries + 1):
                progress(f"Retrying followed forum page {page_number} ({retry}/{page_retries})...")
                sleep_between_actions()
                open_page(page, f"{FOLLOWED_FORUM_URL}?&pn={page_number}", timeout=20, wait=8)
                html = wait_for_followed_forum_content(page)
                page_forums = parse_forums_from_html(html)
                progress(f"Page {page_number} retry {retry} found {len(page_forums)} forum link(s).")
                if page_forums:
                    break
                save_diagnostic(page, f"followed-page-{page_number}-empty-retry-{retry}", html)

        if not page_forums:
            empty_pages += 1
            if not pagination_known and empty_pages >= empty_pages_to_stop:
                progress(f"Stopping forum scan after {empty_pages} empty page(s).")
                break
            page_number += 1
            if page_number <= scan_pages:
                sleep_between_actions()
                html = open_next_followed_forum_page(page, page_number)
            continue
        empty_pages = 0

        for forum in page_forums:
            if forum.name not in seen:
                seen.add(forum.name)
                forums.append(forum)
                if max_forums and len(forums) >= max_forums:
                    progress(f"Reached TIEBA_MAX_FORUMS={max_forums}.")
                    return forums
        page_number += 1
        if page_number <= scan_pages:
            sleep_between_actions()
            html = open_next_followed_forum_page(page, page_number)
    return forums


def already_signed(page: Any) -> bool:
    html = page_html(page)
    if html_indicates_signed(html):
        return True
    for selector in (
        "css:#signstar_wrapper",
        'css:.follow-sign',
        "css:.operate-btn",
    ):
        try:
            element = page.ele(selector, timeout=1)
        except Exception:
            element = None
        text = safe_text(element)
        class_name = safe_attr(element, "class")
        if class_indicates_signed(class_name) or text_indicates_signed(text):
            return True
    return False


def detect_forum_ui(page: Any) -> str:
    html = page_html(page)
    if "follow-sign" in html or "operate-btn" in html:
        return "new"
    if "signstar_wrapper" in html or "j_signbtn" in html or "j_cansign" in html:
        return "old"
    for selector, ui_name in (
        ("css:.follow-sign", "new"),
        ("css:.operate-btn", "new"),
        ("css:#signstar_wrapper", "old"),
        ("css:.j_signbtn", "old"),
    ):
        try:
            if page.ele(selector, timeout=1):
                return ui_name
        except Exception:
            continue
    return "unknown"


def find_old_ui_sign_button(page: Any) -> Any | None:
    class_selectors = (
        'xpath://a[contains(@class, "j_signbtn") and not(contains(@class, "sign_btn_signed"))]',
        'xpath://a[contains(@class, "sign_btn_bright")]',
        'xpath://a[contains(@class, "j_cansign")]',
        'xpath://*[@id="signstar_wrapper"]//a[contains(@class, "sign")]',
    )
    for selector in class_selectors:
        try:
            element = page.ele(selector, timeout=2)
        except Exception:
            element = None
        class_name = safe_attr(element, "class")
        text = safe_text(element)
        if not element:
            continue
        if class_indicates_signed(class_name):
            continue
        if text_indicates_signed(text):
            continue
        return element

    text_selectors = (
        f'xpath://a[contains(text(), "{SIGN_TEXT}")]',
    )
    for selector in text_selectors:
        try:
            element = page.ele(selector, timeout=2)
        except Exception:
            element = None
        text = safe_text(element)
        if element and SIGN_TEXT in text and not text_indicates_signed(text):
            return element
    return None


def find_new_ui_sign_button(page: Any) -> Any | None:
    selectors = (
        "css:.follow-sign",
        f'xpath://div[contains(text(), "{SIGN_TEXT}")]/ancestor::*[contains(@class, "operate-btn")][1]',
        f'xpath://span[contains(text(), "{SIGN_TEXT}")]/ancestor::*[contains(@class, "operate-btn")][1]',
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
            target_url = f"{BASE_TIEBA_URL}/f?kw={quote(forum.name)}&ie=utf-8"
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

        ui = detect_forum_ui(page)
        progress(f"{forum.name} forum page UI detected: {ui}.")
        if ui == "unknown":
            html = page_html(page)
            progress(
                f"{forum.name} unknown page diagnostic: "
                f"{page_diagnostic_line(page, html)}"
            )
            save_diagnostic(page, f"forum-{forum.name}-unknown-attempt-{attempt}", html)
            progress(f"{forum.name} page was unknown; trying to switch this forum page to the old UI.")
            if click_old_version_switch(page):
                time.sleep(1.5)
                ui = detect_forum_ui(page)
                progress(f"{forum.name} forum page UI after old-version switch: {ui}.")

        if ui == "new":
            button = find_new_ui_sign_button(page)
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
                    last_message = f"new UI click failed: {exc}"
                else:
                    last_message = "new UI clicked but sign state was not confirmed"
            elif click_new_ui_sign_button(page):
                time.sleep(2.5)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
                last_message = "new UI sign click was sent but sign state was not confirmed"
            else:
                last_message = "new UI sign button not found"
        elif ui == "old":
            button = find_old_ui_sign_button(page)
            if not button:
                last_message = "old UI sign button not found"
            else:
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
                    last_message = f"old UI click failed: {exc}"
                else:
                    last_message = "old UI clicked but sign state was not confirmed"
        else:
            diagnosis = page_diagnostic_line(page)
            button = find_new_ui_sign_button(page) or find_old_ui_sign_button(page)
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
                    last_message = f"unknown UI click failed: {exc}"
                else:
                    last_message = "unknown UI clicked but sign state was not confirmed"
            elif click_new_ui_sign_button(page):
                time.sleep(2.5)
                if already_signed(page):
                    return SignResult(forum.name, True, "signed")
                last_message = "unknown UI fallback click was sent but sign state was not confirmed"
            else:
                last_message = f"forum UI and sign button not found; {diagnosis}"

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
            home_html = page_html(page)
            progress(f"{label} homepage login diagnostic: {page_diagnostic_line(page, home_html)}")
            save_diagnostic(page, f"{label}-homepage-not-logged-in", home_html)
            progress("Homepage looked logged out; checking the old followed-forum page before failing.")
            followed_html = open_followed_forum_index(page)
            if not has_followed_forum_list(followed_html):
                diagnostic = page_diagnostic_line(page, followed_html)
                progress(f"{label} followed-forum login diagnostic: {diagnostic}")
                save_diagnostic(page, f"{label}-followed-forum-not-logged-in", followed_html)
                details.append("Cookie was injected, but Tieba still looks logged out.")
                details.append(cookie_login_hint(cookies))
                details.append(diagnostic)
                return AccountResult(label, False, "not logged in after cookie injection", details)
            progress("Old followed-forum page is visible; continuing despite the new homepage login state.")

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
            progress(f"{'OK' if result.ok else 'FAIL'} {result.forum}: {result.message}")
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
