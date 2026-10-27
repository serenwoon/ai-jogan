"""KST 기준 날짜 도우미. 예약 실행은 UTC 21:00이므로 모든 날짜는 여기서 KST로 얻는다."""
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
_WEEKDAYS = "월화수목금토일"


def kst_today(now_utc: datetime | None = None) -> date:
    """KST 기준 오늘 날짜. now_utc를 주면 그 시각을 기준으로 한다."""
    if now_utc is None:
        now_utc = datetime.now(UTC)
    return now_utc.astimezone(KST).date()


def iso_week_label(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def previous_iso_week(d: date) -> str:
    return iso_week_label(d - timedelta(days=7))


def korean_date_label(d: date) -> str:
    return f"{d.month:02d}/{d.day:02d}({_WEEKDAYS[d.weekday()]})"


def load_site_config(root: Path) -> dict:
    with open(Path(root) / "config" / "site.json", encoding="utf-8") as f:
        return json.load(f)
