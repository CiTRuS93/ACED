"""Check generated local links, preview indexing policy and self-contained assets."""

import argparse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

from build_docs import SITE_URL

ROOT = Path(__file__).resolve().parents[1] / ".docs-preview"


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.remote_assets: list[str] = []
        self.noindex = False
        self.canonical: str | None = None
        self.feed(path.read_text())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "a" and values.get("href"):
            self.links.append(str(values["href"]))
        if tag == "meta" and values.get("name") == "robots":
            self.noindex = "noindex" in str(values.get("content"))
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical = values.get("href")
        asset = values.get("src")
        if tag == "link" and values.get("rel") == "stylesheet":
            asset = values.get("href")
        if asset:
            self.links.append(asset)
            if urlsplit(asset).scheme or asset.startswith("//"):
                self.remote_assets.append(asset)


def main() -> None:
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if args.production:
        ROOT = ROOT.parent / ".docs-site"
    pages = {path: Page(path) for path in ROOT.rglob("*.html")}
    assert pages, "Build docs first"
    errors = []
    for path, page in pages.items():
        if page.remote_assets:
            errors.append(f"{path}: external asset")
        if args.production:
            if path.name == "404.html":
                if not page.noindex or page.canonical:
                    errors.append("404 must be noindex and have no canonical")
            else:
                expected = SITE_URL + path.relative_to(ROOT).as_posix().removesuffix("index.html")
                if page.noindex or page.canonical != expected:
                    errors.append(f"{path}: incorrect production indexing/canonical")
        elif not page.noindex or page.canonical:
            errors.append(f"{path}: preview indexing policy violated")
        for href in page.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                if not args.production or not href.startswith(SITE_URL):
                    continue
                url = urlsplit("/" + href.removeprefix(SITE_URL))
            elif args.production and url.path.startswith("/ACED/"):
                url = urlsplit(href.removeprefix("/ACED"))
            target = (path.parent / unquote(url.path)).resolve() if url.path else path
            if url.path.startswith("/"):
                target = ROOT / unquote(url.path).lstrip("/")
            if target.is_dir():
                target /= "index.html"
            if not target.is_file():
                errors.append(f"{path.relative_to(ROOT)}: missing {href}")
            elif (
                url.fragment and target in pages and unquote(url.fragment) not in pages[target].ids
            ):
                errors.append(f"{path.relative_to(ROOT)}: missing fragment {href}")
    if args.production:
        sitemap = ET.parse(ROOT / "sitemap.xml")
        locations = {node.text for node in sitemap.findall(".//{*}loc")}
        expected_locations = {page.canonical for page in pages.values() if page.canonical}
        assert locations == expected_locations, "Sitemap must cover every canonical page exactly"
        assert (ROOT / "sitemap.xml.gz").exists()
        assert (ROOT / ".nojekyll").exists()
        assert (ROOT / "robots.txt").read_text() == (
            f"User-agent: *\nAllow: /ACED/\nSitemap: {SITE_URL}sitemap.xml\n"
        )
    else:
        assert not (ROOT / "sitemap.xml").exists()
        assert not (ROOT / "sitemap.xml.gz").exists()
        assert (ROOT / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert not errors, "\n".join(errors)
    print(f"Checked {len(pages)} HTML pages: local links, anchors, assets and indexing policy pass")


if __name__ == "__main__":
    main()
