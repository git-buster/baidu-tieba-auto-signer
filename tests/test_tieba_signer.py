from scripts.tieba_signer import (
    cookie_login_hint,
    decode_forum_name,
    html_indicates_signed,
    parse_followed_forum_pagination,
    parse_followed_forum_total_pages,
    parse_forums_from_html,
    parse_interval,
    parse_pn_from_url,
    split_accounts,
    text_indicates_signed,
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


def test_cookie_login_hint_reports_missing_bduss() -> None:
    hint = cookie_login_hint([{"name": "BAIDUID", "value": "example"}])
    assert "BDUSS" in hint


def test_cookie_login_hint_reports_rejected_login_cookie() -> None:
    hint = cookie_login_hint([{"name": "BDUSS", "value": "example"}])
    assert "rejected" in hint


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


def test_new_ui_streak_text_means_signed() -> None:
    assert text_indicates_signed("连签1天")


def test_new_ui_signed_state_accepts_any_streak_days() -> None:
    html = '<div class="follow-sign">连签28天</div>'
    assert html_indicates_signed(html)


def test_old_ui_signed_state_accepts_signed_text() -> None:
    html = '<div id="signstar_wrapper"><a class="j_signbtn">已签到 连续7天</a></div>'
    assert html_indicates_signed(html)


def test_old_ui_signed_state_accepts_signed_class_without_signed_text() -> None:
    html = (
        '<div id="signstar_wrapper" class="sign_box_bright_signed">'
        '<a class="j_signbtn signstar_signed">05月08日 漏签6天 连续1天</a>'
        "</div>"
    )
    assert html_indicates_signed(html)


def test_sign_rank_alone_is_not_signed() -> None:
    assert not html_indicates_signed("<div>签到排名</div>")


def test_old_ui_signable_state_is_not_signed() -> None:
    html = (
        '<div id="signstar_wrapper" class="sign_box_bright">'
        '<a class="j_signbtn sign_btn_bright j_cansign">05月08日 漏签0天</a>'
        "</div>"
    )
    assert not html_indicates_signed(html)


def test_parse_followed_forum_total_pages_from_tail_link() -> None:
    html = """
    <div id="like_pagelet">
      <a href="/i/i/forum?&pn=2">2</a>
      <a href="/i/i/forum?&pn=6">尾页</a>
    </div>
    """
    assert parse_followed_forum_total_pages(html) == 6


def test_parse_followed_forum_pagination_prefers_tail_url() -> None:
    html = """
    <div id="like_pagelet">
      <a href="/i/i/forum?&pn=2">2</a>
      <a href="/i/i/forum?&pn=6">尾页</a>
    </div>
    """
    assert parse_followed_forum_pagination(html) == {
        "total_pages": 6,
        "tail_url": "https://tieba.baidu.com/i/i/forum?&pn=6",
    }


def test_single_followed_forum_page_reports_one_page() -> None:
    html = """
    <div id="like_pagelet">
      <table><tbody>
        <tr><td><a href="/f?kw=test" title="test">test</a></td></tr>
      </tbody></table>
    </div>
    """
    assert parse_followed_forum_total_pages(html) == 1


def test_parse_pn_from_url() -> None:
    assert parse_pn_from_url("https://tieba.baidu.com/i/i/forum?&pn=12") == 12
