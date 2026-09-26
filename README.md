# kroshtan.com

The website of **Kroshtan**, the sole proprietorship of Floris van Beers, an independent ML/AI engineer in
Groningen. Python + FastAPI, server-rendered Jinja templates, one small stylesheet and a few lines of vanilla
JavaScript. No frontend framework, no trackers, no third-party requests from the browser. One API endpoint,
`POST /api/ask`, lets visitors check whether their problem is a fit; it calls the Anthropic API from the server.

MIT licensed; see [LICENSE](LICENSE). The fonts (Fraunces, Source Sans 3) are self-hosted under the SIL
Open Font License; see `app/static/fonts/`.

```
app/            FastAPI app, templates, static assets
content/        all copy (YAML + Markdown), edit these to change the site
prompts/        assess.md, the system prompt for "Can I help with this?"
private/        extra context for that assistant (gitignored, except its README)
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

## "Can I help with this?"

A text box on the home and contact pages. The visitor describes a problem (max 1,500 characters), the server wraps it
in a fixed prompt and asks Claude whether it fits Floris's expertise, and the answer streams back into the page.

- **Prompt:** `prompts/assess.md`. Edit freely; it is read at startup. The server appends the contact email, the
  public site content (from `content/`, with `TODO` placeholders stripped) and the private notes.
- **Context:** public content from `content/about.md` and `about/skills/services/teaching/portfolio.yaml`, plus every
  `.md`/`.txt` file in `private/` (or `$PRIVATE_DIR`). Information from private files **can appear in answers**.
- **Feature switch:** the box is only rendered when `ANTHROPIC_API_KEY` is set. Without it the site works as before
  and `/api/ask` answers 503.
- **Privacy:** questions are not stored or logged. Logs contain counts only ("question 12 of 100 today"). Rate-limit
  buckets are keyed by a salted hash of the IP, kept in memory, and the container runs with access logs off. A note
  under the box tells visitors their question goes to an external AI service.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | (unset) | Anthropic API key. Server-side only; never sent to the browser. |
| `LLM_MODEL` | `claude-sonnet-5` | Model to use. |
| `LLM_MAX_TOKENS` | `1200` | Output ceiling per answer. The prompt asks for ≤150 words; the rest is headroom for thinking. |
| `DAILY_REQUEST_CAP` | `100` | Questions per UTC day across all visitors. Above it, visitors get a friendly message with the email address. |
| `RATE_LIMIT_PER_HOUR` / `RATE_LIMIT_PER_DAY` | `5` / `20` | Per visitor IP, sliding windows. |
| `PRIVATE_DIR` | `private/` | Folder with private context files. `/etc/secrets` on Render. |
| `CLIENT_IP_HEADER` | (unset) | Header holding the real client IP, if the edge sets one clients can't forge (e.g. `cf-connecting-ip`). |
| `TRUSTED_PROXY_HOPS` | `1` | Otherwise: which `X-Forwarded-For` entry, counted from the right, is the client. |

Cost: the system prompt is about 3k tokens (cached after the first request) and an answer a few hundred, so a
question costs on the order of one to two cents with Sonnet 5. With the default cap that's at most about $2 a day.

Limits are held in memory: correct for the single Render instance, reset on each deploy or restart.

### Running it locally

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make dev
```

Put any private notes in `private/` (e.g. `private/projects.md`). They are picked up on restart.

### Filling `private/` on Render

Render has no persistent folder for this, but it has **Secret Files**: files you upload in the dashboard that are
mounted read-only at `/etc/secrets/<filename>` and never enter the repo or the image.

1. Render → `kroshtan-web` → *Environment* → *Secret Files* → *Add Secret File*.
2. Filename, e.g. `projects.md`; paste the contents. Repeat for each file. Only `.md`, `.markdown` and `.txt`
   files are read; any other secret file in `/etc/secrets` is ignored.
3. Make sure `PRIVATE_DIR=/etc/secrets` is set (the Blueprint does this).
4. *Save*, then *Manual Deploy* → *Deploy latest reference* (or push a commit) so the service restarts and re-reads
   them. The startup log says `assistant context: public content + N private file(s)`, which confirms they
   were found.

### Checking the per-IP limit after the first deploy

The limiter must see the visitor's real address, not one a client can forge. By default it takes the rightmost
`X-Forwarded-For` entry, which is the one Render's proxy adds. Check it once after deploying:

```bash
# 6th request should be a 429, even though every request claims a different address:
for i in 1 2 3 4 5 6; do
  curl -s -o /dev/null -w '%{http_code}\n' -X POST https://kroshtan.com/api/ask \
    -H 'Content-Type: application/json' -H "X-Forwarded-For: 203.0.113.$i" \
    -d '{"question":"Checking the rate limit, please ignore."}'
done
```

If all six return 200, the proxy passes the header differently: set `CLIENT_IP_HEADER` to a header the edge sets
itself (e.g. `cf-connecting-ip` or `true-client-ip`, whichever Render sends) or raise `TRUSTED_PROXY_HOPS`. If
visitors on different networks hit the limit together, the rightmost entry is a proxy address rather than the
client; try `TRUSTED_PROXY_HOPS=2`. The global daily cap bounds cost either way. (The test uses 5 of your
own questions and 5 of today's cap.)

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
4. **Set the API key.** Render → service → *Environment* → `ANTHROPIC_API_KEY` (the Blueprint asks for it). Leave
   it empty to launch without the question box.
5. **Wire up the deploy hook.** Render → service → *Settings* → *Deploy Hook* → copy the URL. GitHub → repo →
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
