"""Build preview or production documentation from the same tracked Markdown sources."""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "https://github.com/CiTRuS93/ACED"
SITE_URL = "https://citrus93.github.io/ACED/"


def stage_sources(destination: Path) -> None:
    """Stage only tracked documentation, never local runtime data or private notes."""
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT, text=True).split("\0")
    for name in tracked:
        path = Path(name)
        if not (
            name in {"README.md", "CONTRIBUTING.md", "LICENSE"}
            or (name.startswith("docs/") and path.suffix in {".md", ".png", ".svg", ".gif", ".mmd"})
            or (name.startswith("examples/") and path.suffix == ".py")
        ):
            continue
        target = destination / path
        target.parent.mkdir(parents=True, exist_ok=True)
        source = ROOT / path
        if path.suffix == ".md":
            # MkDocs resolves relative Markdown links, including README -> index.
            # Keep GitHub source links when a target is not part of this preview.
            def local_link(match: re.Match[str], parent: Path = path.parent) -> str:
                relative = match.group(1)
                file, _, fragment = relative.partition("#")
                if file in tracked and (file.startswith("docs/") or file == "CONTRIBUTING.md"):
                    result = os.path.relpath(file, parent).replace(os.sep, "/")
                    return result + ("#" + fragment if fragment else "")
                return match.group(0)

            text = re.sub(
                re.escape(REPOSITORY + "/blob/main/") + r"([^\s)]+)",
                local_link,
                source.read_text(encoding="utf-8"),
            )
            # Use bundled public images rather than requiring a network request.
            text = re.sub(
                re.escape("https://raw.githubusercontent.com/CiTRuS93/ACED/main/") + r"([^\s)]+)",
                local_link,
                text,
            )

            def source_link(match: re.Match[str], parent: Path = path.parent) -> str:
                href = match.group(1)
                candidate = os.path.normpath(str(parent / href.split("#")[0]))
                if candidate in tracked and candidate.startswith(("src/", "tests/")):
                    fragment = "#" + href.split("#", 1)[1] if "#" in href else ""
                    return "](" + REPOSITORY + "/blob/main/" + candidate + fragment + ")"
                return match.group(0)

            text = re.sub(r"\]\(([^\s)]+)\)", source_link, text)
            target.write_text(text, encoding="utf-8")
        else:
            target.write_bytes(source.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--production", action="store_true", help="Build for GitHub Pages")
    args = parser.parse_args()
    output = ROOT / (".docs-site" if args.production else ".docs-preview")
    with tempfile.TemporaryDirectory(prefix="aced-docs-") as temporary:
        staging = Path(temporary) / "source"
        staging.mkdir()
        stage_sources(staging)
        config = {
            "site_name": "ACED documentation",
            "repo_url": REPOSITORY,
            "repo_name": "GitHub repository",
            "edit_uri": "",
            "site_description": (
                "Durable AI coding-agent workflows with verified evidence and human approvals."
            ),
            "extra": {
                "production": args.production,
                "homepage_title": "ACED: Durable AI coding-agent workflows and product experiments",
            },
            "docs_dir": str(staging),
            "site_dir": str(output),
            "use_directory_urls": True,
            "theme": {
                "name": "mkdocs",
                "custom_dir": str(ROOT / "site_theme"),
                "highlightjs": False,
            },
            "plugins": ["search"],
            "markdown_extensions": ["tables", "fenced_code", "toc"],
            "nav": [
                {"Overview": "README.md"},
                {
                    "Start here": [
                        {"Documentation index": "docs/README.md"},
                        {"Offline demo": "docs/manager.md"},
                        {"Python runtime": "docs/runtime.md"},
                        {"Recovery example": "docs/examples/resume-workflow.md"},
                        {"Approval example": "docs/examples/persist-approval.md"},
                        {"Synthetic experiment": "docs/examples/synthetic-experiment.md"},
                    ]
                },
                {
                    "Integrate": [
                        {"Host contract": "docs/integrations.md"},
                        {"CLI runners": "docs/agent-clis.md"},
                        {"Codex configuration": "docs/local-codex.md"},
                        {"Design": "docs/design.md"},
                        {"Qualification": "docs/roadmap.md"},
                    ]
                },
                {"Evidence": "docs/playground-example.md"},
                {"Contribute": "CONTRIBUTING.md"},
            ],
        }
        if args.production:
            config["site_url"] = SITE_URL
        config_path = Path(temporary) / "mkdocs.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "mkdocs", "build", "--strict", "-f", str(config_path)],
            check=True,
        )
    if args.production:
        (output / "robots.txt").write_text(
            f"User-agent: *\nAllow: /ACED/\nSitemap: {SITE_URL}sitemap.xml\n", encoding="utf-8"
        )
        (output / ".nojekyll").touch()
    else:
        for name in ("sitemap.xml", "sitemap.xml.gz"):
            (output / name).unlink(missing_ok=True)
        (output / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    print(f"Documentation build: {output}")


if __name__ == "__main__":
    main()
