"""최근 7일 digest와 겹치는 항목 찾기."""
from datetime import date, timedelta
from pathlib import Path

from jogan.digest import CORNERS, DigestError, load_digest, normalize_url


def _item_urls(item) -> list[str]:
    """항목 하나의 출처 URL(정규화). 깨진 구조는 빈 목록."""
    if not isinstance(item, dict) or not isinstance(item.get("sources"), list):
        return []
    return [
        normalize_url(s["url"])
        for s in item["sources"]
        if isinstance(s, dict) and isinstance(s.get("url"), str)
    ]


def _items(d: dict):
    corners = d.get("corners")
    if not isinstance(corners, dict):
        return
    for corner in CORNERS:
        c = corners.get(corner)
        if isinstance(c, dict) and isinstance(c.get("items"), list):
            yield from c["items"]


def recent_keys(issues_dir: Path, today: date, days: int = 7) -> set[str]:
    """오늘을 뺀 앞선 `days`일 digest의 출처 URL(정규화). 없거나 깨진 파일은 건너뛴다."""
    keys: set[str] = set()
    for back in range(1, days + 1):
        path = Path(issues_dir) / (today - timedelta(days=back)).isoformat() / "digest.json"
        try:
            d = load_digest(path)
        except DigestError:
            continue
        for item in _items(d):
            keys.update(_item_urls(item))
    return keys


def find_duplicates(d: dict, keys: set[str]) -> list[str]:
    """출처 URL이 keys와 겹치는 항목의 id (코너 순서·항목 순서)."""
    dup: list[str] = []
    for item in _items(d):
        if any(u in keys for u in _item_urls(item)):
            dup.append(item.get("id", ""))
    return dup
