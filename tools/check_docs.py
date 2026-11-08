"""Check generated local links, preview indexing policy and self-contained assets."""

import argparse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml
from build_docs import REPOSITORY, SITE_URL

ROOT = Path(__file__).resolve().parents[1] / ".docs-preview"


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__()
        self.titles: list[str] = []
        self.descriptions: list[str] = []
        self.in_title = False
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.remote_assets: list[str] = []
        self.noindex = False
        self.canonical: str | None = None
        self.feed(path.read_text())

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "title":
            self.in_title = True
            self.titles.append("")
        if tag == "meta" and values.get("name") == "description":
            self.descriptions.append(values.get("content") or "")
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

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.titles[-1] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False


def check_problem_guide_metadata(root: Path, pages: dict[Path, Page]) -> list[str]:
    errors = []
    descriptions = []
    for name in (
        "examples/resume-workflow",
        "examples/persist-approval",
        "agent-clis",
        "playground-example",
    ):
        source = Path(__file__).resolve().parents[1] / f"docs/{name}.md"
        metadata = yaml.safe_load(source.read_text(encoding="utf-8").split("---", 2)[1])
        page = pages[root / f"docs/{name}/index.html"]
        title, description = metadata["title"], metadata["description"]
        if not title or page.titles != [f"{title} - ACED documentation"]:
            errors.append(f"{name}: missing or incorrect problem-specific title")
        if not description or page.descriptions != [description]:
            errors.append(f"{name}: missing or incorrect page description")
        descriptions.append(description)
    if len(set(descriptions)) != len(descriptions):
        errors.append("Problem guides must have distinct descriptions")
    return errors


def main() -> None:
    global ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if args.production:
        ROOT = ROOT.parent / ".docs-site"
    pages = {path: Page(path) for path in ROOT.rglob("*.html")}
    assert pages, "Build docs first"
    errors = check_problem_guide_metadata(ROOT, pages)
    homepage = pages[ROOT / "index.html"]
    if homepage.titles != ["ACED: Durable AI coding-agent workflows and product experiments"]:
        errors.append("Homepage must have its descriptive ACED title")
    for path, page in pages.items():
        if len(page.titles) != 1 or not page.titles[0].strip():
            errors.append(f"{path}: missing or duplicate title")
        if len(page.descriptions) > 1:
            errors.append(f"{path}: duplicate descriptions")
        if REPOSITORY not in page.links:
            errors.append(f"{path}: missing direct repository link")
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
