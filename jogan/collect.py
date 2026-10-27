"""RSS · GitHub · Hacker News 후보 수집과 별 스냅샷.

출처 하나가 죽어도(404, 타임아웃, 깨진 응답) 나머지로 계속하고 failed_sources에 남긴다.
"""
import json
import os
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol, TypedDict

import feedparser
import requests

from jogan.digest import normalize_url


class Candidate(TypedDict):
    id: str
    kind: str  # "article" | "repo" | "hn"
    title: str
    url: str
    source: str
    published: str | None
    stars: int | None
    stars_delta: int | None
    text_file: str | None


class Http(Protocol):
    def get_json(self, url: str, headers: dict | None = None) -> Any: ...

    def get_bytes(self, url: str) -> bytes: ...


class RequestsHttp:
    """실제 네트워크. 테스트에서는 쓰지 않는다."""

    TIMEOUT = 15
    HEADERS = {"User-Agent": "ai-jogan/0.1"}

    def _get(self, url: str, headers: dict | None = None) -> requests.Response:
        resp = requests.get(url, headers={**self.HEADERS, **(headers or {})}, timeout=self.TIMEOUT)
        resp.raise_for_status()
        return resp

    def get_json(self, url: str, headers: dict | None = None) -> Any:
        return self._get(url, headers).json()

    def get_bytes(self, url: str) -> bytes:
        # resp.text 는 charset 이 없으면 ISO-8859-1 로 읽어 한글이 깨진다 — 원본 바이트를 그대로 준다
        return self._get(url).content


def _err(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:200]


def _collect_rss(feed: dict, now: datetime, max_age: timedelta, http: Http) -> list[Candidate]:
    parsed = feedparser.parse(http.get_bytes(feed["url"]))
    if not parsed.version:  # 피드 형식으로 인식되지 않은 응답(HTML 오류 페이지 등)
        raise ValueError("피드로 읽히지 않는 응답")
    out: list[Candidate] = []
    for entry in parsed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        link = (entry.get("link") or "").strip()
        title = " ".join((entry.get("title") or "").split())
        if not stamp or not link or not title:
            continue  # 날짜를 못 읽으면 48시간 안인지 알 수 없다
        published = datetime(*stamp[:6], tzinfo=UTC)
        if now - published > max_age:
            continue
        out.append({
            "id": "", "kind": "article", "title": title, "url": normalize_url(link),
            "source": feed["name"], "published": published.isoformat(),
            "stars": None, "stars_delta": None, "text_file": None,
        })
    return out


def _collect_github(topic: str, since: date, http: Http) -> list[dict]:
    url = (
        "https://api.github.com/search/repositories"
        f"?q=topic:{topic}+created:>={since.isoformat()}&sort=stars&order=desc&per_page=20"
    )
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return list(http.get_json(url, headers=headers)["items"])


def _title_has_keyword(title: str, keywords: list[str]) -> bool:
    # 앞쪽만 단어 경계로 본다 — "said" 안의 "ai" 는 아니고, "LLMs"·"agents" 는 맞는다
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(k)}", title, re.IGNORECASE) for k in keywords)


def _collect_hn(cfg: dict, now: datetime, http: Http) -> list[Candidate]:
    since = int(now.timestamp()) - 24 * 3600
    url = (
        "https://hn.algolia.com/api/v1/search_by_date?tags=story"
        f"&numericFilters=created_at_i>{since},points>{cfg['hn_min_points']}&hitsPerPage=100"
    )
    out: list[Candidate] = []
    for hit in http.get_json(url)["hits"]:
        title = " ".join((hit.get("title") or "").split())
        if not title or not _title_has_keyword(title, cfg["hn_keywords"]):
            continue
        link = hit.get("url") or f"https://news.ycombinator.com/item?id={hit['objectID']}"
        out.append({
            "id": "", "kind": "hn", "title": title, "url": normalize_url(link),
            "source": "Hacker News", "published": hit.get("created_at"),
            "stars": None, "stars_delta": None, "text_file": None,
        })
    return out


def _load_stars(path: Path) -> dict[str, dict]:
    """full_name -> {"stars", "date", "prev_stars", "prev_date"}. 옛 형식(이름 -> 정수)도 읽는다."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for name, v in data.items():
        if isinstance(v, int) and not isinstance(v, bool):
            v = {"stars": v, "date": None}
        if isinstance(v, dict) and isinstance(v.get("stars"), int):
            out[name] = {"stars": v["stars"], "date": v.get("date"),
                         "prev_stars": v.get("prev_stars"), "prev_date": v.get("prev_date")}
    return out


def _baseline(entry: dict | None, today: str) -> int | None:
    """증가분을 잴 기준 별 수. 오늘 이미 기록된 항목이면 오늘 전의 값(prev)을 쓴다."""
    if entry is None:
        return None
    return entry["prev_stars"] if entry["date"] == today else entry["stars"]


def _updated_entry(entry: dict | None, stars: int, today: str) -> dict:
    if entry is None:
        return {"stars": stars, "date": today, "prev_stars": None, "prev_date": None}
    if entry["date"] == today:  # 같은 날 다시 실행 — 기준(prev)은 그대로 둔다
        return {**entry, "stars": stars}
    return {"stars": stars, "date": today, "prev_stars": entry["stars"], "prev_date": entry["date"]}


def _save_stars(path: Path, stars: dict[str, dict]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(stars, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def _repo_candidate(item: dict, baseline: int | None) -> Candidate:
    name = item["full_name"]
    stars = int(item["stargazers_count"])
    desc = " ".join((item.get("description") or "").split())
    title = f"{name}: {desc[:120]}" if desc else name
    return {
        "id": "", "kind": "repo", "title": title, "url": item["html_url"], "source": "GitHub",
        "published": None, "stars": stars,
        "stars_delta": stars - baseline if baseline is not None else None,
        "text_file": None,
    }


def _interleave(groups: list[list[Candidate]], limit: int) -> list[Candidate]:
    """종류별 순서를 지키며 돌아가면서 limit건까지 뽑는다. 한 종류가 자리를 독차지하지 않는다."""
    out: list[Candidate] = []
    pos = 0
    while len(out) < limit and any(pos < len(g) for g in groups):
        for g in groups:
            if pos < len(g) and len(out) < limit:
                out.append(g[pos])
        pos += 1
    return out


def collect_all(cfg: dict, today: date, stars_path: Path, http: Http, *,
                now_utc: datetime | None = None) -> dict:
    """모든 출처에서 후보를 모아 {"date", "candidates", "failed_sources"}를 돌려준다.

    stars_path 의 별 스냅샷을 읽어 증가분을 계산하고, 오늘 본 별 수를 합쳐 다시 쓴다.
    같은 날 다시 실행해도 기준은 오늘 전의 값(prev_stars)이라 증가분이 같다.
    """
    now = now_utc or datetime.now(UTC)
    failed: list[dict] = []
    seen: set[str] = set()

    def unique(cands: list[Candidate]) -> list[Candidate]:
        kept = []
        for c in cands:
            key = normalize_url(c["url"])
            if key not in seen:
                seen.add(key)
                kept.append(c)
        return kept

    articles: list[Candidate] = []
    max_age = timedelta(hours=cfg["rss_max_age_hours"])
    for feed in cfg["rss"]:
        try:
            articles.extend(_collect_rss(feed, now, max_age, http))
        except Exception as exc:
            failed.append({"source": feed["name"], "error": _err(exc)})
    articles.sort(key=lambda c: c["published"], reverse=True)

    previous = _load_stars(stars_path)
    today_iso = today.isoformat()
    today_stars: dict[str, int] = {}
    repos_by_name: dict[str, Candidate] = {}
    since = today - timedelta(days=cfg["github_created_within_days"])
    for topic in cfg["github_topics"]:
        try:
            items = _collect_github(topic, since, http)
            found = [(item, _repo_candidate(item, _baseline(previous.get(item["full_name"]), today_iso)))
                     for item in items]
        except Exception as exc:
            failed.append({"source": f"GitHub:{topic}", "error": _err(exc)})
            continue
        for item, cand in found:
            today_stars[item["full_name"]] = cand["stars"]
            repos_by_name.setdefault(item["full_name"], cand)
    repos = sorted(repos_by_name.values(),
                   key=lambda c: c["stars_delta"] if c["stars_delta"] is not None else c["stars"],
                   reverse=True)

    hn: list[Candidate] = []
    try:
        hn = _collect_hn(cfg, now, http)
    except Exception as exc:
        failed.append({"source": "Hacker News", "error": _err(exc)})
    hn.sort(key=lambda c: c["published"] or "", reverse=True)

    if today_stars:
        updated = {name: _updated_entry(previous.get(name), stars, today_iso)
                   for name, stars in today_stars.items()}
        _save_stars(stars_path, {**previous, **updated})

    groups = [unique(articles), unique(repos), unique(hn)]
    candidates = _interleave(groups, cfg["max_candidates"])
    for i, cand in enumerate(candidates, start=1):
        cand["id"] = f"c{i:03d}"
    return {"date": today.isoformat(), "candidates": candidates, "failed_sources": failed}
