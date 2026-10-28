from datetime import UTC, datetime, timedelta

from nse_pasta.http import Fetched
from nse_pasta.raw import RawCache, cached_get, sha256_of


class Answers:
    def __init__(self, *answers):
        self.answers, self.asked = list(answers), []

    def get(self, url, params=None, referer=None):
        self.asked.append(url)
        return self.answers.pop(0)


def test_bodies_are_kept_by_sha_and_every_answer_stays(tmp_path):
    cache = RawCache(tmp_path)
    old = datetime(2026, 1, 1, tzinfo=UTC)
    cache.put("u", 200, b"[1]", now=old)
    cache.put("u", 200, b"[1, 2]")
    assert cache.blob_path(sha256_of(b"[1]")).exists()
    again = RawCache(tmp_path)  # read back from the manifest
    assert [again.body(e) for e in again.history("u")] == [b"[1]", b"[1, 2]"]
    assert again.body(again.entry("u")) == b"[1, 2]"


def test_a_torn_manifest_line_is_skipped(tmp_path):
    cache = RawCache(tmp_path)
    cache.put("u", 200, b"x")
    with cache.manifest.open("a", encoding="utf-8") as handle:
        handle.write('{"url": "v", "stat')
    assert list(RawCache(tmp_path).entries()) == ["u"]


def test_cached_get_reuses_and_refuses(tmp_path):
    cache = RawCache(tmp_path)
    client = Answers(Fetched(503), Fetched(200, b"<html>blocked</html>"), Fetched(200, b"[]"))
    valid = lambda body: body.startswith(b"[")  # noqa: E731
    assert cached_get(cache, client, "u", valid=valid).status == 503  # transient: not kept
    assert cached_get(cache, client, "u", valid=valid).status == 0  # a block page: not kept
    assert cache.entry("u") is None
    assert cached_get(cache, client, "u", valid=valid).body == b"[]"
    assert cached_get(cache, client, "u").fetched is False  # documents: asked once
    stale = lambda e: e.fetched_at > datetime.now(UTC) + timedelta(days=1)  # noqa: E731
    assert cached_get(cache, None, "u", reuse=stale).body == b"[]"  # offline: the cache
    assert len(client.asked) == 3


def test_a_404_is_final(tmp_path):
    cache = RawCache(tmp_path)
    client = Answers(Fetched(404, b"not found"))
    assert cached_get(cache, client, "doc").status == 404
    assert cached_get(cache, client, "doc").status == 404 and len(client.asked) == 1
