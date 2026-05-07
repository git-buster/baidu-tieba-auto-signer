from scripts.tieba_signer import decode_forum_name, parse_interval


def test_decode_utf8_forum_name() -> None:
    assert decode_forum_name("%E6%B5%8B%E8%AF%95") == "测试"


def test_decode_gbk_forum_name() -> None:
    assert decode_forum_name("%B2%E2%CA%D4") == "测试"


def test_parse_fixed_interval() -> None:
    assert parse_interval("3") == (3.0, 3.0)


def test_parse_random_interval() -> None:
    assert parse_interval("8-3") == (3.0, 8.0)
