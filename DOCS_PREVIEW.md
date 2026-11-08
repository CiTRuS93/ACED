# Documentation builds and publication

README, contribution guide and tracked `docs/` Markdown remain the only content
sources. The build stages documentation and public assets in a temporary directory
and uses MkDocs' bundled theme and local search. It does not edit the sources or
include untracked files, runtime databases, or private notes. Code references link
to GitHub. No analytics or CDN assets are loaded.

## Build and inspect

Use Python 3.12+ from the repository root:

```bash
python -m venv .venv-docs
.venv-docs/bin/python -m pip install --require-hashes -r requirements-docs.lock
.venv-docs/bin/python tools/test_docs.py
.venv-docs/bin/python tools/build_docs.py
.venv-docs/bin/python tools/check_docs.py
.venv-docs/bin/python -m http.server 8000 --bind 127.0.0.1 --directory .docs-preview
```

Open `http://127.0.0.1:8000/`. Stop with Ctrl-C. The ignored `.docs-preview/`
directory is regenerated. Do not store anything else there. Preview pages remain
`noindex, nofollow`, with no sitemap or canonical URLs. Indexing hints are not access
controls. Add intended source documentation to Git's index before building.

For the public GitHub Pages build:

```bash
.venv-docs/bin/python tools/build_docs.py --production
.venv-docs/bin/python tools/check_docs.py --production
```

The ignored `.docs-site/` output uses the configured production URL
`https://citrus93.github.io/ACED/`. It includes canonical URLs, a sitemap,
a robots file and `.nojekyll`. The 404 page stays noindex. This build does not
publish anything by itself. Both modes are checked in CI. Checks cover all local
links, fragment targets, assets and indexing metadata, not external availability
or a full accessibility audit.

## GitHub Pages deployment

- Owner: CiTRuS93, repository ACED. Audience: public, including search engines.
- Provider: GitHub Pages for this public repository, using its included hosting
  and standard GitHub-hosted Linux Actions runners. No domain purchase, paid
  upgrade, separate service account or package-registry release is involved.
- Enable **Settings → Pages → Build and deployment → Source: GitHub Actions**
  once. The GitHub connector cannot configure this repository setting.
- After merging this change and passing CI, run **Actions → Publish documentation
  → Run workflow**, selecting `main`. Publishing is manual, not triggered by
  ordinary pushes or pull requests. The workflow refuses any branch except main.
- The build job has read-only repository access. Only the deployment job receives
  short-lived `pages: write` and `id-token: write` permissions through GitHub's
  standard Pages action. No long-lived credentials are stored.
- Confirm the deployment succeeds and inspect the returned URL, a nested docs
  page, navigation/search, and a nonexistent URL before announcing the site live.
- Roll back by reverting the unwanted documentation change through a reviewed PR,
  merging it and running the workflow again. For an urgent withdrawal, unpublish
  the site from Settings → Pages; this does not remove search-engine caches.
- This website deployment does not change ACED's development-preview status or
  claim production or unattended qualification.

GitHub Pages serves `robots.txt` here at `/ACED/robots.txt`. Crawlers normally
read robots rules only at the origin root; this project-level file cannot control
other projects on `citrus93.github.io`. Indexable canonical pages and the sitemap
do not depend on that file being discovered. No root-site changes are made.

## Maintenance

Paths follow sources: `/ACED/docs/runtime/` comes from `docs/runtime.md`.
README files become directory indexes. Preserve paths; renames need redirects.
Production's absolute 404 navigation links account for the project base path.

Build dependencies, including transitives, are pinned with hashes in
`requirements-docs.lock`. Review dependency updates and regenerate with
`uv pip compile requirements-docs.txt --generate-hashes -o requirements-docs.lock`.
They remain separate from ACED's runtime dependencies.

Search and mobile dropdowns need JavaScript. Content, ordinary links and the
documentation index remain available without it. Tables and code scroll on small
screens. The theme provides a keyboard skip link, focus outlines, contrast,
language metadata and responsive layout. Broader assistive-technology review
remains useful. No discovery, adoption or operational qualification is implied.
