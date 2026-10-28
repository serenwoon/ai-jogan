"""항목마다 원문 페이지의 대표 이미지(og:image) 주소를 찾는다.

사진은 저장소에 복사하지 않고 원문 사이트의 주소를 그대로 건다(링크 미리보기와 같은 방식).
찾지 못하면 그 항목은 사진 없이 나간다. 이 단계의 실패로 그날 호가 멈추지는 않는다.
"""
from collections.abc import Callable
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from jogan.digest import CORNERS

# 앞에 있을수록 먼저 쓴다
IMAGE_KEYS = ("og:image:secure_url", "og:image", "og:image:url", "twitter:image", "twitter:image:src")
MAX_PAGE_BYTES = 1_500_000
SOURCES_PER_ITEM = 2
USER_AGENT = "Mozilla/5.0 (compatible; ai-jogan/0.1; +https://github.com/serenwoon/ai-jogan)"


class _MetaImages(HTMLParser):
    # 자체 상태는 _jg_ 접두사로 둔다(render._TextExtractor 주석 참고).
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._jg_found: dict[str, str] = {}

    def handle_starttag(self, tag, attrs):
        if tag != "meta":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        key = (a.get("property") or a.get("name") or "").strip().lower()
        content = a.get("content", "").strip()
        if key in IMAGE_KEYS and content and key not in self._jg_found:
            self._jg_found[key] = content


def is_image_url(url) -> bool:
    """https 주소만 받는다. http 사진은 Pages(https)에서 섞인 콘텐츠로 막힌다."""
    if not isinstance(url, str) or not url or url != url.strip():
        return False
    if any(c in url for c in "\"'<> \t\r\n"):
        return False
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.netloc)


def page_image(html: str, page_url: str) -> str | None:
    """HTML의 meta 태그에서 대표 이미지 주소를 찾아 절대 주소로 돌려준다."""
    parser = _MetaImages()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    for key in IMAGE_KEYS:
        if key in parser._jg_found:
            url = urljoin(page_url, parser._jg_found[key])
            if is_image_url(url):
                return url
    return None


def _source_urls(item: dict) -> list[str]:
    out = []
    for src in item.get("sources") or []:
        url = src.get("url") if isinstance(src, dict) else None
        if isinstance(url, str) and urlsplit(url.strip()).scheme in ("http", "https"):
            out.append(url.strip())
    return out[:SOURCES_PER_ITEM]


def find_images(digest: dict, fetch_page: Callable[[str], str | None],
                image_ok: Callable[[str], bool]) -> dict[str, str]:
    """{항목 id: 사진 주소}. 원문을 앞에서부터 보고, 실제로 열리는 사진이 있는 첫 원문을 쓴다."""
    found: dict[str, str] = {}
    for key in CORNERS:
        for item in digest["corners"][key]["items"]:
            for url in _source_urls(item):
                try:
                    html = fetch_page(url)
                    image = page_image(html, url) if html else None
                    if image and image_ok(image):
                        found[item["id"]] = image
                        break
                except Exception:
                    continue
    return found


def clean_images(data) -> dict[str, str]:
    """images.json 을 읽어 쓸 수 있는 것만 남긴다. 깨진 파일이면 빈 사전."""
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and is_image_url(v)}


# ---------- 실제 네트워크 (테스트에서는 쓰지 않는다) ----------

def fetch_page(url: str) -> str | None:
    import requests

    with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10, stream=True) as resp:
        if resp.status_code != 200:
            return None
        if "html" not in resp.headers.get("content-type", "").lower():
            return None
        data = b""
        for chunk in resp.iter_content(65536):
            data += chunk
            if len(data) >= MAX_PAGE_BYTES:
                break
    return data.decode(resp.encoding or "utf-8", errors="replace")


def image_ok(url: str) -> bool:
    """사진 주소가 실제로 사진을 돌려주는지 본다. SVG는 메일에서 안 보이는 곳이 많아 뺀다."""
    import requests

    with requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10, stream=True) as resp:
        kind = resp.headers.get("content-type", "").lower()
        return resp.status_code == 200 and kind.startswith("image/") and "svg" not in kind
