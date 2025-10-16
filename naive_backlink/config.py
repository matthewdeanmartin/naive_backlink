# naive_backlink/config.py
"""
Centralized configuration management.

Handles loading defaults, merging in settings from pyproject.toml,
and applying runtime overrides.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, MutableMapping

try:
    import tomli
except ImportError:
    tomli = None  # type: ignore

log = logging.getLogger(__name__)

# This is the list of "well-known ID sites" for whitelist mode.
# By default, it's just a few examples. Users can override this
# in their pyproject.toml.
DEFAULT_WHITELIST = [
    "github.com/*",
    "*.github.io/*",
    "gitlab.com/*",
    "*.gitlab.io/*",
    "keybase.io/*",
    "linkedin.com/in/*",
    "twitter.com/*",
    "x.com/*",
    "facebook.com/*",
    "mastodon.social/*",
    "*.m.wikipedia.org/*",
    "*.wikipedia.org/*",
]

# This is the baseline configuration dictionary.
DEFAULT_CONFIG: dict[str, Any] = {
    "use_playwright_as_fallback": False,
    "max_hops": 3,
    "max_redirects": 5,
    "max_outlinks": 50,
    "timeout": 10.0,
    "max_content_bytes": 1_048_576,  # 1 MiB
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36"
    ),
    # --- Policy & Mode Settings ---
    "only_whitelist": False,  # If True, ONLY crawl URLs matching the whitelist
    "only_rel_me": False,  # If True, ONLY create evidence for rel="me" links
    "trusted": [],  # Domains to boost score (not implemented in scoring yet)
    "whitelist": DEFAULT_WHITELIST,  # Patterns for --only-well-known-id-sites
    # 🔒 Wildcard denylist (fnmatch). Case-insensitive match on host and host+path.
    # This is the default mode (blacklist).
    "blacklist": [
        # Everything under joinmastodon.org (and all its subdomains)
        "joinmastodon.org/*",
        "*.joinmastodon.org/*",
        # GitHub “attractive nuisances” (keep real user/org pages)
        "github.com/sponsors/*",
        "github.com/trending/*",
        "github.com/readme/*",
        "github.com/topics/*",
        "github.com/collections/*",
        "github.com/partners/*",
        "github.com/solutions",
        "github.com/solutions/*",
        "github.com/site",
        "github.com/site/*",
        "github.com/features",
        "github.com/features/*",
        "github.com/enterprise",
        "github.com/enterprise/*",
        "github.com/resources",
        "github.com/resources/*",
        "github.com/marketplace",
        "skills.github.com",
        "*.stackoverflow.co/*",
        "stackoverflow.co",
        "stackoverflow.co/*",
        "stackoverflow.blog*",
        "api.stackexchange.com",
        "data.stackexchange.com",
        "stackoverflow.com/users/signup*",
        # noise?
        "*.forem.com",
        # Sites with strong anti-bot / API blocks
        "twitter.com/*",
        "x.com/*",
        "www.linkedin.com/*",  # HTTP 999, worth reporting but not crawling
        "linkedin.com/*",  # HTTP 999, worth reporting but not crawling
        "reddit.com/*",  # Anti-bot
    ],
    "same_domain_policy": "no-self-domain-or-subdomain",
    "use_registrable_domain": False,
    "cache": {
        "enabled": True,
        "directory": ".naive_backlink_cache",
        "expire_seconds": 24 * 3600,  # 1 day
        "store_errors": False,
    },
}


def _deep_merge_dict(
    base: MutableMapping[str, Any], overrides: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Recursively merge dicts."""
    for key, value in overrides.items():
        if isinstance(value, MutableMapping) and isinstance(
            base.get(key), MutableMapping
        ):
            base[key] = _deep_merge_dict(base[key], value)
        else:
            base[key] = value
    return base


def load_config(pyproject_path: Path | None = None) -> dict[str, Any]:
    """
    Loads configuration from defaults and merges settings from pyproject.toml.

    1. Starts with DEFAULT_CONFIG.
    2. If `tomli` is installed, it looks for `pyproject.toml`.
    3. If `pyproject.toml` is found, it merges settings from
       `[tool.naive_backlink]` over the defaults.
    """
    # Start with a deep copy of the defaults
    config = DEFAULT_CONFIG.copy()
    config["cache"] = DEFAULT_CONFIG["cache"].copy()
    config["blacklist"] = DEFAULT_CONFIG["blacklist"].copy()
    config["whitelist"] = DEFAULT_CONFIG["whitelist"].copy()
    config["trusted"] = DEFAULT_CONFIG["trusted"].copy()

    if tomli is None:
        log.debug("tomli not installed. Skipping pyproject.toml configuration.")
        return config

    if pyproject_path is None:
        pyproject_path = Path.cwd() / "pyproject.toml"

    if not pyproject_path.exists():
        log.debug(
            "No pyproject.toml found at %s. Using default config.", pyproject_path
        )
        return config

    try:
        with pyproject_path.open("rb") as f:
            toml_data = tomli.load(f)

        project_config = toml_data.get("tool", {}).get("naive_backlink", {})
        if project_config:
            log.info("Loading config from %s", pyproject_path)
            config = _deep_merge_dict(config, project_config)  # type: ignore
        else:
            log.debug("No [tool.naive_backlink] section in %s.", pyproject_path)

    except Exception as e:
        log.warning(
            "Failed to load or parse %s: %s. Using default config.",
            pyproject_path,
            e,
            exc_info=True,
        )

    return config
