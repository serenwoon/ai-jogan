import copy
import json
import re
from datetime import date, timedelta
from pathlib import Path

from jogan.dates import load_site_config
from jogan.digest import CORNERS, EMPTY_NOTE, load_digest
from jogan.render import html_to_text, item_url, render_email, render_site

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
SITE = load_site_config(ROOT)
OK = load_digest(FIX / "digest_ok.json")
EMPTY_GH = load_digest(FIX / "digest_empty_github.json")
TODAY = date(2026, 10, 28)

DETAIL_HEADINGS = ("무엇인가", "왜 지금 화제인가", "내 업무에 쓸 자리", "배울 점", "주의", "원문")


def all_items(d):
    return [it for c in CORNERS for it in d["corners"][c]["items"]]


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def write_issue(issues_dir: Path, d: date, headline: str) -> None:
    digest = copy.deepcopy(OK)
    digest["date"] = d.isoformat()
    digest["headline"] = headline
    folder = issues_dir / d.isoformat()
    folder.mkdir(parents=True)
    (folder / "digest.json").write_text(json.dumps(digest, ensure_ascii=False), encoding="utf-8")


# ---------- item_url ----------

def test_item_url_format():
    assert item_url("https://x.github.io/ai-jogan", TODAY, "abc-1") == "https://x.github.io/ai-jogan/2026-10-28/abc-1.html"
    assert item_url("https://x.github.io/ai-jogan/", TODAY, "abc-1") == "https://x.github.io/ai-jogan/2026-10-28/abc-1.html"


# ---------- 메일 ----------

def test_email_has_no_style_block_details_or_input():
    _, html = render_email(OK, SITE)
    for bad in ("<style", "<details", "<input", "<script"):
        assert bad not in html.lower()


def test_email_subject_format():
    subject, _ = render_email(OK, SITE)
    assert subject == "AI 조간 10/28(수) — " + OK["headline"]


def test_email_header_and_corner_titles():
    _, html = render_email(OK, SITE)
    assert "AI 조간 · 10/28(수) · 읽는 시간 " in html
    for name in ("① 오늘의 한 줄", "② 업무 자동화 사례", "③ 깃허브·스킬 픽", "④ 따라 해보기", "⑤ 1분 용어"):
        assert name in html
    assert "#1a4fd6" in html
    assert 'style="' in html


def test_every_item_links_to_its_detail_page():
    _, html = render_email(OK, SITE)
    for item in all_items(OK):
        url = item_url(SITE["base_url"], TODAY, item["id"])
        assert html.count(f'href="{url}"') >= 2, item["id"]  # 제목 + 「자세히 →」
    assert html.count("자세히 →") == len(all_items(OK))


def test_empty_corner_shows_note():
    _, html = render_email(EMPTY_GH, SITE)
    assert EMPTY_NOTE in html
    assert "③ 깃허브·스킬 픽" in html


def test_escapes_html_in_titles():
    d = copy.deepcopy(OK)
    d["corners"]["one_line"]["items"][0]["title"] = 'A<B & "C"'
    d["headline"] = "A<B"
    subject, html = render_email(d, SITE)
    assert "A&lt;B &amp; " in html
    assert "A<B" not in html
    assert subject == "AI 조간 10/28(수) — A<B"  # 제목줄은 HTML이 아니라 그대로


def test_source_urls_are_stripped_and_only_http_rendered(tmp_path):
    d = copy.deepcopy(OK)
    item = d["corners"]["one_line"]["items"][0]
    item["sources"] = [
        {"title": "공백 있음", "url": "  https://example.com/a  "},
        {"title": "나쁜 주소", "url": "javascript:alert(1)"},
    ]
    render_site(d, SITE, tmp_path / "docs", tmp_path / "issues")
    page = (tmp_path / "docs" / "2026-10-28" / f"{item['id']}.html").read_text(encoding="utf-8")
    assert 'href="https://example.com/a"' in page
    assert "javascript:" not in page
    assert "나쁜 주소" in page  # 제목은 글로 남는다


# ---------- 사이트 ----------

def test_detail_page_has_six_sections_and_source_link(tmp_path):
    docs = tmp_path / "docs"
    render_site(OK, SITE, docs, tmp_path / "issues")
    item = OK["corners"]["automation"]["items"][0]
    page = (docs / "2026-10-28" / f"{item['id']}.html").read_text(encoding="utf-8")
    for heading in DETAIL_HEADINGS:
        assert f">{heading}<" in page, heading
    for src in item["sources"]:
        assert f'href="{src["url"]}"' in page
    assert "AI 조간 10/28(수) › ② 업무 자동화 사례" in re.sub(r"<[^>]+>", "", page)
    assert item["detail"]["what"] in page


def test_empty_detail_field_omits_its_heading(tmp_path):
    d = copy.deepcopy(OK)
    item = d["corners"]["term"]["items"][0]
    item["detail"]["caution"] = ""
    docs = tmp_path / "docs"
    render_site(d, SITE, docs, tmp_path / "issues")
    page = (docs / "2026-10-28" / f"{item['id']}.html").read_text(encoding="utf-8")
    assert ">주의<" not in page
    assert ">원문<" in page


def test_site_files_and_day_page(tmp_path):
    docs = tmp_path / "docs"
    written = render_site(OK, SITE, docs, tmp_path / "issues")
    assert (docs / ".nojekyll").is_file()
    assert (docs / "index.html").is_file()
    day = docs / "2026-10-28" / "index.html"
    assert day.is_file()
    assert len(written) == len(set(written))
    assert all(p.is_file() for p in written)
    assert {p for p in written if p.parent == docs / "2026-10-28"} >= {day}
    html = day.read_text(encoding="utf-8")
    for item in all_items(OK):
        assert (docs / "2026-10-28" / f"{item['id']}.html").is_file()
        assert f'href="{item["id"]}.html"' in html  # 상대 링크


def test_index_lists_last_30_days_newest_first(tmp_path):
    issues = tmp_path / "issues"
    for n in range(1, 36):  # 10-28 이전 35일
        write_issue(issues, TODAY - timedelta(days=n), f"머리말 {n}")
    docs = tmp_path / "docs"
    render_site(OK, SITE, docs, issues)
    html = (docs / "index.html").read_text(encoding="utf-8")
    dates = re.findall(r'href="(\d{4}-\d{2}-\d{2})/index\.html"', html)
    assert len(dates) == 30
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-10-28"
    assert dates[-1] == (TODAY - timedelta(days=29)).isoformat()


def test_index_includes_current_digest_once_even_if_in_issues(tmp_path):
    issues = tmp_path / "issues"
    write_issue(issues, TODAY, "이미 저장된 같은 날")
    write_issue(issues, TODAY - timedelta(days=1), "어제")
    (issues / "2026-10-20").mkdir()  # digest.json 없는 폴더
    (issues / "2026-10-19").mkdir()
    (issues / "2026-10-19" / "digest.json").write_text("{깨짐", encoding="utf-8")
    docs = tmp_path / "docs"
    render_site(OK, SITE, docs, issues)
    html = (docs / "index.html").read_text(encoding="utf-8")
    assert re.findall(r'href="(\d{4}-\d{2}-\d{2})/index\.html"', html) == ["2026-10-28", "2026-10-27"]
    assert OK["headline"] in html


def test_render_is_idempotent(tmp_path):
    issues = tmp_path / "issues"
    write_issue(issues, TODAY - timedelta(days=1), "어제")
    docs = tmp_path / "docs"
    render_site(OK, SITE, docs, issues)
    first = snapshot(docs)
    render_site(OK, SITE, docs, issues)
    assert snapshot(docs) == first
    assert render_email(OK, SITE) == render_email(OK, SITE)
    assert all(b"\r" not in data for data in first.values())


def test_rerender_removes_stale_item_pages_of_that_day(tmp_path):
    docs = tmp_path / "docs"
    render_site(OK, SITE, docs, tmp_path / "issues")
    d = copy.deepcopy(OK)
    d["corners"]["term"]["items"][0]["id"] = "term-new-id"
    render_site(d, SITE, docs, tmp_path / "issues")
    assert (docs / "2026-10-28" / "term-new-id.html").is_file()
    assert not (docs / "2026-10-28" / "term-tool-calling.html").exists()


# ---------- html_to_text (R1) ----------

def test_html_to_text_links_become_text_and_url():
    out = html_to_text('<p>보세요 <a href="https://e.com/x">여기</a> 입니다</p>')
    assert out == "보세요 여기 (https://e.com/x) 입니다"


def test_html_to_text_blocks_make_lines_and_whitespace_collapses():
    html = "<div>  첫째   줄\n\n계속 </div><div>둘째</div><p>문단</p><ul><li>하나</li><li>둘</li></ul>a<br>b"
    lines = html_to_text(html).split("\n")
    assert lines[0] == "첫째 줄 계속"
    assert lines[1] == "둘째"
    assert "문단" in lines and "하나" in lines and "둘" in lines
    assert lines[-2:] == ["a", "b"]
    assert "\n\n\n" not in html_to_text(html)
    assert not html_to_text(html).startswith("\n") and not html_to_text(html).endswith("\n")


def test_html_to_text_skips_head_style_script_and_decodes_entities():
    html = "<html><head><title>제목</title><style>p{color:red}</style></head><body><script>x()</script><p>A &lt; B &amp; C</p></body></html>"
    assert html_to_text(html) == "A < B & C"


def test_html_to_text_link_edge_cases():
    assert html_to_text('<a href="https://e.com">https://e.com</a>') == "https://e.com"
    assert html_to_text('<a href="https://e.com"></a>') == "https://e.com"
    assert html_to_text("<a>링크 아님</a>") == "링크 아님"


def test_email_plain_text_keeps_titles_and_detail_urls():
    _, html = render_email(OK, SITE)
    text = html_to_text(html)
    assert "<" not in text
    assert "① 오늘의 한 줄" in text
    item = OK["corners"]["github"]["items"][0]
    assert item["title"] in text
    assert f"({item_url(SITE['base_url'], TODAY, item['id'])})" in text
    assert "읽는 시간" in text
