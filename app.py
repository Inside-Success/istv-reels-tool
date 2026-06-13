import json
import os
import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from src.analyzer import CLAUDE_MODELS, analyze_with_claude
from src.audio_processor import AUDIO_EXTS, VIDEO_EXTS, prepare_audio
from src.preview_media import preview_media_type, render_cut_previews
from src.spreadsheet_generator import generate_spreadsheet
from src.transcription import fmt_time, transcribe_audio


load_dotenv()

DEFAULT_MODEL = next(iter(CLAUDE_MODELS))
JOB_RETENTION_SECONDS = int(os.getenv("JOB_RETENTION_SECONDS", "21600"))
MAX_LOG_LINES = 200


@dataclass
class JobState:
    id: str
    filename: str
    status: str = "queued"
    progress: int = 0
    logs: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: dict[str, Any] | None = None
    error: str | None = None
    files: dict[str, bytes] = field(default_factory=dict)
    download_names: dict[str, str] = field(default_factory=dict)


app = FastAPI(title="Inside Success Reels API", version="1.0.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGIN", "").split(",")
    if origin.strip()
]
if not allowed_origins:
    allowed_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict[str, JobState] = {}
JOBS_LOCK = threading.Lock()

_DOWNLOAD_KIND = re.compile(r"^(xlsx|preview_brand_story|preview_reel_\d+)$")

_REPO_ROOT = Path(__file__).resolve().parent
_GENERATED_DATA = _REPO_ROOT / "generated_data"


def _persist_job_artifacts(
    job_id: str,
    upload_path: str,
    filename: str,
    transcript: dict[str, Any],
    analysis: dict[str, Any],
    xlsx_path: str,
    preview_paths: dict[str, str],
) -> str | None:
    """
    Copy Rev transcript, Claude analysis, XLSX/PDF, previews, and original upload
    into generated_data/<job_id>/ (under the repo root). Runs before temp dir is removed.
    """
    _GENERATED_DATA.mkdir(parents=True, exist_ok=True)
    out = _GENERATED_DATA / job_id
    if out.exists():
        shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    with (out / "transcript.json").open("w", encoding="utf-8") as handle:
        json.dump(transcript, handle, indent=2, ensure_ascii=False)
    with (out / "analysis.json").open("w", encoding="utf-8") as handle:
        json.dump(analysis, handle, indent=2, ensure_ascii=False, default=str)

    if os.path.isfile(xlsx_path):
        shutil.copy2(xlsx_path, out / Path(xlsx_path).name)
    if os.path.isfile(upload_path):
        safe_up = _safe_filename(filename)
        shutil.copy2(upload_path, out / safe_up)

    for _pk, ppath in (preview_paths or {}).items():
        if ppath and os.path.isfile(ppath):
            shutil.copy2(ppath, out / Path(ppath).name)

    return str(out.resolve())


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/models")
def models() -> dict[str, Any]:
    return {"default_model": DEFAULT_MODEL, "models": CLAUDE_MODELS}


@app.post("/api/jobs")
async def create_job(
    file: UploadFile = File(...),
    model: str = Form(DEFAULT_MODEL),
) -> JSONResponse:
    _cleanup_old_jobs()

    filename = _safe_filename(file.filename)
    extension = Path(filename).suffix.lower()
    if extension not in VIDEO_EXTS and extension not in AUDIO_EXTS:
        supported = ", ".join(sorted(VIDEO_EXTS | AUDIO_EXTS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{extension}'. Supported: {supported}",
        )

    if model not in CLAUDE_MODELS:
        raise HTTPException(status_code=400, detail="Unsupported Claude model.")

    rev_key = (os.getenv("REVAI_API_KEY") or "").strip()
    claude_key = (os.getenv("CLAUDE_API_KEY") or "").strip()
    if not rev_key:
        raise HTTPException(status_code=400, detail="Rev.ai API key is required.")
    if not claude_key:
        raise HTTPException(status_code=400, detail="Claude API key is required.")

    job_id = uuid4().hex
    tmp_dir = tempfile.mkdtemp(prefix=f"inside-success-{job_id}-")
    upload_path = os.path.join(tmp_dir, filename)

    try:
        with open(upload_path, "wb") as out_file:
            while chunk := await file.read(1024 * 1024):
                out_file.write(chunk)
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc
    finally:
        await file.close()

    job = JobState(id=job_id, filename=filename)
    with JOBS_LOCK:
        JOBS[job_id] = job

    _log(job_id, f"Uploaded {filename}")
    worker = threading.Thread(
        target=_run_pipeline,
        args=(job_id, upload_path, tmp_dir, filename, rev_key, claude_key, model),
        daemon=True,
    )
    worker.start()

    return JSONResponse(_public_job(job))


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = _get_job(job_id)
    return _public_job(job)


@app.get("/api/jobs/{job_id}/downloads/{kind}")
def download(job_id: str, kind: str) -> Response:
    job = _get_job(job_id)
    if job.status != "complete":
        raise HTTPException(status_code=409, detail="Job is not complete yet.")
    if not _DOWNLOAD_KIND.match(kind):
        raise HTTPException(status_code=400, detail="Invalid download kind.")
    if kind not in job.files:
        raise HTTPException(status_code=404, detail="Download not found.")

    filename = job.download_names.get(kind, f"inside_success_reels.{kind}")
    if kind == "xlsx":
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media_type = preview_media_type(filename)
    disposition = "inline" if kind.startswith("preview_") else "attachment"
    return Response(
        content=job.files[kind],
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


def _run_pipeline(
    job_id: str,
    upload_path: str,
    tmp_dir: str,
    filename: str,
    rev_key: str,
    claude_key: str,
    model: str,
) -> None:
    try:
        _set_job(job_id, status="running", progress=5)

        _log(job_id, "Preparing audio")
        audio_path, steps = prepare_audio(upload_path, tmp_dir)
        for step in steps:
            _log(job_id, step)
        _set_job(job_id, progress=15)

        _log(job_id, "Uploading to Rev.ai for word-level transcription")
        transcript = transcribe_audio(
            audio_path,
            rev_key,
            progress_cb=lambda message: _log(job_id, message),
        )
        _set_job(job_id, progress=55)
        _log(
            job_id,
            "Transcription complete: "
            f"{transcript['word_count']:,} words, {fmt_time(transcript['duration'])}",
        )

        _log(job_id, f"Analysing with {CLAUDE_MODELS.get(model, model)}")
        analysis = analyze_with_claude(
            transcript,
            model,
            claude_key,
            progress_cb=lambda message: _log(job_id, message),
        )
        _set_job(job_id, progress=78)

        stem = Path(filename).stem or "documentary"
        xlsx_path = os.path.join(tmp_dir, "inside_success_reels.xlsx")

        _log(job_id, "Generating Excel spreadsheet")
        generate_spreadsheet(
            analysis=analysis,
            transcript=transcript,
            output_path=xlsx_path,
            video_filename=stem,
        )
        _set_job(job_id, progress=90)

        preview_paths: dict[str, str] = {}
        try:
            _log(job_id, "Cutting & joining preview clips with ffmpeg (brand + reels)...")
            preview_paths = render_cut_previews(upload_path, analysis, tmp_dir, stem)
        except Exception as exc:
            _log(job_id, f"Preview export skipped: {exc}")

        archived_path: str | None = None
        try:
            archived_path = _persist_job_artifacts(
                job_id,
                upload_path,
                filename,
                transcript,
                analysis,
                xlsx_path,
                preview_paths,
            )
        except Exception as exc:
            _log(job_id, f"generated_data archive failed: {exc}")
        else:
            if archived_path:
                _log(job_id, f"Saved local bundle to {archived_path}")

        with open(xlsx_path, "rb") as xlsx_file:
            xlsx_bytes = xlsx_file.read()

        files: dict[str, bytes] = {"xlsx": xlsx_bytes}
        download_names: dict[str, str] = {
            "xlsx": f"{stem}_inside_success_reels.xlsx",
        }
        preview_rows: list[dict[str, Any]] = []
        for pk, ppath in preview_paths.items():
            with open(ppath, "rb") as media_file:
                files[pk] = media_file.read()
            download_names[pk] = os.path.basename(ppath)
            preview_rows.append(
                {
                    "kind": pk,
                    "mime": preview_media_type(ppath),
                    "label": _preview_download_label(pk),
                }
            )

        result = {
            "filename": filename,
            "transcript": {
                "duration": transcript.get("duration", 0),
                "duration_label": fmt_time(transcript.get("duration", 0)),
                "word_count": transcript.get("word_count", 0),
            },
            "analysis": analysis,
            "previews": preview_rows,
            "local_bundle_path": archived_path,
        }
        _set_job(
            job_id,
            status="complete",
            progress=100,
            result=result,
            files=files,
            download_names=download_names,
        )
        _log(job_id, "Done")
    except Exception as exc:
        _set_job(job_id, status="failed", error=str(exc), progress=100)
        _log(job_id, f"Pipeline error: {exc}")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _preview_download_label(kind: str) -> str:
    if kind == "preview_brand_story":
        return "Brand story (joined)"
    m = re.match(r"^preview_reel_(\d+)$", kind)
    if m:
        return f"Reel {m.group(1)} (joined)"
    return kind


def _public_job(job: JobState) -> dict[str, Any]:
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "progress": job.progress,
        "logs": job.logs,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "error": job.error,
        "result": job.result,
        "downloads": {
            kind: f"/api/jobs/{job.id}/downloads/{kind}" for kind in job.files
        },
    }


def _get_job(job_id: str) -> JobState:
    with JOBS_LOCK:
        job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _set_job(job_id: str, **changes: Any) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        for key, value in changes.items():
            setattr(job, key, value)
        job.updated_at = time.time()


def _log(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        job = JOBS[job_id]
        job.logs.append(message)
        if len(job.logs) > MAX_LOG_LINES:
            job.logs = job.logs[-MAX_LOG_LINES:]
        job.updated_at = time.time()


def _safe_filename(filename: str | None) -> str:
    raw_name = Path(filename or "upload").name
    cleaned = "".join(
        char if char.isalnum() or char in "._- " else "_" for char in raw_name
    ).strip()
    return cleaned or "upload"


def _cleanup_old_jobs() -> None:
    cutoff = time.time() - JOB_RETENTION_SECONDS
    with JOBS_LOCK:
        old_ids = [
            job_id
            for job_id, job in JOBS.items()
            if job.updated_at < cutoff and job.status in {"complete", "failed"}
        ]
        for job_id in old_ids:
            del JOBS[job_id]
