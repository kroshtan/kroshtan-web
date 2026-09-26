"""
Jinja environment and the filters the templates use.

Content is owned by the repository, not by visitors, so rendering its Markdown to raw HTML is safe. Nothing a
visitor submits ever passes through these filters.
"""

import hashlib
import re
from functools import cache
from pathlib import Path

import markdown
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.content import TODO_MARK

APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

# A TODO placeholder runs to the end of its sentence or HTML text node, whichever comes first.
_TODO_RE = re.compile(rf"\b{TODO_MARK}\b[^<.]*\.?")


def mark_todos(html: str) -> str:
    """
    Highlight ``TODO`` placeholders so unfinished copy is impossible to miss on the page.

    :param html: rendered HTML
    :return: the same HTML with each placeholder wrapped in ``<mark class="todo">``
    """
    return _TODO_RE.sub(lambda m: f'<mark class="todo">{m.group(0).strip()}</mark>', html)


def md_block(text: str | None) -> Markup:
    """
    Render Markdown to block-level HTML.

    :param text: Markdown source
    :return: safe HTML
    """
    if not text:
        return Markup("")
    return Markup(mark_todos(markdown.markdown(str(text), extensions=["smarty"])))


def md_inline(text: str | None) -> Markup:
    """
    Render a single line of Markdown without the surrounding paragraph.

    :param text: Markdown source
    :return: safe HTML
    """
    html = str(md_block(text))
    if html.startswith("<p>") and html.endswith("</p>") and html.count("<p>") == 1:
        html = html[3:-4]
    return Markup(html)


def is_todo(value: object) -> bool:
    """
    Tell whether a content value is still an unfilled placeholder.

    :param value: any content value
    :return: ``True`` for empty values and strings starting with ``TODO``
    """
    return value is None or str(value).strip() == "" or str(value).strip().upper().startswith(TODO_MARK)


@cache
def _file_hash(path: str) -> str:
    return hashlib.sha256((STATIC_DIR / path).read_bytes()).hexdigest()[:10]


def static_url(path: str) -> str:
    """
    URL of a static asset with a content hash, so it can be cached forever and still update on deploy.

    :param path: path relative to ``app/static``
    :return: the versioned URL
    """
    return f"/static/{path}?v={_file_hash(path)}"


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.filters["md"] = md_block
templates.env.filters["mdi"] = md_inline
templates.env.tests["todo"] = is_todo
templates.env.globals["static_url"] = static_url
