# Backend

FastAPI API for uploads, transcription, Claude analysis, Excel generation, and preview clip rendering.

## Layout

- `main.py` - FastAPI ASGI application and API routes.
- `reels_api/` - transcription, analysis, media processing, and export helpers used by the API.
- `requirements.txt` - Python runtime dependencies for the API service.

## Local development

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Create `backend/.env` from `backend/.env.example` and set:

- `REVAI_API_KEY`
- `CLAUDE_API_KEY`
- `FRONTEND_ORIGIN`, comma-separated when needed, for example `http://localhost:5205,http://127.0.0.1:5205,https://your-vercel-app.vercel.app`

The health check is available at `/api/health`.

## Docker

```bash
docker build -t inside-success-reels-api .
docker run --env-file .env -p 8000:10000 inside-success-reels-api
```

The image installs FFmpeg and starts `uvicorn main:app` on `${PORT:-10000}`.

## Render

Use this directory as the service root and deploy with `Dockerfile`. `render.yaml` is included as a backend-only blueprint.
