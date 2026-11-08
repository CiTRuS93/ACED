"""Check generated local links, preview indexing policy and self-contained assets."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1] / ".docs-preview"


class Page(HTMLParser):
    def __init__(self, path: Path):
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.remote_assets: list[str] = []
        self.noindex = False
        self.canonical = False
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
            self.canonical = True
        asset = values.get("src")
        if tag == "link" and values.get("rel") == "stylesheet":
            asset = values.get("href")
        if asset:
            self.links.append(asset)
            if urlsplit(asset).scheme or asset.startswith("//"):
                self.remote_assets.append(asset)


def main() -> None:
    pages = {path: Page(path) for path in ROOT.rglob("*.html")}
    assert pages, "Build docs first"
    errors = []
    for path, page in pages.items():
        if not page.noindex or page.canonical or page.remote_assets:
            errors.append(f"{path}: preview indexing/asset policy violated")
        for href in page.links:
            url = urlsplit(href)
            if url.scheme or url.netloc:
                continue
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
    assert not (ROOT / "sitemap.xml").exists()
    assert not (ROOT / "sitemap.xml.gz").exists()
    assert (ROOT / "robots.txt").read_text() == "User-agent: *\nDisallow: /\n"
    assert not errors, "\n".join(errors)
    print(f"Checked {len(pages)} HTML pages: local links, anchors, assets and noindex policy pass")


if __name__ == "__main__":
    main()
