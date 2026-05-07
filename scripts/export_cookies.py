from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    try:
        from DrissionPage import ChromiumPage
    except ImportError as exc:
        raise RuntimeError("Please install dependencies first: pip install -r requirements.txt") from exc

    page = ChromiumPage()
    page.get("https://tieba.baidu.com/")
    input("请在打开的浏览器里登录百度贴吧，登录完成后回到这里按回车...")
    cookies = page.cookies(all_info=True)
    output = Path("tieba_cookies.json")
    output.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 {len(cookies)} 条 cookie 到 {output.resolve()}")
    print("请把整个 JSON 文件内容复制到私有 Action 仓库的 TIEBA_COOKIES Secret。")
    page.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
