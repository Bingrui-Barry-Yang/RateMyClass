# RateMyClassOxy

Course and professor reviews for Occidental College students.

- **Frontend:** React + TypeScript + Vite, Tailwind CSS v4, shadcn/ui, TanStack Query, React Router
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Database:** PostgreSQL 16 (Docker for local development)

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

Ports are set in `.env` (`BACKEND_PORT`, `FRONTEND_PORT`, `POSTGRES_PORT`) if the defaults clash
with something else on your machine.

## Commands

Run `make help` for the full list.

| Command | What it does |
| --- | --- |
| `make setup` | Install dependencies exactly as locked (`uv sync --locked`, `npm ci`) |
| `make db-up` / `make db-down` | Start / stop local Postgres |
| `make db-reset` | Wipe the local database and re-run migrations |
| `make dev` | Run backend and frontend with hot reload |
| `make migrate` | Apply migrations |
| `make migration m="..."` | Autogenerate a migration from model changes |
| `make gen-api` | Regenerate frontend API types from the backend OpenAPI schema |
| `make test` | Backend (pytest) and frontend (Vitest) tests |
| `make lint` | Lint, format check and type check (ruff, mypy, oxlint, prettier, tsc) |
| `make format` | Auto-format all code |
| `make build` | Production build of the frontend |

## Dependencies

Lockfiles are committed: `backend/uv.lock` and `frontend/package-lock.json`.

- Backend: `cd backend && uv add <pkg>` (or `uv add --dev <pkg>`). Never edit `uv.lock` by hand.
- Frontend: `cd frontend && npm install <pkg>` (or `-D` for dev tools).

## Contributing

1. Branch off `main`.
2. Make your change; run `make lint test`.
3. If you changed the API, run `make gen-api` and commit the updated `schema.d.ts`.
4. Open a pull request. CI must pass before merging.
