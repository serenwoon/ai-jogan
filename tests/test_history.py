import json
from datetime import date
from pathlib import Path

from jogan.digest import load_digest
from jogan.history import find_duplicates, recent_keys

FIX = Path(__file__).resolve().parent / "fixtures"
TODAY = date(2026, 10, 28)


def put_digest(issues_dir, day, url_by_id):
    """issues/<day>/digest.json 에 id: url 목록으로 간단한 digest를 쓴다."""
    d = load_digest(FIX / "digest_ok.json")
    d["date"] = day
    for corner in d["corners"].values():
        corner["items"] = []
    items = d["corners"]["one_line"]["items"]
    for item_id, url in url_by_id.items():
        items.append({"id": item_id, "title": "t", "summary": "s", "tags": [], "detail": {},
                      "sources": [{"title": "x", "url": url}]})
    folder = issues_dir / day
    folder.mkdir(parents=True)
    (folder / "digest.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def test_dedupe_ignores_same_date(tmp_path):
    put_digest(tmp_path, "2026-10-28", {"a": "https://example.com/today"})
    assert recent_keys(tmp_path, TODAY) == set()


def test_dedupe_finds_url_from_3_days_ago(tmp_path):
    put_digest(tmp_path, "2026-10-25", {"a": "https://Example.com/post/?utm_source=x"})
    keys = recent_keys(tmp_path, TODAY)
    assert keys == {"https://example.com/post"}
    d = load_digest(FIX / "digest_ok.json")
    first = d["corners"]["one_line"]["items"][0]
    first["sources"][0]["url"] = "https://example.com/post#top"
    assert find_duplicates(d, keys) == [first["id"]]


def test_window_is_seven_days_before_today(tmp_path):
    put_digest(tmp_path, "2026-10-21", {"a": "https://example.com/seven"})   # 7일 전: 포함
    put_digest(tmp_path, "2026-10-20", {"a": "https://example.com/eight"})   # 8일 전: 제외
    put_digest(tmp_path, "2026-10-29", {"a": "https://example.com/future"})  # 미래: 제외
    assert recent_keys(tmp_path, TODAY) == {"https://example.com/seven"}


def test_missing_and_broken_files_are_skipped(tmp_path):
    put_digest(tmp_path, "2026-10-27", {"a": "https://example.com/ok"})
    (tmp_path / "2026-10-26").mkdir()  # digest.json 없음
    broken = tmp_path / "2026-10-25"
    broken.mkdir()
    (broken / "digest.json").write_text("{", encoding="utf-8")
    odd = tmp_path / "2026-10-24"
    odd.mkdir()
    (odd / "digest.json").write_text('{"corners": [1]}', encoding="utf-8")
    assert recent_keys(tmp_path, TODAY) == {"https://example.com/ok"}
    assert recent_keys(tmp_path / "nope", TODAY) == set()


def test_all_sources_of_an_item_are_keys(tmp_path):
    folder = tmp_path / "2026-10-27"
    folder.mkdir()
    d = load_digest(FIX / "digest_ok.json")
    (folder / "digest.json").write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    keys = recent_keys(tmp_path, TODAY)
    assert "https://example.org/blog/minutes-report" in keys
    assert "http://example.org/templates/weekly" in keys


def test_find_duplicates_none_and_multiple():
    d = load_digest(FIX / "digest_ok.json")
    assert find_duplicates(d, set()) == []
    keys = {"https://example.com/skills/spec", "https://github.com/example/prompt-lint"}
    assert find_duplicates(d, keys) == ["skills-open-spec", "prompt-linter"]
