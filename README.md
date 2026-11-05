# RateMyClassOxy

Course and professor reviews for Occidental College students.

- **Frontend:** React + TypeScript + Vite, Tailwind CSS v4, shadcn/ui, TanStack Query, React Router
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Database:** PostgreSQL 16 (Docker for local development)
- **Scraper:** httpx + BeautifulSoup (lxml), reading the public course list at counts.oxy.edu

See [docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [Node.js 22](https://nodejs.org/) (see `.nvmrc`)
- [uv](https://docs.astral.sh/uv/) (`brew install uv`). uv installs Python 3.12 for you.
- GNU Make (preinstalled on macOS and Linux)

## Quick start

```bash
make setup     # creates .env, installs backend + frontend deps from lockfiles
make db-up     # starts Postgres in Docker
make migrate   # applies database migrations
make dev       # backend on :8010, frontend on :5173
```

Open http://localhost:5173. The home page shows whether the backend and database are reachable.
API docs live at http://localhost:8010/api/docs.

The database starts empty. To fill it with course data, see [Load course data](#load-course-data).

Ports are set in `.env` (`BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`) if the defaults clash
with something else on your machine.

## Load course data

Course data comes from counts.oxy.edu and is not committed: everything under `data/` is git-ignored.

```bash
make scrape    # first run downloads all terms (~1 request/s, a few hours); safe to stop and rerun
make import    # groups the data into courses and loads it into the database; safe to rerun
```

### Updating course data

When counts.oxy.edu changes (classes cancelled, moved or reassigned, descriptions edited, a new term
published):

```bash
make migrate   # after pulling new code: apply any new database migrations first
make update    # re-downloads new and changed terms, then reports what the import would change
make import    # applies it; check data/reports/update/<time>/summary.txt first
```

`make update` checks the current academic year and later plus any term new on the site, and
re-downloads in full the terms that are new, changed, current or upcoming (a few minutes); the result
is the same as downloading those terms again. Older terms are not checked: `all=1` checks and
re-downloads every term the site lists (~30 min), which also picks up changes the school made to a
past term. `terms=202702` re-downloads only the named terms. An interrupted or failed run changes
nothing and resumes on the next run. Terms the site no longer lists are kept.

`make import` makes the database match the data: cancelled sections are deleted, changed ones updated
in place. It stops if a term would lose more than 20% of its sections (usually a site problem); run
`make import force=1` if the cancellations are real.

| Folder | Contents |
| --- | --- |
| `data/raw` | Downloaded pages (gzip HTML), so parsing can be redone without the network |
| `data/parsed` | One JSON file per term: every listed section as shown, plus course details |
| `data/normalized` | Terms, departments, courses, sections and professors, the input of `make import` |
| `data/reports` | CSV reports for review (topic splits, title changes, renumbered courses, possible duplicate professors, unmatched labs, overrides that no longer match anything, and full tables of all sections and courses); `data/reports/update/<time>/` holds what each import changed |

Corrections are made by hand in the committed CSV files in `scraper/overrides/`, never in the database:
`exclusions.csv` (what to skip), `course_overrides.csv` (topic names, merges, titles, numbers reused for
different courses, courses to keep apart or to link as "formerly") and `professor_aliases.csv` (one
professor listed under several names). After editing them, run `make import` again (it re-runs
normalize first) and check `data/reports`.

## Commands

Run `make help` for the full list.

| Command | What it does |
| --- | --- |
| `make setup` | Install dependencies exactly as locked (`uv sync --locked --all-packages`, `npm ci`) |
| `make db-up` / `make db-down` | Start / stop local Postgres |
| `make db-reset` | Wipe the local database and re-run migrations |
| `make dev` | Run backend and frontend with hot reload |
| `make migrate` | Apply migrations |
| `make migration m="..."` | Autogenerate a migration from model changes |
| `make gen-api` | Regenerate frontend API types from the backend OpenAPI schema |
| `make test` | Backend and scraper (pytest) and frontend (Vitest) tests. Needs the local database (`make db-up migrate`) |
| `make lint` | Lint, format check and type check (ruff, mypy, oxlint, prettier, tsc) |
| `make format` | Auto-format all code |
| `make build` | Production build of the frontend |
| `make scrape` | First download of course data from counts.oxy.edu into `data/raw` (cached, resumable) and parse it into `data/parsed` (`terms=202602,202603`) |
| `make update` | Re-download new and changed terms, normalize, and report what `make import` would change (`terms=…`, `all=1`) |
| `make normalize` | Group parsed data into courses, sections and professors (`data/normalized`) and write review reports (`data/reports`) |
| `make import` | Normalize, then make the database match it and write a change report to `data/reports/update` (`force=1`). Needs `make db-up migrate` and `make scrape` first |

## Dependencies

Lockfiles are committed: `uv.lock` (repo root, shared by the `backend` and `scraper` uv workspace members) and `frontend/package-lock.json`.

- Python: `cd backend && uv add <pkg>` or `cd scraper && uv add <pkg>` (add `--dev` for dev tools), then `make setup` so both workspace members stay installed. Never edit `uv.lock` by hand.
- Frontend: `cd frontend && npm install <pkg>` (or `-D` for dev tools).

## Contributing

1. Branch off `main`.
2. Make your change; run `make lint test` (with the database up: `make db-up migrate`).
3. If you changed the API, run `make gen-api` and commit the updated `schema.d.ts`.
4. Open a pull request. CI must pass before merging.
