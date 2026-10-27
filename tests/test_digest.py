import copy
import json
from datetime import date
from pathlib import Path

import pytest

from jogan.digest import (
    CORNERS,
    DigestError,
    load_digest,
    normalize_url,
    reading_minutes,
    validate_digest,
)

FIX = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 10, 28)


def ok():
    return load_digest(FIX / "digest_ok.json")


def first_item(d, corner="one_line"):
    return d["corners"][corner]["items"][0]


def has(violations, word):
    return any(word in v for v in violations)


def test_corners_order():
    assert CORNERS == ("one_line", "automation", "github", "try_this", "term")


def test_valid_fixture_passes():
    assert validate_digest(load_digest(FIX / "digest_ok.json"), date(2026, 10, 28)) == []


def test_empty_github_with_note_passes():
    d = load_digest(FIX / "digest_empty_github.json")
    assert validate_digest(d, date(2026, 10, 28)) == []


def test_empty_one_line_fails():
    d = ok()
    d["corners"]["one_line"] = {"items": [], "empty_note": "오늘은 새 사례 없음"}
    assert has(validate_digest(d, TODAY), "one_line")


def test_empty_try_this_and_term_fail():
    for corner in ("try_this", "term"):
        d = ok()
        d["corners"][corner] = {"items": [], "empty_note": "오늘은 새 사례 없음"}
        assert has(validate_digest(d, TODAY), corner)


def test_empty_corner_requires_exact_note():
    d = ok()
    d["corners"]["github"] = {"items": [], "empty_note": "없음"}
    assert has(validate_digest(d, TODAY), "empty_note")
    d["corners"]["github"] = {"items": [], "empty_note": None}
    assert has(validate_digest(d, TODAY), "empty_note")


def test_item_count_limits():
    d = ok()
    d["corners"]["github"]["items"].append(copy.deepcopy(first_item(d, "github")))
    d["corners"]["github"]["items"][2]["id"] = "third-repo"
    assert has(validate_digest(d, TODAY), "github")
    d = ok()
    extra = copy.deepcopy(first_item(d, "one_line"))
    extra["id"] = "another-headline"
    d["corners"]["one_line"]["items"].append(extra)
    assert has(validate_digest(d, TODAY), "one_line")


def test_nonempty_corner_with_empty_note_text_fails():
    d = ok()
    d["corners"]["github"]["empty_note"] = "오늘은 새 사례 없음"
    assert has(validate_digest(d, TODAY), "empty_note")


def test_missing_corner_fails():
    d = ok()
    del d["corners"]["term"]
    assert has(validate_digest(d, TODAY), "term")


def test_item_without_source_fails():
    d = ok()
    first_item(d)["sources"] = []
    assert has(validate_digest(d, TODAY), "출처")


def test_non_http_source_fails():
    d = ok()
    first_item(d)["sources"][0]["url"] = "javascript:alert(1)"
    assert has(validate_digest(d, TODAY), "http")


def test_summary_over_120_fails():
    d = ok()
    first_item(d)["summary"] = "가" * 121
    assert has(validate_digest(d, TODAY), "120")
    first_item(d)["summary"] = "가" * 120
    assert not has(validate_digest(d, TODAY), "120")


def test_title_over_60_fails():
    d = ok()
    first_item(d)["title"] = "가" * 61
    assert has(validate_digest(d, TODAY), "60")


def test_headline_over_40_fails():
    d = ok()
    d["headline"] = "가" * 41
    assert has(validate_digest(d, TODAY), "40")


def test_detail_field_over_400_fails():
    d = ok()
    first_item(d)["detail"]["caution"] = "가" * 401
    assert has(validate_digest(d, TODAY), "400")
    first_item(d)["detail"]["caution"] = "가" * 400
    assert not has(validate_digest(d, TODAY), "400")


def test_missing_detail_field_fails():
    d = ok()
    del first_item(d)["detail"]["lesson"]
    assert has(validate_digest(d, TODAY), "lesson")


def test_too_many_tags_fails():
    d = ok()
    first_item(d)["tags"] = ["a", "b", "c", "d"]
    assert has(validate_digest(d, TODAY), "tags")


def test_wrong_date_fails():
    d = ok()
    assert has(validate_digest(d, date(2026, 10, 29)), "날짜")
    d["date"] = "2026-10-27"
    assert has(validate_digest(d, TODAY), "날짜")


def test_duplicate_item_ids_fail():
    d = ok()
    first_item(d, "term")["id"] = first_item(d, "one_line")["id"]
    assert has(validate_digest(d, TODAY), "id")


def test_bad_id_format_fails():
    for bad in ("Skills-AAIF", "skills_aaif", "스킬", "has space", ""):
        d = ok()
        first_item(d)["id"] = bad
        assert has(validate_digest(d, TODAY), "id"), bad


def test_reserved_id_index_fails():
    d = ok()
    first_item(d)["id"] = "index"
    assert has(validate_digest(d, TODAY), "예약")


@pytest.mark.parametrize("field", ["headline", "title", "summary"])
@pytest.mark.parametrize("ch", ["\n", "\r", "\t", "\x00", "\x1b", "\x7f"])
def test_control_characters_in_one_line_fields_fail(field, ch):
    d = ok()
    if field == "headline":
        d["headline"] = "앞" + ch + "뒤"
    else:
        first_item(d)[field] = "앞" + ch + "뒤"
    assert has(validate_digest(d, TODAY), "제어 문자")


def test_newline_in_detail_is_allowed():
    d = ok()
    first_item(d)["detail"]["what"] = "첫 줄\n둘째 줄"
    assert validate_digest(d, TODAY) == []


def test_too_long_reading_time_fails():
    d = ok()
    for corner in CORNERS:
        for item in d["corners"][corner]["items"]:
            item["summary"] = "가" * 2000
    assert reading_minutes(d) > 5
    assert has(validate_digest(d, TODAY), "읽는 시간")


def test_reading_minutes_counts_visible_text():
    d = ok()
    chars = len(d["headline"])
    for corner in CORNERS:
        c = d["corners"][corner]
        for item in c["items"]:
            chars += len(item["title"]) + len(item["summary"])
        if c["empty_note"]:
            chars += len(c["empty_note"])
    assert reading_minutes(d) == -(-chars // 500)
    # detail은 메일에 보이지 않으므로 세지 않는다
    first_item(d)["detail"]["what"] = "가" * 400
    assert reading_minutes(d) == -(-chars // 500)


def test_reading_minutes_counts_empty_note():
    d = load_digest(FIX / "digest_empty_github.json")
    d["corners"]["github"]["empty_note"] = "가" * 2600
    assert reading_minutes(d) >= 6


def test_wrong_types_give_violations_not_exceptions():
    for bad in (None, [], "x", {"date": 1, "headline": 3, "corners": []}, {"corners": {"one_line": None}}):
        assert validate_digest(bad, TODAY)  # 비어 있지 않은 목록, 예외 없음
    d = ok()
    d["corners"]["one_line"]["items"] = "oops"
    assert validate_digest(d, TODAY)
    d = ok()
    first_item(d)["sources"] = [None]
    assert validate_digest(d, TODAY)
    d = ok()
    first_item(d)["tags"] = "MCP"
    assert validate_digest(d, TODAY)


def test_load_missing_or_broken_digest(tmp_path):
    with pytest.raises(DigestError):
        load_digest(tmp_path / "none.json")
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")
    with pytest.raises(DigestError):
        load_digest(tmp_path / "bad.json")


def test_load_non_object_json_fails(tmp_path):
    (tmp_path / "list.json").write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(DigestError):
        load_digest(tmp_path / "list.json")


def test_normalize_url_strips_utm():
    assert normalize_url("https://A.com/x/?utm_source=y#z") == "https://a.com/x"


def test_normalize_url_keeps_other_query_and_trailing_slash_rules():
    assert normalize_url("https://a.com/x?id=3&utm_medium=m") == "https://a.com/x?id=3"
    assert normalize_url("https://a.com/") == "https://a.com"
    assert normalize_url("HTTPS://A.com/P/Q/") == "https://a.com/P/Q"


def test_fixture_is_valid_json_with_utf8():
    json.loads((FIX / "digest_ok.json").read_text(encoding="utf-8"))
