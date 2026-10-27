import json
from datetime import UTC, date, datetime
from pathlib import Path

from jogan.collect import collect_all
from jogan.dates import kst_today

FIX = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 10, 27, 21, 0, tzinfo=UTC)
TODAY = kst_today(NOW)
assert TODAY == date(2026, 10, 28)

FEED = (FIX / "feed.xml").read_text(encoding="utf-8")
GITHUB = json.loads((FIX / "github_search.json").read_text(encoding="utf-8"))
HN = json.loads((FIX / "hn.json").read_text(encoding="utf-8"))


def make_cfg(**over):
    cfg = {
        "rss": [
            {"name": "OpenAI", "url": "https://feeds.example.com/openai.xml"},
            {"name": "Other", "url": "https://feeds.example.com/other.xml"},
        ],
        "rss_max_age_hours": 48,
        "github_topics": ["mcp", "ai-agents"],
        "github_created_within_days": 30,
        "hn_keywords": ["AI", "LLM", "agent", "MCP"],
        "hn_min_points": 100,
        "max_candidates": 60,
        "fetch_text_limit": 25,
    }
    cfg.update(over)
    return cfg


class FakeHttp:
    """URL로 응답을 고르는 가짜. fail에는 출처 이름('OpenAI', 'GitHub:mcp', 'Hacker News')을 준다."""

    def __init__(self, cfg, fail=(), feed=FEED.encode("utf-8"), github=GITHUB):
        self.cfg = cfg
        self.feed = feed
        self.github = github
        self.fail = set(fail)
        self.calls = []
        self.headers_seen = []

    def get_bytes(self, url):
        self.calls.append(url)
        for feed in self.cfg["rss"]:
            if feed["url"] == url:
                if feed["name"] in self.fail:
                    raise RuntimeError("HTTP 404")
                return self.feed
        raise AssertionError(f"unexpected text url {url}")

    def get_json(self, url, headers=None):
        self.calls.append(url)
        self.headers_seen.append(headers)
        if "api.github.com" in url:
            for topic in self.cfg["github_topics"]:
                if f"topic:{topic}+" in url and f"GitHub:{topic}" in self.fail:
                    raise RuntimeError("HTTP 403")
            return self.github
        if "hn.algolia.com" in url:
            if "Hacker News" in self.fail:
                raise RuntimeError("timeout")
            return HN
        raise AssertionError(f"unexpected json url {url}")


def run(tmp_path, cfg=None, stars=None, fail=(), http=None, today=TODAY):
    cfg = cfg or make_cfg()
    stars_path = tmp_path / "stars.json"
    if stars is not None:
        stars_path.write_text(json.dumps(stars), encoding="utf-8")
    http = http or FakeHttp(cfg, fail=fail)
    return collect_all(cfg, today, stars_path, http, now_utc=NOW), stars_path, http


def by_kind(out, kind):
    return [c for c in out["candidates"] if c["kind"] == kind]


def test_rss_items_older_than_48h_dropped(tmp_path):
    out, _, _ = run(tmp_path)
    articles = by_kind(out, "article")
    titles = [c["title"] for c in articles]
    assert titles == ["Fresh post one", "Fresh post two", "Almost stale post (47h)"]  # 최신순
    # 같은 글이 두 피드에 있어도 한 건
    urls = [c["url"] for c in articles]
    assert len(urls) == len(set(urls)) == 3
    assert articles[0]["url"] == "https://example.com/posts/one"  # utm 제거
    assert articles[0]["source"] == "OpenAI"
    assert articles[0]["published"].startswith("2026-10-27T12:00:00")


def test_repo_star_delta_from_snapshot(tmp_path):
    out, stars_path, _ = run(tmp_path, stars={"example/alpha": 120})
    alpha = next(c for c in by_kind(out, "repo") if c["title"].startswith("example/alpha"))
    assert alpha["stars"] == 300
    assert alpha["stars_delta"] == 180
    saved = json.loads(stars_path.read_text(encoding="utf-8"))
    assert saved["example/alpha"] == {"stars": 300, "date": "2026-10-28", "prev_stars": 120, "prev_date": None}
    assert saved["example/beta"] == {"stars": 900, "date": "2026-10-28", "prev_stars": None, "prev_date": None}


def test_first_seen_repo_has_no_delta(tmp_path):
    out, stars_path, _ = run(tmp_path)
    repos = by_kind(out, "repo")
    assert len(repos) == 3  # 두 주제에서 나온 같은 저장소는 한 건
    assert all(c["stars_delta"] is None for c in repos)
    assert [c["stars"] for c in repos] == [900, 300, 40]  # delta가 없으면 stars 내림차순
    assert all(c["source"] == "GitHub" for c in repos)
    raw = stars_path.read_bytes().decode("utf-8")
    assert "\r" not in raw and raw.endswith("\n")
    assert list(json.loads(raw)) == sorted(json.loads(raw))


def test_repos_sorted_by_delta_before_stars(tmp_path):
    out, _, _ = run(tmp_path, stars={"example/alpha": 100, "example/beta": 890})
    names = [c["title"].split(":")[0] for c in by_kind(out, "repo")]
    assert names[0] == "example/alpha"  # delta 200 > 10


def test_existing_snapshot_entries_are_kept(tmp_path):
    _, stars_path, _ = run(tmp_path, stars={"old/repo": 7})
    saved = json.loads(stars_path.read_text(encoding="utf-8"))
    assert saved["old/repo"]["stars"] == 7 and saved["example/gamma"]["stars"] == 40


def test_same_day_rerun_keeps_same_delta(tmp_path):
    first, stars_path, _ = run(tmp_path, stars={"example/alpha": 120})
    second, _, _ = run(tmp_path)  # 같은 스냅샷 파일, 같은 날
    third, _, _ = run(tmp_path)
    for out in (second, third):
        alpha = next(c for c in by_kind(out, "repo") if c["title"].startswith("example/alpha"))
        assert alpha["stars_delta"] == 180
    assert [c["stars_delta"] for c in by_kind(first, "repo")] == [c["stars_delta"] for c in by_kind(second, "repo")]
    saved = json.loads(stars_path.read_text(encoding="utf-8"))
    assert saved["example/alpha"]["prev_stars"] == 120


def test_same_day_rerun_of_first_seen_repo_stays_none(tmp_path):
    run(tmp_path)
    again, _, _ = run(tmp_path)
    assert all(c["stars_delta"] is None for c in by_kind(again, "repo"))


def test_same_day_rerun_updates_current_stars(tmp_path):
    run(tmp_path, stars={"example/alpha": 120})
    grown = {"items": [{**GITHUB["items"][0], "stargazers_count": 330}]}
    out, stars_path, _ = run(tmp_path, http=FakeHttp(make_cfg(), github=grown))
    alpha = by_kind(out, "repo")[0]
    assert alpha["stars_delta"] == 210  # 기준은 여전히 120
    assert json.loads(stars_path.read_text(encoding="utf-8"))["example/alpha"]["stars"] == 330


def test_next_day_uses_updated_baseline(tmp_path):
    run(tmp_path, stars={"example/alpha": 120})
    grown = {"items": [{**GITHUB["items"][0], "stargazers_count": 350}]}
    tomorrow = date(2026, 10, 29)
    out, stars_path, _ = run(tmp_path, today=tomorrow, http=FakeHttp(make_cfg(), github=grown))
    alpha = by_kind(out, "repo")[0]
    assert alpha["stars_delta"] == 50  # 어제 기록한 300 이 기준
    saved = json.loads(stars_path.read_text(encoding="utf-8"))["example/alpha"]
    assert saved == {"stars": 350, "date": "2026-10-29", "prev_stars": 300, "prev_date": "2026-10-28"}
    # 같은 날 다시 돌려도 50
    again, _, _ = run(tmp_path, today=tomorrow, http=FakeHttp(make_cfg(), github=grown))
    assert by_kind(again, "repo")[0]["stars_delta"] == 50


def test_github_query_and_token(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    _, _, http = run(tmp_path)
    gh = [u for u in http.calls if "api.github.com" in u]
    assert len(gh) == 2
    assert "topic:mcp+created:>=2026-09-28" in gh[0]
    assert "sort=stars&order=desc&per_page=20" in gh[0]
    assert all(h and h["Authorization"] == "Bearer tok" for h in http.headers_seen[:2])
    monkeypatch.delenv("GITHUB_TOKEN")
    _, _, http2 = run(tmp_path)
    assert not any(h and "Authorization" in h for h in http2.headers_seen)


def test_hn_keyword_filter(tmp_path):
    out, _, http = run(tmp_path)
    hn = {c["title"]: c for c in by_kind(out, "hn")}
    # "said" 안의 ai 는 키워드가 아니다
    assert set(hn) == {"Show HN: A new LLM agent framework", "MCP servers explained"}
    assert hn["MCP servers explained"]["url"] == "https://news.ycombinator.com/item?id=1004"
    assert all(c["source"] == "Hacker News" for c in hn.values())
    url = next(u for u in http.calls if "hn.algolia.com" in u)
    since = int(NOW.timestamp()) - 24 * 3600
    assert f"created_at_i>{since},points>100" in url


def test_hn_keyword_matches_plurals_but_not_inside_words(tmp_path):
    hn = {"hits": [
        {"objectID": "1", "title": "Why LLMs fail", "url": "https://example.org/a", "points": 200,
         "created_at": "2026-10-27T10:00:00.000Z"},
        {"objectID": "2", "title": "Agents everywhere", "url": "https://example.org/b", "points": 200,
         "created_at": "2026-10-27T09:00:00.000Z"},
        {"objectID": "3", "title": "Agentic coding in practice", "url": "https://example.org/c", "points": 200,
         "created_at": "2026-10-27T08:00:00.000Z"},
        {"objectID": "4", "title": "He said it was a mainstay", "url": "https://example.org/d", "points": 200,
         "created_at": "2026-10-27T07:00:00.000Z"},
    ]}

    class Hn(FakeHttp):
        def get_json(self, url, headers=None):
            return hn if "hn.algolia.com" in url else {"items": []}

    cfg = make_cfg()
    out, _, _ = run(tmp_path, cfg=cfg, http=Hn(cfg))
    assert [c["title"] for c in by_kind(out, "hn")] == [
        "Why LLMs fail", "Agents everywhere", "Agentic coding in practice"]


def test_korean_feed_bytes_without_charset_parse_correctly(tmp_path):
    korean = (
        '<?xml version="1.0"?><rss version="2.0"><channel><title>피드</title>'
        "<item><title>한글 제목 테스트</title><link>https://example.com/ko</link>"
        "<pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>"
    ).encode("utf-8")
    cfg = make_cfg(rss=[{"name": "KR", "url": "https://feeds.example.com/kr.xml"}])
    out, _, _ = run(tmp_path, cfg=cfg, http=FakeHttp(cfg, feed=korean))
    assert [c["title"] for c in by_kind(out, "article")] == ["한글 제목 테스트"]


def test_requests_http_get_bytes_returns_raw_content(monkeypatch):
    from jogan import collect

    class Resp:
        content = "한글".encode("utf-8")
        text = "í"  # charset 없이 .text 로 읽으면 이렇게 깨진다

        def raise_for_status(self):
            pass

    monkeypatch.setattr(collect.requests, "get", lambda url, headers, timeout: Resp())
    assert collect.RequestsHttp().get_bytes("https://example.com/x").decode("utf-8") == "한글"


def test_one_source_failure_does_not_abort(tmp_path):
    out, _, _ = run(tmp_path, fail={"OpenAI"})
    assert out["failed_sources"][0]["source"] == "OpenAI"
    assert "404" in out["failed_sources"][0]["error"]
    assert len(out["candidates"]) > 0
    assert out["date"] == "2026-10-28"


def test_github_and_hn_failures_are_recorded(tmp_path):
    out, _, _ = run(tmp_path, fail={"GitHub:mcp", "Hacker News"})
    names = [f["source"] for f in out["failed_sources"]]
    assert names == ["GitHub:mcp", "Hacker News"]
    assert len(by_kind(out, "repo")) == 3  # 다른 주제가 살아 있다
    assert by_kind(out, "hn") == []


def test_all_sources_failing_returns_empty(tmp_path):
    names = {"OpenAI", "Other", "GitHub:mcp", "GitHub:ai-agents", "Hacker News"}
    out, _, _ = run(tmp_path, fail=names)
    assert out["candidates"] == []
    assert len(out["failed_sources"]) == 5


def test_non_feed_response_counts_as_failure(tmp_path):
    cfg = make_cfg()

    class Html(FakeHttp):
        def get_bytes(self, url):
            return b"<html><body>not a feed</body></html>"

    out, _, _ = run(tmp_path, cfg=cfg, http=Html(cfg))
    assert {f["source"] for f in out["failed_sources"]} == {"OpenAI", "Other"}


def test_candidates_capped_at_max(tmp_path):
    out, _, _ = run(tmp_path, cfg=make_cfg(max_candidates=4))
    assert len(out["candidates"]) == 4
    # 한 종류가 자리를 독차지하지 않는다
    assert {c["kind"] for c in out["candidates"]} == {"article", "repo", "hn"}


def test_candidate_ids_are_sequential(tmp_path):
    out, _, _ = run(tmp_path)
    ids = [c["id"] for c in out["candidates"]]
    assert ids == [f"c{i:03d}" for i in range(1, len(ids) + 1)]
    assert len(ids) == 3 + 3 + 2
    assert all(c["text_file"] is None for c in out["candidates"])
