import os
import pathlib


from naive_backlink.cache import CacheConfig, FileCache


def test_set_and_get_html_ok_lowercases_headers_and_content_type(tmp_path):
    cfg = CacheConfig(
        enabled=True,
        directory=str(tmp_path / "nb_cache"),
        expire_seconds=30,
        store_errors=False,
    )
    fc = FileCache(cfg, app_name="naive_backlink_test")

    url = "https://example.org/page"
    fc.set_html_ok(
        url,
        final_url=url,
        status=200,
        headers={"Content-Type": "Text/HTML; Charset=UTF-8", "X-RateLimit": "10"},
        text="<html><body>ok</body></html>",
        content_type="Text/HTML; Charset=UTF-8",
    )

    got = fc.get(url)
    assert got is not None
    assert got["final_url"] == url
    assert got["status"] == 200
    # headers keys lowercased
    assert "content-type" in got["headers"]
    assert "x-ratelimit" in got["headers"]
    # content-type lowercased
    assert got["content_type"] == "text/html; charset=utf-8"
    assert "ok" in got["text"]


def test_not_caching_errors_by_default(tmp_path):
    cfg = CacheConfig(
        enabled=True,
        directory=str(tmp_path / "nb_cache"),
        expire_seconds=30,
        store_errors=False,
    )
    fc = FileCache(cfg)

    url = "https://example.org/bad"
    # Should be ignored because status != 200 and store_errors = False
    fc.set_html_ok(
        url,
        final_url=url,
        status=404,
        headers={"Content-Type": "text/html"},
        text="not found",
        content_type="text/html",
    )
    assert fc.get(url) is None


def test_caching_errors_when_enabled(tmp_path):
    cfg = CacheConfig(
        enabled=True,
        directory=str(tmp_path / "nb_cache"),
        expire_seconds=30,
        store_errors=True,  # now we keep non-200
    )
    fc = FileCache(cfg)

    url = "https://example.org/bad"
    fc.set_html_ok(
        url,
        final_url=url,
        status=500,
        headers={"Content-Type": "text/html"},
        text="server down",
        content_type="text/html",
    )
    got = fc.get(url)
    assert got is not None
    assert got["status"] == 500
    assert got["text"] == "server down"


def test_os_default_directory_uses_platformdirs(tmp_path, monkeypatch):
    # Monkeypatch the imported symbol used in cache.py
    from naive_backlink import cache as cache_mod

    target_dir = tmp_path / "os_default_here"

    def fake_user_cache_dir(app_name: str, appauthor: bool = False):
        # mirror platformdirs signature
        return str(target_dir)

    monkeypatch.setattr(cache_mod, "_user_cache_dir", fake_user_cache_dir, raising=True)

    cfg = CacheConfig(
        enabled=True,
        directory="os-default",
        expire_seconds=30,
        store_errors=False,
    )
    fc = FileCache(cfg, app_name="naive_backlink_test")
    # Force creation (constructor already calls it, but this is harmless)
    fc.create_cache_object()

    # diskcache exposes .directory; ensure it is our patched path
    # Accept either the exact path or a normalized string.
    cache_dir = pathlib.Path(fc._cache.directory)  # type: ignore[attr-defined]
    assert cache_dir == target_dir


def test_create_cache_object_idempotent(tmp_path):
    cfg = CacheConfig(
        enabled=True,
        directory=str(tmp_path / "nb_cache"),
        expire_seconds=30,
        store_errors=False,
    )
    fc = FileCache(cfg)
    first_dir = str(fc._cache.directory)  # type: ignore[attr-defined]
    # Call twice; should not recreate or change directory
    fc.create_cache_object()
    second_dir = str(fc._cache.directory)  # type: ignore[attr-defined]
    assert first_dir == second_dir
    assert os.path.isdir(first_dir)


def test_disabled_cache_does_not_initialize_internal_cache():
    cfg = CacheConfig(
        enabled=False,
        directory=".should_not_be_used",
        expire_seconds=30,
        store_errors=False,
    )
    fc = FileCache(cfg)
    # Implementation detail: when disabled, constructor returns early
    # and _cache is never created.
    assert not hasattr(fc, "_cache")
