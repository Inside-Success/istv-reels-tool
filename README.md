# Inside Success Reels Tool

React frontend plus FastAPI backend for generating documentary reel suggestions, a brand story, an Excel sheet, and a PDF report.

## Project layout

- `frontend/` - Vite React app for Vercel.
- `app.py` - FastAPI backend for Render.
- `src/` - audio prep, Rev.ai transcription, Claude analysis, Excel, and PDF generation.
- `Dockerfile` - Render-ready backend image with FFmpeg installed.
- `render.yaml` - optional Render blueprint.

## Local development

Backend:

```bash
pip install -r requirements.txt
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL=http://localhost:8000` for the frontend when running locally. The backend loads `.env` values at startup and reads `REVAI_API_KEY` and `CLAUDE_API_KEY` from the server environment; API keys are not collected in the React UI.

## Render backend

Use the Dockerfile deployment path. Set these environment variables in Render:

- `REVAI_API_KEY`
- `CLAUDE_API_KEY`
- `FRONTEND_ORIGIN`, for example `https://your-vercel-app.vercel.app`

The health check path is `/api/health`.

## Vercel frontend

Create a Vercel project with `frontend` as the project root.

- Build command: `npm run build`
- Output directory: `dist`
- Environment variable: `VITE_API_BASE_URL=https://your-render-service.onrender.com`
