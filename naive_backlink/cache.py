from __future__ import annotations

import logging

"""
File-backed HTTP response cache.

- Storage: diskcache.Cache (robust, fast, cross-platform).
- Location: default is a visible folder in CWD; optionally an OS-specific app cache dir via platformdirs.
- Scope: only 200 OK HTML pages (text/html). No binary assets. No error pages by default.
"""

from dataclasses import dataclass
from typing import Any, Optional

# from diskcache import Cache as _DiskCache
import diskcache
from platformdirs import user_cache_dir as _user_cache_dir

log = logging.getLogger(__name__)


@dataclass
class CacheConfig:
    enabled: bool = True
    # Either a concrete directory path, or special marker "os-default"
    # for an OS-specific global cache location.
    directory: str = ".naive_backlink_cache"
    expire_seconds: int = 24 * 3600  # 1 day
    store_errors: bool = False  # keep simple: default = do not cache non-200


class FileCache:
    """
    Thin wrapper over diskcache with a tiny, explicit key/value contract.
    Keys: normalized URL strings.
    Values: dict with: final_url, status, headers (lowercased keys), text, content_type.
    """

    def __init__(self, cfg: CacheConfig, app_name: str = "naive_backlink"):
        self.cfg = cfg

        if not cfg.enabled:
            log.warning("Caching not enabled")
            return

        self._cache = None
        self.app_name = app_name
        self.create_cache_object()

    def create_cache_object(self):
        if self._cache is not None and self._cache.directory:
            return
        directory = self.cfg.directory
        if directory == "os-default":
            if _user_cache_dir is not None:
                directory = _user_cache_dir(self.app_name, appauthor=False)
            else:
                directory = ".naive_backlink_cache"  # fallback visible

        log.warning(f"Cache at {directory}")
        self._cache = diskcache.Cache(directory)
        if self._cache is None:
            raise Exception("create failed.")
        if not self._cache.directory:
            raise Exception("create failed.")

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()

    # ---- Public API ---------------------------------------------------------

    def get(self, url: str) -> Optional[dict[str, Any]]:

        if self._cache is None or not self._cache.directory:
            log.warning("Cache disabled")
            return None
        return self._cache.get(url)  # respects internal expirations

    def set_html_ok(
        self,
        url: str,
        *,
        final_url: str,
        status: int,
        headers: dict[str, str],
        text: str,
        content_type: str,
    ) -> None:
        if self._cache is None or not self._cache.directory:
            log.warning("Cache disabled, no self._cache")
            return
        if status != 200 and not self.cfg.store_errors:
            log.warning(f"Not caching error, got {status}")
            return
        self._cache.set(
            url,
            {
                "final_url": final_url,
                "status": status,
                "headers": {k.lower(): v for k, v in (headers or {}).items()},
                "text": text,
                "content_type": (
                    content_type.lower() if isinstance(content_type, str) else ""
                ),
            },
            expire=self.cfg.expire_seconds,
        )
