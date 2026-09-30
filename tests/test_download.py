"""Downloads must not publish incomplete or unverified images."""

import hashlib
import io
import urllib.error

import pytest

from vmtools.download import download
from vmtools.ui import EXIT_CHECKSUM, EXIT_DOWNLOAD, Fail


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = headers or {}


def serve(monkeypatch, *responses):
    pending = iter(responses)
    requests = []

    def open_url(request, **kwargs):
        requests.append(request)
        response = next(pending)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr("vmtools.download.urllib.request.urlopen", open_url)
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
    assert download("https://example.org/image.iso", dest, progress=False) == dest
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
        download("https://example.org/image.iso", dest, progress=False)
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
    dest.with_suffix(".iso.part").write_bytes(b"stale")
    requests = serve(monkeypatch,
        urllib.error.HTTPError("https://example.org/image.iso", 416, "range", {}, None),
        Response(b"fresh", headers={"Content-Length": "5"}),
    )
    download("https://example.org/image.iso", dest, progress=False)
    assert dest.read_bytes() == b"fresh"
    assert requests[1].get_header("Range") is None


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
        download("https://example.org/image.iso", dest, progress=False)
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
