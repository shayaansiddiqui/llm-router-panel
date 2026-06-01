# llm-gateway-console

A simple MVP foundation for a lightweight LLM Gateway and React admin panel.

The gateway exposes an OpenAI-compatible endpoint:

```text
POST /v1/chat/completions
```

Client apps can call a central domain such as:

```text
https://ai.gettingstarted.app/v1/chat/completions
```

The FastAPI gateway selects an active provider by priority, forwards the request to that provider's OpenAI-compatible backend, and tries the next active provider if a provider fails or times out.

Example provider endpoints:

```text
https://ai-1.gettingstarted.app
https://ai-2.gettingstarted.app
```

If a provider endpoint is saved as `https://ai-1.gettingstarted.app`, the gateway forwards chat completions to `https://ai-1.gettingstarted.app/v1/chat/completions`.

## Stack

- Backend: FastAPI
- Frontend: React + Vite
- Storage: SQLite

## Project Structure

```text
llm-gateway-console/
  backend/
    app/
      main.py
      database.py
      config.py
      schemas.py
    requirements.txt
    .env.example
  frontend/
    src/
      main.jsx
      styles.css
    package.json
    .env.example
```

## Run Backend Locally

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will create the SQLite database at `./data/llm_gateway.db` by default.

Useful backend URLs:

```text
http://localhost:8000/health
http://localhost:8000/docs
http://localhost:8000/v1/chat/completions
```

## Run Frontend Locally

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open the Vite URL shown in the terminal, usually:

```text
http://localhost:5173
```

Set `VITE_API_BASE_URL` in `frontend/.env` if the admin API is not running at `http://localhost:8000`.
Set `VITE_PUBLIC_GATEWAY_URL` to the public gateway URL shown in API Docs, for example `https://ai.gettingstarted.app`.

## Backend Environment Variables

Create `backend/.env` from `backend/.env.example`.

```text
APP_NAME=LLM Gateway Console
DATABASE_PATH=./data/llm_gateway.db
ADMIN_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
PROVIDER_REQUEST_TIMEOUT_SECONDS=60
```

For deployed admin panels, set `ADMIN_CORS_ORIGINS` to the frontend origin. Multiple origins can be comma-separated.

## First MVP Behavior

- Admin panel manages providers, models, routing rules, and logs.
- Providers include endpoint URL, optional API key, active/passive status, priority, and timeout.
- Chat completion requests use the first matching active routing rule when possible.
- If no rule matches, active providers are tried by priority.
- Request attempts are logged in SQLite.
- No authentication is included in this MVP.

## Example Request

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "llama-3.1-8b",
    "messages": [
      { "role": "user", "content": "Say hello from the gateway" }
    ]
  }'
```

Before this works, add at least one active provider in the admin panel.
