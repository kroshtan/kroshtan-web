"""
Loading of the site's copy from ``content/``.

Every word on the site lives in ``content/`` so it can be edited without touching a template. YAML holds
structured copy (services, skills, portfolio); Markdown holds prose (about). Long YAML fields are Markdown
too and are rendered through the ``md`` template filter.

Content is read once per process. In development ``make dev`` restarts the server whenever a file under
``content/`` changes, so there is no cache to invalidate by hand.
"""

import logging
import os
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CONTENT_DIR = Path(os.environ.get("CONTENT_DIR", ROOT / "content"))

TODO_MARK = "TODO"


@dataclass(frozen=True)
class SiteConfig:
    """The fields in ``content/site.yaml`` that the code relies on, validated once at startup."""

    name: str
    email: str
    location: str
    github_url: str
    source_url: str
    linkedin_url: str | None
    kvk_number: str | None
    vat_id: str | None
    base_url: str
    description: str
    nav: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _clean(value: Any) -> str | None:
    """
    Normalise an optional config value: empty strings and ``TODO`` placeholders count as unset.

    :param value: the raw YAML value
    :return: the stripped string, or ``None`` when it is not filled in
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper().startswith(TODO_MARK):
        return None
    return text


def read_yaml(name: str) -> dict[str, Any]:
    """
    Read one YAML file from the content directory.

    :param name: the file name, e.g. ``services.yaml``
    :return: the parsed mapping (empty when the file is empty)
    :raises TypeError: when the file's top level is not a mapping
    """
    data = yaml.safe_load((CONTENT_DIR / name).read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise TypeError(f"content/{name} must contain a mapping at the top level")
    return data


def read_markdown(name: str) -> str:
    """
    Read one Markdown file from the content directory.

    :param name: the file name, e.g. ``about.md``
    :return: the raw Markdown source
    """
    return (CONTENT_DIR / name).read_text(encoding="utf-8")


@cache
def site_config() -> SiteConfig:
    """
    Load and validate ``content/site.yaml``.

    The KvK number is required by Dutch law (Handelsregisterbesluit art. 42) on a business website. It is
    not a hard startup failure — a missing number should not take the site down — but it produces a
    warning that the footer shows to every visitor until it is filled in, which is hard to overlook.

    :return: the validated config
    """
    raw = read_yaml("site.yaml")
    warnings: list[str] = []

    kvk = _clean(raw.get("kvk_number"))
    if kvk is None:
        warnings.append(
            "KvK number missing — required on a Dutch business website. Set kvk_number in content/site.yaml."
        )
    elif not (kvk.isdigit() and len(kvk) == 8):
        warnings.append(f"KvK number {kvk!r} does not look like an 8-digit Chamber of Commerce number.")

    for message in warnings:
        logger.warning(message)

    return SiteConfig(
        name=raw["name"],
        email=raw["email"],
        location=raw["location"],
        github_url=raw["github_url"],
        source_url=raw["source_url"],
        linkedin_url=_clean(raw.get("linkedin_url")),
        kvk_number=kvk,
        vat_id=_clean(raw.get("vat_id")),
        base_url=raw["base_url"].rstrip("/"),
        description=raw["description"],
        nav=raw.get("nav") or [],
        warnings=warnings,
    )


@cache
def page(name: str) -> dict[str, Any]:
    """
    Load the YAML copy for one page, cached for the life of the process.

    :param name: the page name without extension, e.g. ``services``
    :return: the page's content mapping
    """
    return read_yaml(f"{name}.yaml")


@cache
def prose(name: str) -> str:
    """
    Load a Markdown prose file, cached for the life of the process.

    :param name: the file name without extension, e.g. ``about``
    :return: the raw Markdown source
    """
    return read_markdown(f"{name}.md")


def clear_caches() -> None:
    """Forget everything loaded so far; used by tests that point ``CONTENT_DIR`` elsewhere."""
    site_config.cache_clear()
    page.cache_clear()
    prose.cache_clear()
