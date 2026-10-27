from datetime import date
from email import message_from_bytes, policy

import pytest

from jogan.mail import MailConfigError, failure_mail, send_mail

ENV = {"NAVER_USER": "sender@naver.com", "NAVER_APP_PASSWORD": "app-pw", "MAIL_TO": "me@example.com"}


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None):
        self.host, self.port, self.timeout = host, port, timeout
        self.logins = []
        self.sent = []
        self.closed = False
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False

    def login(self, user, password):
        self.logins.append((user, password))

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def _reset():
    FakeSMTP.instances = []


def test_send_uses_naver_ssl_and_logs_in():
    send_mail("제목", "<p>본문</p>", "본문", ENV, smtp_factory=FakeSMTP)
    smtp = FakeSMTP.instances[0]
    assert (smtp.host, smtp.port) == ("smtp.naver.com", 465)
    assert smtp.logins == [("sender@naver.com", "app-pw")]
    assert len(smtp.sent) == 1 and smtp.closed
    msg = smtp.sent[0]
    assert msg["From"] == "sender@naver.com"
    assert msg["To"] == "me@example.com"


@pytest.mark.parametrize("missing", ["NAVER_USER", "NAVER_APP_PASSWORD", "MAIL_TO"])
def test_missing_env_raises(missing):
    env = {k: v for k, v in ENV.items() if k != missing}
    with pytest.raises(MailConfigError) as e:
        send_mail("s", "<p>h</p>", "t", env, smtp_factory=FakeSMTP)
    assert missing in str(e.value)
    assert FakeSMTP.instances == []


def test_empty_env_value_raises():
    env = {**ENV, "NAVER_APP_PASSWORD": ""}
    with pytest.raises(MailConfigError):
        send_mail("s", "<p>h</p>", "t", env, smtp_factory=FakeSMTP)
    assert FakeSMTP.instances == []


def test_message_is_multipart_with_utf8_subject():
    subject = "AI 조간 10/28(수) — 스킬이 표준이 됐다"
    send_mail(subject, "<p>안녕</p>", "안녕", ENV, smtp_factory=FakeSMTP)
    raw = FakeSMTP.instances[0].sent[0].as_bytes()
    msg = message_from_bytes(raw, policy=policy.default)
    assert msg["Subject"] == subject
    assert msg.get_content_type() == "multipart/alternative"
    assert msg.get_body(("plain",)).get_content().strip() == "안녕"
    assert "<p>안녕</p>" in msg.get_body(("html",)).get_content()


def test_comma_separated_recipients_are_split():
    env = {**ENV, "MAIL_TO": "a@example.com, b@example.com"}
    send_mail("s", "<p>h</p>", "t", env, smtp_factory=FakeSMTP)
    msg = FakeSMTP.instances[0].sent[0]
    assert [a.addr_spec for a in msg["To"].addresses] == ["a@example.com", "b@example.com"]


def test_failure_mail_mentions_stage_run_url_and_token_hint():
    subject, html, text = failure_mail(date(2026, 10, 28), "edit", "https://github.com/x/y/actions/runs/1")
    assert subject == "AI 조간 10/28(수) — 실패"
    for body in (html, text):
        assert "edit" in body
        assert "https://github.com/x/y/actions/runs/1" in body
        assert "claude setup-token" in body
        assert "CLAUDE_CODE_OAUTH_TOKEN" in body
    assert 'href="https://github.com/x/y/actions/runs/1"' in html
    assert "<style" not in html


def test_failure_mail_escapes_stage_and_run_url():
    _, html, _ = failure_mail(date(2026, 10, 28), "<b>x</b>&", 'https://e.com/?a=1&b="2"<s>')
    assert "<b>x</b>" not in html and "<s>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;&amp;" in html
    assert "a=1&amp;b=&quot;2&quot;&lt;s&gt;" in html
