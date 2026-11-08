# Local documentation preview

This optional site is an evaluation aid, not a deployment or release. Existing
README, contribution guide and `docs/` Markdown remain the only content sources.
The build stages tracked documentation and assets in a temporary directory, then
uses MkDocs' bundled theme and local search. It does not modify those sources.
Links to repository code remain GitHub links. No analytics or external CDN assets
are loaded. No package runtime dependency or hosting workflow is added.

## Build and inspect

Use Python 3.12+ from the repository root:

```bash
python -m venv .venv-docs
.venv-docs/bin/python -m pip install -r requirements-docs.txt
.venv-docs/bin/python tools/test_docs.py
.venv-docs/bin/python tools/build_docs.py
.venv-docs/bin/python tools/check_docs.py
.venv-docs/bin/python -m http.server 8000 --bind 127.0.0.1 --directory .docs-preview
```

Open `http://127.0.0.1:8000/` on the same computer. Stop the server with Ctrl-C.
The ignored `.docs-preview/` directory is regenerated on each build. Do not store
anything else there. Add new intended documentation files to Git's index before
building; ignored or untracked files are deliberately not copied. Do not add
private notes or runtime records to tracked documentation. Dependencies may need
network access during installation; viewing built content needs no network except
when following an external link. `.venv-docs/` is ignored.

CI runs the staging regressions, build and generated-site checks without publishing.
The build fails on MkDocs warnings. `check_docs.py` checks generated local links,
fragment targets, local assets, and the preview's indexing policy. It does not
check external link availability or constitute a full accessibility audit.

## URLs, indexing and eventual publication

Current paths follow source paths: `/docs/runtime/`, for example, comes from
`docs/runtime.md`. README files become their directory indexes. Keep these paths
stable; any future rename needs an explicit redirect strategy. The navigation
emphasizes an offline first use, the host contract, and qualification limits.
Detailed reference pages remain linked from the documentation index.

There is deliberately no `site_url`, canonical URL or sitemap. Every HTML page
includes `noindex, nofollow`, and `robots.txt` disallows crawling. These are indexing
hints, not authentication or access controls. This preview is only a loopback
server, not a private hosted service.

Publication requires a separate decision about owner, provider, domain/base path,
audience, cost, and release/rollback process. Only after that decision should a
follow-up change set the actual canonical `site_url`, enable the sitemap and
appropriate robots policy, verify subpath and 404 routing on the selected host,
and add an explicitly authorized deployment workflow. Do not substitute a guessed
URL or treat this branch as permission to publish. Reconcile known source-document
corrections before publication; this branch intentionally does not edit their
claims or change qualification policy.

## Maintenance and tradeoffs

- One direct build dependency, MkDocs 1.6.1, uses its bundled theme and search.
  Transitive dependencies are not fully locked; adopt a hashed build lock before
  reproducible release hosting, and review dependency updates rather than adding
  them to ACED's runtime requirements.
- The small build helper rewrites only included repository Markdown/image links
  and routes source-code references back to GitHub. Its link checker should run
  whenever source paths or theme structure change. Markdown remains readable on
  GitHub without this tool.
- Search and mobile dropdown navigation require JavaScript; page content, ordinary
  links and the documentation index remain available without it. Tables and code
  blocks scroll horizontally on narrow screens.
- The theme adds a keyboard skip link, visible focus outlines, higher-contrast link/navigation colors, language metadata,
  responsive layouts and a clearly labelled preview notice. Screen-reader and
  broader assistive-technology review remain necessary before publication.
- This can reduce navigation friction for evaluators. It supplies no evidence of
  increased discovery, adoption, customer results or operational qualification.
