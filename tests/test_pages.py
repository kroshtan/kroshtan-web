from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app import content
from app.main import PAGES
from app.rendering import mark_todos


@pytest.mark.parametrize("path", PAGES)
def test_every_page_renders(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "<main" in response.text


def test_service_copy_comes_from_content(client: TestClient) -> None:
    services = content.page("services")["services"]
    html = client.get("/services").text
    for service in services:
        assert service["name"] in html
        assert service["price"] in html


def test_home_links_to_each_service(client: TestClient) -> None:
    html = client.get("/").text
    for service in content.page("services")["services"]:
        assert f'href="/services#{service["id"]}"' in html


def test_edited_content_shows_up(client: TestClient, content_dir: Path) -> None:
    home = content_dir / "home.yaml"
    data = yaml.safe_load(home.read_text())
    data["headline"] = "A headline only this test knows."
    home.write_text(yaml.safe_dump(data))
    assert "A headline only this test knows." in client.get("/").text


def test_missing_kvk_shows_a_visible_warning(client: TestClient, content_dir: Path) -> None:
    site = content_dir / "site.yaml"
    data = yaml.safe_load(site.read_text())
    data["kvk_number"] = ""
    site.write_text(yaml.safe_dump(data))
    html = client.get("/").text
    assert 'class="config-warning"' in html
    assert "KvK number missing" in html


def test_filled_kvk_hides_the_warning(client: TestClient, content_dir: Path) -> None:
    site = content_dir / "site.yaml"
    data = yaml.safe_load(site.read_text())
    data["kvk_number"] = "12345678"
    data["vat_id"] = "NL000000000B01"
    site.write_text(yaml.safe_dump(data))
    html = client.get("/").text
    assert 'class="config-warning"' not in html
    assert "12345678" in html
    assert "NL000000000B01" in html


def test_www_redirects_to_apex(client: TestClient) -> None:
    response = client.get("/about?x=1", headers={"host": "www.kroshtan.com"}, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == "https://kroshtan.com/about?x=1"


def test_security_headers(client: TestClient) -> None:
    headers = client.get("/").headers
    assert "default-src 'self'" in headers["content-security-policy"]
    assert headers["x-content-type-options"] == "nosniff"


def test_unknown_page_is_a_styled_404(client: TestClient) -> None:
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert "doesn't exist" in response.text


def test_static_assets_are_versioned_and_cached(client: TestClient) -> None:
    html = client.get("/").text
    assert "/static/css/site.css?v=" in html
    response = client.get("/static/css/site.css")
    assert "immutable" in response.headers["cache-control"]


def test_todo_placeholders_are_highlighted() -> None:
    assert mark_todos("<p>TODO: paper title</p>") == '<p><mark class="todo">TODO: paper title</mark></p>'
    assert mark_todos("<p>Nothing to do here.</p>") == "<p>Nothing to do here.</p>"


def test_projects_render(client: TestClient) -> None:
    html = client.get("/portfolio").text
    for project in content.page("portfolio")["projects"]:
        assert project["title"] in html
    assert 'class="empty-state"' not in html


def test_example_projects_are_labelled(client: TestClient, content_dir: Path) -> None:
    portfolio = content_dir / "portfolio.yaml"
    data = yaml.safe_load(portfolio.read_text())
    data["projects"] = [{"example": True, "title": "Example project", "description": "An example."}]
    portfolio.write_text(yaml.safe_dump(data))
    html = client.get("/portfolio").text
    assert "Example" in html
    assert 'class="empty-state"' in html


def test_sitemap_lists_every_page(client: TestClient) -> None:
    xml = client.get("/sitemap.xml").text
    for path in PAGES:
        assert f"https://kroshtan.com{path}</loc>" in xml
