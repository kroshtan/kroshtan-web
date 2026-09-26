# kroshtan.com

The website of **Kroshtan**, the sole proprietorship of Floris van Beers, an independent ML/AI engineer in
Groningen. Python + FastAPI, server-rendered Jinja templates, one small stylesheet and a few lines of vanilla
JavaScript. No frontend framework, no trackers, no third-party requests.

MIT licensed; see [LICENSE](LICENSE). The fonts (JetBrains Mono, IBM Plex Sans) are self-hosted under the SIL
Open Font License; see `app/static/fonts/`.

```
app/            FastAPI app, templates, static assets
content/        all copy (YAML + Markdown), edit these to change the site
tests/          pytest suite
Dockerfile      the image Render runs
render.yaml     Render Blueprint
.github/        CI: lint + tests, build and push the image to GHCR, trigger the Render deploy hook
```

## Run locally

Requires Python 3.12+ and `make`.

```bash
make install   # one-time: venv (with uv inside it), dependencies, pre-commit hook
make dev       # http://localhost:8000, reloads on changes to app/ and content/
```

Other targets (`make help` lists them all):

```bash
make test      # pytest with coverage
make fix       # pre-commit on all files: ruff, ruff-format, mypy, pydoclint
make todos     # every TODO placeholder still left in content/
```

Or run the production image: `docker build -t kroshtan-web . && docker run -p 10000:10000 kroshtan-web`.

## Editing content

Every word on the site is in `content/`. Templates contain no copy.

| File | Page |
|---|---|
| `site.yaml` | name, email, links, **KvK number**, VAT ID, navigation |
| `home.yaml` | home page |
| `about.yaml`, `about.md` | about page: facts and timeline (YAML), prose (Markdown) |
| `skills.yaml` | skill groups |
| `services.yaml` | the three services (full copy + the short home-page summary) |
| `teaching.yaml` | teaching and talks (shown on the services page) |
| `portfolio.yaml` | publications, projects, talks |
| `contact.yaml` | contact page |

Long fields are Markdown. Any value starting with `TODO` is shown on the page with a yellow highlight so
nothing unfinished can go live unnoticed; `make todos` lists them.

**KvK number.** Dutch law requires the Chamber of Commerce number on a business website. While
`kvk_number` in `content/site.yaml` is empty, every page shows a warning banner and the server logs a warning
at startup. The VAT ID is optional and appears in the footer only when set.

**Projects.** Add public projects to `projects:` in `content/portfolio.yaml` (`title`, `description`, `url`,
`tags`). The entry with `example: true` is a labelled example; delete it once real projects are in.

## Deployment

```
push to main ──▶ GitHub Actions ──▶ lint + tests ──▶ build image ──▶ ghcr.io/kroshtan/kroshtan-web
                                                                            │
                                   Render deploy hook  ◀── ?imgURL=…@sha256:<digest>
```

Render never builds from the repository. It runs the image GitHub Actions pushes to GHCR, and it deploys only
when the workflow calls the service's deploy hook, passing the exact digest just built.

### One-time setup

1. **Push the repo to GitHub** (`github.com/Kroshtan/kroshtan-web`). The first run on `main` pushes
   `ghcr.io/kroshtan/kroshtan-web:latest`; the deploy step is skipped with a warning because there is no hook yet.
2. **Make the image public.** GitHub → your profile → *Packages* → `kroshtan-web` → *Package settings* →
   *Change visibility* → Public. (The code is public anyway. If you would rather keep the package private,
   add a GHCR registry credential in Render: a GitHub personal access token with `read:packages`.)
3. **Create the Render service.** Either:
   - *Blueprint:* Render dashboard → *New* → *Blueprint* → pick this repo. Render reads `render.yaml` and
     creates the `kroshtan-web` image service (Starter plan, Frankfurt) with both custom domains. Turn
     *Auto Sync* off on the Blueprint if you don't want config changes in `render.yaml` applied automatically.
   - *By hand:* *New* → *Web Service* → *Existing image* → `ghcr.io/kroshtan/kroshtan-web:latest`, Starter,
     Frankfurt, health check path `/healthz`.
4. **Wire up the deploy hook.** Render → service → *Settings* → *Deploy Hook* → copy the URL. GitHub → repo →
   *Settings* → *Environments* → create `production` → add secret `RENDER_DEPLOY_HOOK_URL` with that URL.
   From now on every push to `main` that passes CI is deployed.

To redeploy without a code change: *Actions* → *CI / CD* → *Run workflow* on `main`.

### Custom domain and DNS

The apex `kroshtan.com` is canonical; `www.kroshtan.com` redirects to it with a 301. Render does this itself
once both domains are attached, and the app redirects `www` as well as a fallback.

1. In Render → service → *Settings* → *Custom Domains*, add `kroshtan.com` and `www.kroshtan.com` (the Blueprint
   already declares both).
2. At your DNS provider, add **only** these records:

   | Type | Name | Value |
   |---|---|---|
   | `A` | `@` (kroshtan.com) | `216.24.57.1` |
   | `CNAME` | `www` | `kroshtan-web.onrender.com` (use the exact `*.onrender.com` host Render shows) |

   If your provider supports `ALIAS`/`ANAME` records at the apex, you can use one pointing at
   `kroshtan-web.onrender.com` instead of the `A` record. Remove any existing `AAAA` record on `@` and `www`;
   Render's domain docs ask for this, and a stale one sends some visitors elsewhere. Render shows the current values on the
   *Custom Domains* page; if they differ from the table above, use Render's.
3. Click *Verify* in Render. It issues the TLS certificates (Let's Encrypt / Google Trust Services)
   automatically. HTTPS needs no further setup.

> [!WARNING]
> **The domain's email runs on Proton Mail. Do not touch Proton's records.**
> Add the `A` and `CNAME` records above and change nothing else. In particular, keep:
>
> - the **`MX`** records (`mail.protonmail.ch`, `mailsec.protonmail.ch`),
> - the **SPF** `TXT` record on `@` (`v=spf1 include:_spf.protonmail.ch ~all`),
> - the **Proton verification** `TXT` record on `@` (`protonmail-verification=…`),
> - the **DKIM** `CNAME` records (`protonmail._domainkey`, `protonmail2._domainkey`, `protonmail3._domainkey`),
> - the **DMARC** `TXT` record on `_dmarc`.
>
> Never put a `CNAME` on the apex `@`: a CNAME cannot coexist with other records, so it would knock out the
> MX, SPF and verification records and stop email for the whole domain. If a DNS provider's "connect to
> hosting" wizard offers to replace existing records, decline. If the domain has `CAA` records, they must
> allow `letsencrypt.org` and `pki.goog`, or Render cannot issue certificates.
>
> After the change, check that mail still works: Proton → *Settings* → *Domain names* should show all
> checks green.
