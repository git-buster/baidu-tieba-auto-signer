from scripts.tieba_signer import (
    decode_forum_name,
    parse_forums_from_html,
    parse_interval,
    split_accounts,
)


def test_decode_utf8_forum_name() -> None:
    assert decode_forum_name("%E6%B5%8B%E8%AF%95") == "测试"


def test_decode_gbk_forum_name() -> None:
    assert decode_forum_name("%B2%E2%CA%D4") == "测试"


def test_parse_fixed_interval() -> None:
    assert parse_interval("3") == (3.0, 3.0)


def test_parse_random_interval() -> None:
    assert parse_interval("8-3") == (3.0, 8.0)


def test_multiline_json_cookie_is_single_account() -> None:
    raw = """[
  {
    "name": "BDUSS",
    "value": "example",
    "domain": ".baidu.com"
  }
]"""
    assert split_accounts(raw) == [raw]


def test_parse_followed_forums_from_like_table() -> None:
    html = """
    <div id="like_pagelet">
      <table><tbody>
        <tr><td><a href="/f?kw=%E6%B5%8B%E8%AF%95" title="测试">测试吧</a></td></tr>
      </tbody></table>
    </div>
    """
    forums = parse_forums_from_html(html)
    assert len(forums) == 1
    assert forums[0].name == "测试"


def test_parse_ignores_non_followed_links() -> None:
    html = """
    <div id="like_pagelet"><table><tbody></tbody></table></div>
    <a href="/f?kw=%E5%B9%BF%E5%91%8A" title="广告">广告吧</a>
    """
    assert parse_forums_from_html(html) == []
