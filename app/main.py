"""The kroshtan.com web application: server-rendered pages from ``content/``, plus the phase-2 API."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from app import content
from app.rendering import STATIC_DIR, templates

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"), format="%(levelname)s %(name)s: %(message)s")

# The apex is canonical; www redirects to it. Render already does this once both domains are attached, so
# this is the fallback for when only `www` has been attached or Render's behaviour changes.
CANONICAL_HOST = os.environ.get("CANONICAL_HOST", "kroshtan.com")

# No third-party origins at all: fonts are self-hosted and there is no analytics. `connect-src 'self'` is
# what the phase-2 question box streams from.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "X-Content-Type-Options": "nosniff",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class CachedStaticFiles(StaticFiles):
    """Static files with a long cache lifetime; ``static_url`` puts a content hash in every URL."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        """
        Serve the file and mark it cacheable.

        :param path: the requested path
        :param scope: the ASGI scope
        :return: the file response
        """
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Load the site config once at startup so a missing KvK number is logged immediately."""
    content.site_config()
    yield


app = FastAPI(title="kroshtan.com", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", CachedStaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def canonical_host_and_headers(request: Request, call_next: Any) -> Response:
    """
    Redirect ``www.`` to the apex and attach the security headers to every response.

    :param request: the incoming request
    :param call_next: the next handler
    :return: the response
    """
    host = request.headers.get("host", "").split(":")[0].lower()
    if CANONICAL_HOST and host == f"www.{CANONICAL_HOST}":
        target = request.url.replace(scheme="https", hostname=CANONICAL_HOST, port=None)
        return RedirectResponse(str(target), status_code=301)

    response: Response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    if request.headers.get("x-forwarded-proto") == "https":
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


def render(request: Request, template: str, *, status_code: int = 200, **context: Any) -> HTMLResponse:
    """
    Render a page template with the site-wide context.

    :param request: the incoming request
    :param template: template file name
    :param status_code: HTTP status to send
    :return: the HTML response
    """
    site = content.site_config()
    return templates.TemplateResponse(
        request,
        template,
        {"site": site, "path": request.url.path, **context},
        status_code=status_code,
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    """Home: headline, the three services in brief, call to action."""
    return render(request, "home.html", page=content.page("home"), services=content.page("services"))


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request) -> HTMLResponse:
    """About: first-person prose."""
    return render(request, "about.html", page=content.page("about"), body=content.prose("about"))


@app.get("/skills", response_class=HTMLResponse)
async def skills(request: Request) -> HTMLResponse:
    """Skills, grouped."""
    return render(request, "skills.html", page=content.page("skills"))


@app.get("/services", response_class=HTMLResponse)
async def services(request: Request) -> HTMLResponse:
    """Services, followed by teaching and talks."""
    return render(request, "services.html", page=content.page("services"), teaching=content.page("teaching"))


@app.get("/portfolio", response_class=HTMLResponse)
async def portfolio(request: Request) -> HTMLResponse:
    """Publications, projects and speaking."""
    data = content.page("portfolio")
    projects = data.get("projects") or []
    return render(
        request,
        "portfolio.html",
        page=data,
        projects=[p for p in projects if not p.get("example")],
        examples=[p for p in projects if p.get("example")],
    )


@app.get("/contact", response_class=HTMLResponse)
async def contact(request: Request) -> HTMLResponse:
    """Contact details."""
    return render(request, "contact.html", page=content.page("contact"))


@app.get("/healthz", include_in_schema=False)
async def healthz() -> PlainTextResponse:
    """Liveness probe for Render."""
    return PlainTextResponse("ok")


@app.get("/robots.txt", include_in_schema=False)
async def robots() -> PlainTextResponse:
    """Allow everything and point at the sitemap."""
    base = content.site_config().base_url
    return PlainTextResponse(f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n")


PAGES = ["/", "/about", "/skills", "/services", "/portfolio", "/contact"]


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap() -> Response:
    """A minimal XML sitemap of the public pages."""
    base = content.site_config().base_url
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in PAGES)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    return Response(xml, media_type="application/xml")


@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException) -> Response:
    """
    Show a styled page for 404s; other HTTP errors keep FastAPI's JSON body.

    :param request: the incoming request
    :param exc: the raised exception
    :return: the error response
    """
    if exc.status_code == 404 and not request.url.path.startswith("/api/"):
        return render(request, "404.html", status_code=404)
    return PlainTextResponse(str(exc.detail), status_code=exc.status_code)
