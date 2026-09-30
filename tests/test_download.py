"""Downloads must not publish incomplete or unverified images."""

import hashlib
import io
import urllib.error

import pytest

from vmtools.download import download
from vmtools.ui import EXIT_CHECKSUM, EXIT_DOWNLOAD, Fail


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, headers=None, url="https://example.org/image.iso"):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}
        self.url = url

    def geturl(self):
        return self.url


def serve(monkeypatch, *responses):
    pending = iter(responses)
    requests = []

    def open_url(request, **kwargs):
        requests.append(request)
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response

    from types import SimpleNamespace
    monkeypatch.setattr("vmtools.download.urllib.request.build_opener", lambda *handlers: SimpleNamespace(open=open_url))
    return requests


def test_short_response_stays_partial(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    serve(monkeypatch, Response(b"short", headers={"Content-Length": "10"}))
    with pytest.raises(Fail) as exc:
        download("https://example.org/image.iso", dest, progress=False)
    assert exc.value.code == EXIT_DOWNLOAD
    assert not dest.exists()
    assert dest.with_suffix(".iso.part").read_bytes() == b"short"


def test_resume_valid_range(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"abc")
    requests = serve(monkeypatch, Response(b"def", status=206, headers={
        "Content-Length": "3", "Content-Range": "bytes 3-5/6",
    }))
    assert download("https://example.org/image.iso", dest, expected_sha256=hashlib.sha256(b"abcdef").hexdigest(), progress=False) == dest
    assert dest.read_bytes() == b"abcdef"
    assert requests[0].get_header("Range") == "bytes=3-"


@pytest.mark.parametrize("content_range", [None, "bytes 0-2/6", "bytes 3-5/5", "garbage"])
def test_invalid_resume_preserves_partial(tmp_path, monkeypatch, content_range):
    dest = tmp_path / "image.iso"
    part = dest.with_suffix(".iso.part")
    part.write_bytes(b"abc")
    response = Response(b"def", status=206, headers={"Content-Length": "3"})
    if content_range is not None:
        response.headers["Content-Range"] = content_range
    serve(monkeypatch, response)
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, expected_sha256="0" * 64, progress=False)
    assert not dest.exists()
    assert part.read_bytes() == b"abc"
    assert response.closed


def test_ignored_range_restarts(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"old")
    serve(monkeypatch, Response(b"fresh", headers={"Content-Length": "5"}))
    download("https://example.org/image.iso", dest, progress=False)
    assert dest.read_bytes() == b"fresh"


def test_416_without_hash_restarts_instead_of_publishing(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    requests = serve(monkeypatch,
        Response(b"stale", headers={"Content-Length": "6", "ETag": '"v1"'}),
        urllib.error.HTTPError("https://example.org/image.iso", 416, "range", {}, None),
        Response(b"fresh", headers={"Content-Length": "5"}),
    )
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    download("https://example.org/image.iso", dest, progress=False)
    assert dest.read_bytes() == b"fresh"
    assert requests[1].get_header("Range") == "bytes=5-"
    assert requests[1].get_header("If-range") == '"v1"'
    assert requests[2].get_header("Range") is None
    assert requests[2].get_header("If-range") is None
    assert not dest.with_suffix(".iso.part.json").exists()


def test_checksum_failure_preserves_destination(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.write_bytes(b"previous image")
    serve(monkeypatch, Response(b"bad", headers={"Content-Length": "3"}))
    with pytest.raises(Fail) as exc:
        download("https://example.org/image.iso", dest, expected_sha256="0" * 64, progress=False)
    assert exc.value.code == EXIT_CHECKSUM
    assert dest.read_bytes() == b"previous image"
    assert not dest.with_suffix(".iso.part").exists()


def test_416_verified_partial_can_be_promoted(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"complete")
    serve(monkeypatch, urllib.error.HTTPError("https://example.org/image.iso", 416, "range", {}, None))
    download("https://example.org/image.iso", dest,
             expected_sha256=hashlib.sha256(b"complete").hexdigest(), progress=False)
    assert dest.read_bytes() == b"complete"


@pytest.mark.parametrize("headers", [
    {"Content-Length": "invalid"},
    {"Content-Length": "-1"},
    {"Content-Length": "9", "Content-Range": "bytes 3-5/6"},
])
def test_bad_framing_closes_response(tmp_path, monkeypatch, headers):
    dest = tmp_path / "image.iso"
    part = dest.with_suffix(".iso.part")
    part.write_bytes(b"abc")
    response = Response(b"def", status=206, headers=headers)
    serve(monkeypatch, response)
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, expected_sha256="0" * 64, progress=False)
    assert response.closed
    assert part.read_bytes() == b"abc"
    assert not dest.exists()


def test_read_error_retains_download_for_retry(tmp_path, monkeypatch):
    class BrokenResponse(Response):
        def read(self, size=-1):
            chunk = super().read(size)
            if not chunk:
                raise TimeoutError("connection lost")
            return chunk

    dest = tmp_path / "image.iso"
    response = BrokenResponse(b"abc", headers={"Content-Length": "6"})
    serve(monkeypatch, response)
    with pytest.raises(Fail) as exc:
        download("https://example.org/image.iso", dest, progress=False)
    assert exc.value.code == EXIT_DOWNLOAD
    assert response.closed
    assert not dest.exists()
    assert dest.with_suffix(".iso.part").read_bytes() == b"abc"


def test_verified_success_replaces_destination(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.write_bytes(b"previous image")
    serve(monkeypatch, Response(b"new", headers={"Content-Length": "3"}))
    download("https://example.org/image.iso", dest,
             expected_sha256=hashlib.sha256(b"new").hexdigest(), progress=False)
    assert dest.read_bytes() == b"new"
    assert not dest.with_suffix(".iso.part").exists()


def redirect_transport(monkeypatch, locations):
    """Exercise urllib's real redirect pipeline without opening network sockets."""
    import email.message
    import urllib.request

    requests = []
    responses = []

    class Transport(urllib.request.HTTPSHandler):
        handler_order = 100

        def https_open(self, request):
            requests.append(request.full_url)
            headers = email.message.Message()
            if locations:
                status, location = locations.pop(0)
                headers['Location'] = location
                body = b''
            else:
                status, body = 200, b'image'
                headers['Content-Length'] = str(len(body))
            response = Response(body, status=status, headers=headers)
            response.code = status
            response.msg = 'test response'
            response.geturl = lambda: request.full_url
            response.info = lambda: headers
            responses.append(response)
            return response

        http_open = https_open

    monkeypatch.setattr(urllib.request, 'HTTPSHandler', Transport)
    monkeypatch.setattr(urllib.request, 'getproxies', lambda: {})
    return requests, responses


@pytest.mark.parametrize('status', [301, 302, 303, 307, 308])
def test_redirect_cannot_downgrade_https(tmp_path, monkeypatch, status):
    requests, responses = redirect_transport(monkeypatch, [(status, 'http://example.org/image.iso')])
    dest = tmp_path / 'image.iso'
    part = dest.with_suffix('.iso.part')
    part.write_bytes(b'previous partial')
    with pytest.raises(Fail) as exc:
        download('https://example.org/image.iso', dest, progress=False)
    assert exc.value.code == EXIT_DOWNLOAD
    assert requests == ['https://example.org/image.iso']
    assert responses[0].closed
    assert part.read_bytes() == b'previous partial'
    assert not dest.exists()


def test_https_and_relative_redirects_still_download(tmp_path, monkeypatch):
    requests, responses = redirect_transport(monkeypatch, [
        (302, 'https://cdn.example.org/start'), (307, '/image.iso'),
    ])
    dest = tmp_path / 'image.iso'
    download('https://example.org/image.iso', dest, progress=False)
    assert requests == [
        'https://example.org/image.iso', 'https://cdn.example.org/start',
        'https://cdn.example.org/image.iso',
    ]
    assert dest.read_bytes() == b'image'
    assert all(response.closed for response in responses)


def test_unvalidated_partial_restarts_instead_of_mixing_versions(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"old")
    requests = serve(monkeypatch, Response(b"newest", headers={"Content-Length": "6"}))
    download("https://example.org/image.iso", dest, progress=False)
    assert requests[0].get_header("Range") is None
    assert dest.read_bytes() == b"newest"


def test_unvalidated_206_does_not_publish_mixed_content(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"old")
    serve(monkeypatch, Response(b"est", status=206, headers={
        "Content-Length": "3", "Content-Range": "bytes 3-5/6",
    }))
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    assert not dest.exists()
    assert dest.with_suffix(".iso.part").read_bytes() == b"old"


def test_strong_etag_resume_keeps_urls_private_and_cleans_state(tmp_path, monkeypatch):
    url = "https://example.org/image.iso?token=private-query"
    dest = tmp_path / "image.iso"
    metadata = dest.with_suffix(".iso.part.json")
    requests = serve(monkeypatch,
        Response(b"abc", headers={"Content-Length": "6", "ETag": '"v1"'}, url=url),
        Response(b"def", status=206, headers={
            "Content-Length": "3", "Content-Range": "bytes 3-5/6", "ETag": '"v1"',
        }, url=url),
    )
    with pytest.raises(Fail):
        download(url, dest, progress=False)
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert url not in metadata.read_text()
    assert "private-query" not in metadata.read_text()
    download(url, dest, progress=False)
    assert requests[1].get_header("Range") == "bytes=3-"
    assert requests[1].get_header("If-range") == '"v1"'
    assert dest.read_bytes() == b"abcdef"
    assert not dest.with_suffix(".iso.part").exists()
    assert not metadata.exists()


@pytest.mark.parametrize("etag", [None, 'W/"v1"', "unquoted", '"bad\r\nheader"'])
def test_partial_without_strong_etag_restarts(tmp_path, monkeypatch, etag):
    dest = tmp_path / "image.iso"
    headers = {"Content-Length": "6", "Last-Modified": "Wed, 30 Sep 2026 00:00:00 GMT"}
    if etag is not None:
        headers["ETag"] = etag
    requests = serve(monkeypatch,
        Response(b"old", headers=headers), Response(b"newest", headers={"Content-Length": "6"}),
    )
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    download("https://example.org/image.iso", dest, progress=False)
    assert requests[1].get_header("Range") is None
    assert requests[1].get_header("If-range") is None
    assert dest.read_bytes() == b"newest"


@pytest.mark.parametrize("etag,url", [
    ('"v2"', "https://example.org/image.iso"),
    (None, "https://example.org/image.iso"),
    ('W/"v1"', "https://example.org/image.iso"),
    ('"v1"', "https://other.example.org/image.iso"),
])
def test_changed_206_identity_preserves_partial(tmp_path, monkeypatch, etag, url):
    dest = tmp_path / "image.iso"
    headers = {"Content-Length": "3", "Content-Range": "bytes 3-5/6"}
    if etag is not None:
        headers["ETag"] = etag
    response = Response(b"est", status=206, headers=headers, url=url)
    serve(monkeypatch,
        Response(b"old", headers={"Content-Length": "6", "ETag": '"v1"'}), response,
    )
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    saved = dest.with_suffix(".iso.part.json").read_bytes()
    with pytest.raises(Fail, match="source identity changed"):
        download("https://example.org/image.iso", dest, progress=False)
    assert response.closed
    assert dest.with_suffix(".iso.part").read_bytes() == b"old"
    assert dest.with_suffix(".iso.part.json").read_bytes() == saved
    assert not dest.exists()


def test_changed_200_restarts_and_saves_new_validator_before_retry(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    requests = serve(monkeypatch,
        Response(b"old", headers={"Content-Length": "6", "ETag": '"v1"'}),
        Response(b"new", headers={"Content-Length": "6", "ETag": '"v2"'}),
        Response(b"est", status=206, headers={
            "Content-Length": "3", "Content-Range": "bytes 3-5/6", "ETag": '"v2"',
        }),
    )
    for _ in range(2):
        with pytest.raises(Fail):
            download("https://example.org/image.iso", dest, progress=False)
    assert dest.with_suffix(".iso.part").read_bytes() == b"new"
    download("https://example.org/image.iso", dest, progress=False)
    assert requests[1].get_header("If-range") == '"v1"'
    assert requests[2].get_header("If-range") == '"v2"'
    assert dest.read_bytes() == b"newest"


def test_changed_requested_url_restarts_even_with_same_etag(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    requests = serve(monkeypatch,
        Response(b"old", headers={"Content-Length": "6", "ETag": '"v1"'}),
        Response(b"newest", headers={"Content-Length": "6", "ETag": '"v1"'},
                 url="https://example.org/other.iso"),
    )
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    download("https://example.org/other.iso", dest, progress=False)
    assert requests[1].get_header("Range") is None
    assert dest.read_bytes() == b"newest"


@pytest.mark.parametrize("contents", ["broken json", "[]", "{}", '{"version": 1, "etag": 123}', "x" * 8193])
def test_invalid_metadata_restarts(tmp_path, monkeypatch, contents):
    dest = tmp_path / "image.iso"
    dest.with_suffix(".iso.part").write_bytes(b"old")
    metadata = dest.with_suffix(".iso.part.json")
    metadata.write_text(contents)
    requests = serve(monkeypatch, Response(b"newest", headers={"Content-Length": "6"}))
    download("https://example.org/image.iso", dest, progress=False)
    assert requests[0].get_header("Range") is None
    assert dest.read_bytes() == b"newest"
    assert not metadata.exists()


def test_hash_backed_resume_rejects_mixed_bytes(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    dest.write_bytes(b"previous image")
    dest.with_suffix(".iso.part").write_bytes(b"old")
    requests = serve(monkeypatch, Response(b"est", status=206, headers={
        "Content-Length": "3", "Content-Range": "bytes 3-5/6", "ETag": '"v2"',
    }))
    with pytest.raises(Fail) as exc:
        download("https://example.org/image.iso", dest,
                 expected_sha256=hashlib.sha256(b"newest").hexdigest(), progress=False)
    assert exc.value.code == EXIT_CHECKSUM
    assert requests[0].get_header("Range") == "bytes=3-"
    assert dest.read_bytes() == b"previous image"
    assert not dest.with_suffix(".iso.part").exists()
    assert not dest.with_suffix(".iso.part.json").exists()


def test_hash_backed_unknown_prefix_cannot_acquire_tail_validator(tmp_path, monkeypatch):
    dest = tmp_path / "image.iso"
    part = dest.with_suffix(".iso.part")
    part.write_bytes(b"old")
    requests = serve(monkeypatch,
        Response(b"e", status=206, headers={
            "Content-Length": "3", "Content-Range": "bytes 3-5/6", "ETag": '"v2"',
        }),
        Response(b"st", status=206, headers={
            "Content-Length": "2", "Content-Range": "bytes 4-5/6", "ETag": '"v2"',
        }),
    )
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest,
                 expected_sha256=hashlib.sha256(b"newest").hexdigest(), progress=False)
    assert part.read_bytes() == b"olde"
    assert not dest.with_suffix(".iso.part.json").exists()
    # Dropping the caller's hash must not turn an unverified prefix into a
    # validator-backed resume, even though its tail carried a strong ETag.
    with pytest.raises(Fail):
        download("https://example.org/image.iso", dest, progress=False)
    assert requests[1].get_header("Range") is None
    assert not dest.exists()
    assert part.read_bytes() == b"olde"
