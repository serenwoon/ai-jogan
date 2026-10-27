import json
from datetime import UTC, date, datetime
from pathlib import Path

from jogan.dates import (
    iso_week_label,
    korean_date_label,
    kst_today,
    load_site_config,
    previous_iso_week,
)

ROOT = Path(__file__).resolve().parents[1]


def test_kst_today_after_utc_21():
    assert kst_today(datetime(2026, 10, 27, 21, 0, tzinfo=UTC)) == date(2026, 10, 28)


def test_kst_today_before_utc_15():
    assert kst_today(datetime(2026, 10, 27, 14, 59, tzinfo=UTC)) == date(2026, 10, 27)


def test_kst_today_default_returns_date():
    assert isinstance(kst_today(), date)


def test_week_labels():
    assert iso_week_label(date(2026, 10, 26)) == "2026-W44"
    assert previous_iso_week(date(2026, 10, 26)) == "2026-W43"
    assert previous_iso_week(date(2027, 1, 4)) == "2026-W53"


def test_korean_date_label():
    assert korean_date_label(date(2026, 10, 28)) == "10/28(수)"


def test_load_site_config():
    cfg = load_site_config(ROOT)
    assert cfg == {
        "base_url": "https://serenwoon.github.io/ai-jogan",
        "subject_format": "AI 조간 {label} — {headline}",
        "mail_title": "AI 조간",
    }
    # file is plain UTF-8 JSON
    raw = (ROOT / "config" / "site.json").read_text(encoding="utf-8")
    assert json.loads(raw) == cfg
