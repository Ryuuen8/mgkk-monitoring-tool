# MGKK Monitoring Tool

## Start the infrastructure

Copy `.env.example` to `.env`, then start the services from the repository root:

```powershell
Copy-Item .env.example .env
docker compose up --build
```

The Compose stack includes the FastAPI API, a configurable HTTP poller worker,
PostgreSQL, Redis, Prometheus, and Grafana. The poller checks
`POLL_TARGET_URL` every `POLL_INTERVAL_SECONDS` seconds; set these in `.env` to
monitor a different HTTP endpoint. The API exposes `/health` and `/metrics`.

Services are bound to localhost:

- API: <http://localhost:8000/health>
- Prometheus: <http://localhost:9090>
- Grafana: <http://localhost:3000> (credentials from `.env`)

The example credentials are for local development only. Change them before
using this stack outside a trusted local environment.

## Start the frontend

In a separate terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

The Vite development server proxies `/api` requests to the API on port 8000.
Run `npm run lint` and `npm run build` from `frontend` to check the frontend.
