import importlib.util
import json
import urllib.error
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "import_weekly.py"
_spec = importlib.util.spec_from_file_location("import_weekly", _PATH)
iw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(iw)


def _name(week):
    return f"AI 조간 주간 {week}.md"


@pytest.fixture(autouse=True)
def _log_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("AI_JOGAN_DEST", raising=False)


def _config(tmp_path):
    return tmp_path / "localappdata" / "ai-jogan" / "config.json"


def _write_config(tmp_path, data):
    p = _config(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _log_text(tmp_path):
    p = tmp_path / "localappdata" / "ai-jogan" / "import.log"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_imports_only_missing(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    (dest / _name("2026-W43")).write_text("old", encoding="utf-8")
    fetched = []

    def fetch(week):
        fetched.append(week)
        return f"본문 {week}\n"

    written = iw.import_missing(lambda: ["2026-W43", "2026-W44"], fetch, dest)
    assert written == [dest / _name("2026-W44")]
    assert fetched == ["2026-W44"]
    assert (dest / _name("2026-W44")).read_text(encoding="utf-8") == "본문 2026-W44\n"


def test_never_overwrites_existing_file(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    target = dest / _name("2026-W43")
    target.write_text("내가 고친 내용", encoding="utf-8")
    written = iw.import_missing(lambda: ["2026-W43"], lambda w: "새 내용", dest)
    assert written == []
    assert target.read_text(encoding="utf-8") == "내가 고친 내용"


def test_file_created_between_check_and_write_is_not_overwritten(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    target = dest / _name("2026-W43")

    def fetch(week):
        # the file appears while we were downloading
        target.write_text("뒤늦게 생김", encoding="utf-8")
        return "새 내용"

    written = iw.import_missing(lambda: ["2026-W43"], fetch, dest)
    assert written == []
    assert target.read_text(encoding="utf-8") == "뒤늦게 생김"


def test_writes_utf8_lf_even_if_source_has_crlf(tmp_path):
    dest = tmp_path / "dest"
    text = "---\r\ntitle: AI 조간 주간 2026-W43\r\n---\r\n한글\rlone\r\n"
    iw.import_missing(lambda: ["2026-W43"], lambda w: text, dest)
    raw = (dest / _name("2026-W43")).read_bytes()
    assert b"\r" not in raw
    assert raw.decode("utf-8") == "---\ntitle: AI 조간 주간 2026-W43\n---\n한글\nlone\n"


def test_creates_dest_dir(tmp_path):
    dest = tmp_path / "a" / "b" / "c"
    written = iw.import_missing(lambda: ["2026-W43"], lambda w: "x", dest)
    assert dest.is_dir()
    assert len(written) == 1


def test_network_error_returns_empty_and_logs(tmp_path):
    def boom(req, timeout=None):
        raise urllib.error.URLError("offline")

    assert iw.list_weeks(urlopen=boom) == []
    assert "offline" in _log_text(tmp_path)


def test_listing_failure_does_not_create_dest_dir(tmp_path):
    dest = tmp_path / "dest"
    assert iw.import_missing(lambda: [], lambda w: "x", dest) == []
    assert not dest.exists()


def test_list_weeks_filters_and_sorts():
    payload = [
        {"name": "2026-W44.md"},
        {"name": "README.md"},
        {"name": "2026-W43.md"},
        {"name": "2026-W5.md"},
        {"name": "2026-W43.txt"},
        {"name": "../2026-W45.md"},
    ]

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    seen = {}

    def ok(req, timeout=None):
        seen["url"] = req.full_url
        return Resp()

    assert iw.list_weeks(urlopen=ok) == ["2026-W43", "2026-W44"]
    assert seen["url"] == "https://api.github.com/repos/serenwoon/ai-jogan/contents/weekly"


def test_fetch_error_for_one_week_continues(tmp_path):
    dest = tmp_path / "dest"

    def fetch(week):
        if week == "2026-W43":
            raise urllib.error.HTTPError("u", 404, "nf", {}, None)
        return "ok"

    written = iw.import_missing(lambda: ["2026-W43", "2026-W44"], fetch, dest)
    assert written == [dest / _name("2026-W44")]
    assert "2026-W43" in _log_text(tmp_path)
    assert not (dest / _name("2026-W43")).exists()


def test_unsafe_week_name_is_ignored(tmp_path):
    dest = tmp_path / "dest"
    written = iw.import_missing(lambda: ["../evil", "2026-W43"], lambda w: "x", dest)
    assert written == [dest / _name("2026-W43")]


def test_main_exits_zero_on_listing_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: [])
    assert iw.main(["--dest", str(tmp_path / "d")]) == 0


def test_main_writes_to_dest_override(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: ["2026-W43"])
    monkeypatch.setattr(iw, "fetch_week", lambda week, **kw: "x\n")
    dest = tmp_path / "d"
    assert iw.main(["--dest", str(dest)]) == 0
    assert (dest / _name("2026-W43")).exists()
    assert "1" in _log_text(tmp_path)


def test_dest_resolution_order(tmp_path, monkeypatch):
    arg, env, conf = tmp_path / "arg", tmp_path / "env", tmp_path / "conf 폴더"
    assert iw.resolve_dest(None) is None
    _write_config(tmp_path, {"dest": str(conf)})
    assert iw.resolve_dest(None) == conf
    monkeypatch.setenv("AI_JOGAN_DEST", str(env))
    assert iw.resolve_dest(None) == env
    assert iw.resolve_dest(arg) == arg


@pytest.mark.parametrize("content", ["{", "[]", '{"dest": ""}', '{"dest": 3}', '{"other": "x"}'])
def test_unusable_config_means_no_dest(tmp_path, content):
    p = _config(tmp_path)
    p.parent.mkdir(parents=True)
    p.write_text(content, encoding="utf-8")
    assert iw.resolve_dest(None) is None


def test_blank_env_falls_through_to_config(tmp_path, monkeypatch):
    _write_config(tmp_path, {"dest": str(tmp_path / "conf")})
    monkeypatch.setenv("AI_JOGAN_DEST", "  ")
    assert iw.resolve_dest(None) == tmp_path / "conf"


def test_main_without_dest_exits_zero_and_writes_nothing(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: called.append("list") or ["2026-W43"])
    monkeypatch.setattr(iw, "fetch_week", lambda week, **kw: called.append(week) or "x\n")
    assert iw.main([]) == 0
    assert called == []
    assert "도착 폴더 설정 없음" in _log_text(tmp_path)
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert files == ["localappdata/ai-jogan/import.log"]


def test_main_uses_env_then_config(tmp_path, monkeypatch):
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: ["2026-W43"])
    monkeypatch.setattr(iw, "fetch_week", lambda week, **kw: "x\n")
    _write_config(tmp_path, {"dest": str(tmp_path / "conf")})
    assert iw.main([]) == 0
    assert (tmp_path / "conf" / _name("2026-W43")).exists()
    monkeypatch.setenv("AI_JOGAN_DEST", str(tmp_path / "env"))
    assert iw.main([]) == 0
    assert (tmp_path / "env" / _name("2026-W43")).exists()


def test_init_writes_config_and_not_the_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: pytest.fail("--init 은 가져오지 않는다"))
    dest = tmp_path / "내 노트" / "주간"
    assert iw.main(["--init", str(dest)]) == 0
    raw = _config(tmp_path).read_bytes()
    assert b"\r" not in raw and raw.endswith(b"\n")
    assert json.loads(raw.decode("utf-8")) == {"dest": str(dest)}
    assert not dest.exists()
    assert str(_config(tmp_path)) in capsys.readouterr().out
    assert iw.resolve_dest(None) == dest


_RELATIVE = ["rel", "rel/sub", "./x", "C:rel"]


# 빈 환경 변수는 설정 없음, 빈 dest 는 test_unusable_config_means_no_dest 가 본다. 빈 --dest 는 여기서.
@pytest.mark.parametrize("where, value", [("arg", "")] + [(w, v) for w in ("arg", "env", "config")
                                                          for v in _RELATIVE])
def test_non_absolute_dest_is_rejected(tmp_path, monkeypatch, where, value):
    monkeypatch.chdir(tmp_path)
    if where == "env":
        monkeypatch.setenv("AI_JOGAN_DEST", value)
        assert iw.resolve_dest(None) is None
    elif where == "config":
        _write_config(tmp_path, {"dest": value})
        assert iw.resolve_dest(None) is None
    else:
        assert iw.resolve_dest(value) is None
    assert "절대 경로가 아님" in _log_text(tmp_path)


def test_non_absolute_dest_does_not_fall_through(tmp_path, monkeypatch):
    _write_config(tmp_path, {"dest": str(tmp_path / "conf")})
    monkeypatch.setenv("AI_JOGAN_DEST", "rel")
    assert iw.resolve_dest(None) is None
    monkeypatch.delenv("AI_JOGAN_DEST")
    assert iw.resolve_dest("") is None
    assert iw.resolve_dest(None) == tmp_path / "conf"


@pytest.mark.parametrize("argv", [["--dest", ""], ["--dest", "rel"]])
def test_main_with_relative_dest_exits_zero_and_writes_nothing(tmp_path, monkeypatch, argv):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(iw, "list_weeks", lambda **kw: pytest.fail("상대 경로로는 가져오지 않는다"))
    assert iw.main(argv) == 0
    assert "절대 경로가 아님" in _log_text(tmp_path)
    files = [p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()]
    assert files == ["localappdata/ai-jogan/import.log"]


def test_init_message_survives_cp949_console(tmp_path, monkeypatch):
    import io

    buf = io.BytesIO()
    console = io.TextIOWrapper(buf, encoding="cp949", errors="strict", newline="\n")
    monkeypatch.setattr(iw.sys, "stdout", console)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "로컬😀"))  # 경로에 cp949 밖 글자
    dest = tmp_path / "노트—주간😀"
    assert iw.main(["--init", str(dest)]) == 0
    console.flush()
    shown = buf.getvalue().decode("cp949")
    assert "config.json" in shown
    saved = json.loads((tmp_path / "로컬😀" / "ai-jogan" / "config.json").read_text(encoding="utf-8"))
    assert saved == {"dest": str(dest)}


def test_missing_dest_message_survives_cp949_console(tmp_path, monkeypatch):
    import io

    buf = io.BytesIO()
    console = io.TextIOWrapper(buf, encoding="cp949", errors="strict", newline="\n")
    monkeypatch.setattr(iw.sys, "stdout", console)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "로컬😀"))
    assert iw.main([]) == 0
    console.flush()
    assert "--init" in buf.getvalue().decode("cp949")


def test_init_makes_relative_folder_absolute(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert iw.main(["--init", "rel"]) == 0
    saved = Path(json.loads(_config(tmp_path).read_text(encoding="utf-8"))["dest"])
    assert saved.is_absolute() and saved == tmp_path / "rel"


def test_no_default_dest_and_urls_follow_brief():
    assert not hasattr(iw, "DEFAULT_DEST")
    assert iw.config_path().name == "config.json"
    assert iw.RAW_URL.format(week="2026-W43") == (
        "https://raw.githubusercontent.com/serenwoon/ai-jogan/main/weekly/2026-W43.md"
    )


def test_task_xml_is_valid_utf16_with_triggers():
    import xml.etree.ElementTree as ET

    p = Path(__file__).resolve().parents[1] / "tools" / "import_weekly_task.xml"
    raw = p.read_bytes()
    assert raw[:2] == b"\xff\xfe"
    text = raw.decode("utf-16")
    root = ET.fromstring(text.split("?>", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find(".//t:LogonTrigger", ns) is not None
    assert root.find(".//t:CalendarTrigger/t:ScheduleByWeek/t:DaysOfWeek/t:Monday", ns) is not None
    assert root.find(".//t:CalendarTrigger/t:StartBoundary", ns).text.endswith("T09:00:00")
    assert root.find(".//t:StartWhenAvailable", ns).text == "true"
    assert root.find(".//t:Principal/t:LogonType", ns).text == "InteractiveToken"
    assert root.find(".//t:Principal/t:RunLevel", ns).text == "LeastPrivilege"
    assert root.find(".//t:Exec/t:Command", ns).text == (
        r"C:\Users\cas\AppData\Local\Programs\Python\Python312\pythonw.exe"
    )
    assert root.find(".//t:Exec/t:Arguments", ns).text == (
        r'-X utf8 "C:\Users\cas\Documents\GitHub\ai-jogan\tools\import_weekly.py"'
    )
