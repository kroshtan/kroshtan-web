"""
The context the "Can I help with this?" assistant judges against.

Two sources, assembled on the server:

1. The site's public content, read from ``content/``: exactly what any visitor can already see.
2. Private notes from ``PRIVATE_DIR`` (default ``private/``, gitignored): Markdown or text files Floris chooses
   to add, e.g. project details that are not on the site. On Render these are Secret Files, which Render mounts
   at ``/etc/secrets/``; set ``PRIVATE_DIR=/etc/secrets`` there. Information from these files may appear in
   answers, so put nothing in them that must stay confidential.

Both are read once and cached: they change only with a deploy.
"""

import logging
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app import content

logger = logging.getLogger(__name__)

PRIVATE_SUFFIXES = {".md", ".markdown", ".txt"}
# The committed placeholder that explains the folder; it is documentation, not context.
PRIVATE_IGNORED = {"README.md"}
PROMPT_PATH = content.ROOT / "prompts" / "assess.md"

# Public pages that describe what Floris does. Home and contact are layout and calls to action, not facts.
PUBLIC_YAML = ["about", "skills", "services", "teaching", "portfolio"]


@dataclass(frozen=True)
class AssistantContext:
    public: str
    private: str
    private_files: tuple[str, ...]


def private_dir() -> Path:
    """
    The folder private context is read from.

    :return: ``$PRIVATE_DIR`` if set, else ``private/`` in the repository
    """
    return Path(os.environ.get("PRIVATE_DIR") or content.ROOT / "private")


def _strip_todos(value: object) -> object:
    """
    Drop unfilled ``TODO`` placeholders, so the model never sees (or repeats) them as facts.

    :param value: parsed YAML
    :return: the same structure without placeholder strings
    """
    if isinstance(value, dict):
        return {k: _strip_todos(v) for k, v in value.items() if not _is_placeholder(v)}
    if isinstance(value, list):
        return [_strip_todos(v) for v in value if not _is_placeholder(v)]
    return value


def _is_placeholder(value: object) -> bool:
    return isinstance(value, str) and value.strip().upper().startswith(content.TODO_MARK)


def load_public() -> str:
    """
    Serialise the site's public content for the model.

    :return: the about prose followed by each page's YAML, placeholders removed
    """
    parts = [f'<page name="about-prose">\n{content.read_markdown("about.md").strip()}\n</page>']
    for name in PUBLIC_YAML:
        data = _strip_todos(content.read_yaml(f"{name}.yaml"))
        body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100).strip()
        parts.append(f'<page name="{name}">\n{body}\n</page>')
    return "\n\n".join(parts)


def load_private(directory: Path | None = None) -> tuple[str, tuple[str, ...]]:
    """
    Read every Markdown or text file in the private folder, in name order.

    A missing or empty folder is normal (the site works without it) and yields an empty string.

    :param directory: folder to read; defaults to :func:`private_dir`
    :return: the concatenated documents and the names of the files read
    """
    directory = directory or private_dir()
    if not directory.is_dir():
        return "", ()

    parts, names = [], []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix.lower() not in PRIVATE_SUFFIXES or path.name in PRIVATE_IGNORED:
            continue
        try:
            text = path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError) as exc:
            logger.warning("private context: skipping %s (%s)", path.name, type(exc).__name__)
            continue
        if text:
            parts.append(f'<document name="{path.name}">\n{text}\n</document>')
            names.append(path.name)
    return "\n\n".join(parts), tuple(names)


@cache
def assistant_context() -> AssistantContext:
    """
    Assemble both sources once per process.

    :return: the cached context
    """
    private, names = load_private()
    logger.info("assistant context: public content + %d private file(s)", len(names))
    return AssistantContext(public=load_public(), private=private, private_files=names)


@cache
def system_prompt() -> str:
    """
    The full system prompt: the editable instructions from ``prompts/assess.md``, then the context.

    Everything here is identical for every request, so it is sent as one cached block.

    :return: the system prompt text
    """
    ctx = assistant_context()
    instructions = PROMPT_PATH.read_text(encoding="utf-8").strip()
    site = content.site_config()
    sections = [
        instructions,
        f"<contact_email>{site.email}</contact_email>",
        f"<public_site_content>\n{ctx.public}\n</public_site_content>",
    ]
    if ctx.private:
        sections.append(f"<private_notes>\n{ctx.private}\n</private_notes>")
    return "\n\n".join(sections)


def clear_caches() -> None:
    """Forget the assembled context; used by tests."""
    assistant_context.cache_clear()
    system_prompt.cache_clear()
