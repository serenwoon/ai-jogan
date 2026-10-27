"""네이버 SMTP 발송과 실패 알림 메일."""
import smtplib
from collections.abc import Mapping
from datetime import date
from email.message import EmailMessage
from html import escape

from jogan.dates import korean_date_label

SMTP_HOST = "smtp.naver.com"
SMTP_PORT = 465
_REQUIRED = ("NAVER_USER", "NAVER_APP_PASSWORD", "MAIL_TO")

TOKEN_HINT = "편집 단계에서 인증 오류면 노트북에서 `claude setup-token`을 다시 실행해 `CLAUDE_CODE_OAUTH_TOKEN`을 바꾼다"


class MailConfigError(RuntimeError):
    """발송에 필요한 환경 변수가 없거나 비어 있다."""


def send_mail(
    subject: str,
    html: str,
    text: str,
    env: Mapping[str, str],
    smtp_factory=smtplib.SMTP_SSL,
) -> None:
    missing = [name for name in _REQUIRED if not env.get(name)]
    if missing:
        raise MailConfigError("환경 변수가 없습니다: " + ", ".join(missing))

    recipients = [a.strip() for a in env["MAIL_TO"].split(",") if a.strip()]
    if not recipients:
        raise MailConfigError("환경 변수가 없습니다: MAIL_TO")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = env["NAVER_USER"]
    msg["To"] = ", ".join(recipients)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    with smtp_factory(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(env["NAVER_USER"], env["NAVER_APP_PASSWORD"])
        smtp.send_message(msg)


def failure_mail(d: date, stage: str, run_url: str) -> tuple[str, str, str]:
    """실패 알림 메일 (제목, HTML, 텍스트). 인라인 style만 쓴다."""
    subject = f"AI 조간 {korean_date_label(d)} — 실패"
    s, u, hint = escape(stage), escape(run_url), escape(TOKEN_HINT)
    html = (
        '<div style="font-family:sans-serif;font-size:15px;line-height:1.6;color:#222;">'
        f'<h2 style="font-size:18px;margin:0 0 12px;">{escape(subject)}</h2>'
        f'<p style="margin:0 0 8px;">실패한 단계: <strong>{s}</strong></p>'
        f'<p style="margin:0 0 8px;">실행 기록: <a href="{u}">{u}</a></p>'
        f'<p style="margin:0;color:#555;">{hint}</p>'
        "</div>"
    )
    text = (
        f"{subject}\n\n"
        f"실패한 단계: {stage}\n"
        f"실행 기록: {run_url}\n\n"
        f"{TOKEN_HINT}\n"
    )
    return subject, html, text
