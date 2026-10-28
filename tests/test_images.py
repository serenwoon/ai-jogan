from jogan.images import clean_images, find_images, is_image_url, page_image

PAGE = "https://news.example.com/a/1"


def digest_with(sources_by_id):
    corners = {k: {"items": [], "empty_note": None} for k in ("one_line", "automation", "github", "try_this", "term")}
    for n, (item_id, urls) in enumerate(sources_by_id.items()):
        key = list(corners)[n]
        corners[key]["items"].append({"id": item_id, "sources": [{"title": "t", "url": u} for u in urls]})
    return {"corners": corners}


def test_page_image_prefers_og_and_resolves_relative():
    html = (
        '<html><head><meta name="twitter:image" content="https://cdn.example.com/tw.jpg">'
        '<meta property="og:image" content="/img/og.jpg"></head><body></body></html>'
    )
    assert page_image(html, PAGE) == "https://news.example.com/img/og.jpg"


def test_page_image_falls_back_to_twitter_and_ignores_case_and_order():
    html = '<META CONTENT="https://cdn.example.com/tw.jpg" NAME="Twitter:Image">'
    assert page_image(html, PAGE) == "https://cdn.example.com/tw.jpg"


def test_page_image_rejects_http_and_missing():
    assert page_image('<meta property="og:image" content="http://cdn.example.com/a.jpg">', PAGE) is None
    assert page_image("<p>사진 없음</p>", PAGE) is None
    assert page_image('<meta property="og:image" content="">', PAGE) is None


def test_is_image_url():
    assert is_image_url("https://cdn.example.com/a.jpg?x=1")
    for bad in ("http://a.com/a.jpg", "javascript:x", "https://a.com/a b.jpg", 'https://a.com/"x', " https://a.com/a.jpg", "", None, 3):
        assert not is_image_url(bad), bad


def test_find_images_uses_first_source_with_working_image():
    pages = {
        "https://a.com/1": '<meta property="og:image" content="https://cdn.a.com/broken.jpg">',
        "https://b.com/2": '<meta property="og:image" content="https://cdn.b.com/ok.jpg">',
        "https://c.com/3": None,
    }

    def fetch(url):
        if url == "https://boom.com/":
            raise TimeoutError("느림")
        return pages.get(url)

    digest = digest_with({
        "first": ["https://a.com/1", "https://b.com/2"],
        "none": ["https://c.com/3"],
        "boom": ["https://boom.com/", "https://b.com/2"],
        "bad-scheme": ["javascript:alert(1)"],
    })
    found = find_images(digest, fetch, lambda img: "broken" not in img)
    assert found == {"first": "https://cdn.b.com/ok.jpg", "boom": "https://cdn.b.com/ok.jpg"}


def test_find_images_survives_image_check_errors():
    digest = digest_with({"x": ["https://a.com/1"]})

    def check(img):
        raise ConnectionError("끊김")

    assert find_images(digest, lambda u: '<meta property="og:image" content="https://cdn.a.com/a.jpg">', check) == {}


def test_clean_images_keeps_only_safe_entries():
    assert clean_images({"a": "https://e.com/a.jpg", "b": "http://e.com/b.jpg", "c": 1, 2: "https://e.com/x.jpg"}) == {"a": "https://e.com/a.jpg"}
    assert clean_images(["https://e.com/a.jpg"]) == {}
    assert clean_images(None) == {}
