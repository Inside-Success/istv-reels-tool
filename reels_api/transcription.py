import time
from rev_ai import apiclient
from requests import exceptions as requests_exceptions

TRANSIENT_REVAI_ERRORS = (
    requests_exceptions.ConnectionError,
    requests_exceptions.SSLError,
    requests_exceptions.Timeout,
)


def transcribe_audio(audio_path: str, api_key: str, progress_cb=None) -> dict:
    """
    Submit audio to Rev.ai, poll until done, return structured transcript.
    Raises RuntimeError on failure or timeout.
    """
    client = apiclient.RevAiAPIClient(api_key)

    _log(progress_cb, "Uploading audio to Rev.ai...")
    job = _call_revai(
        lambda: client.submit_job_local_file(
            filename=audio_path,
            language="en",
            skip_diarization=False,
            skip_punctuation=False,
            metadata="Inside Success Documentary",
        ),
        "upload audio to Rev.ai",
        progress_cb,
    )
    job_id = job.id
    _log(progress_cb, f"Job submitted (ID: {job_id}). Waiting for transcription...")

    elapsed = 0
    wait = 10  # start at 10 s, grow to 30 s
    while True:
        details = _call_revai(
            lambda: client.get_job_details(job_id),
            "check Rev.ai job status",
            progress_cb,
        )
        status = str(details.status).lower()

        if "transcribed" in status:
            break
        if "failed" in status:
            failure = getattr(details, "failure", "unknown error")
            raise RuntimeError(f"Rev.ai transcription failed: {failure}")

        _log(progress_cb, f"Transcribing... ({elapsed}s elapsed, checking again in {wait}s)")
        time.sleep(wait)
        elapsed += wait
        wait = min(wait + 5, 30)

        if elapsed > 1800:
            raise RuntimeError("Transcription timed out after 30 minutes.")

    _log(progress_cb, "Transcription complete — fetching word-level data...")
    raw = _call_revai(
        lambda: client.get_transcript_json(job_id),
        "fetch Rev.ai transcript",
        progress_cb,
    )
    return _parse(raw)


def _call_revai(action, label: str, progress_cb=None, attempts: int = 4):
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except requests_exceptions.HTTPError as exc:
            status = getattr(exc.response, "status_code", None)
            if status in {401, 403}:
                raise RuntimeError(
                    "Rev.ai rejected the API key. Check REVAI_API_KEY in backend/.env "
                    "and restart the backend."
                ) from exc
            if status not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt == attempts:
                raise RuntimeError(f"Could not {label}: {exc}") from exc
            delay = min(2**attempt, 20)
            _log(progress_cb, f"Rev.ai {label} failed with HTTP {status}; retrying in {delay}s...")
            time.sleep(delay)
        except TRANSIENT_REVAI_ERRORS as exc:
            if attempt == attempts:
                raise RuntimeError(
                    f"Could not {label} after {attempts} attempts due to a network/TLS error: {exc}"
                ) from exc
            delay = min(2**attempt, 20)
            _log(progress_cb, f"Rev.ai network/TLS error while trying to {label}; retrying in {delay}s...")
            time.sleep(delay)


def _parse(raw: dict) -> dict:
    """Convert Rev.ai monologue JSON to a flat word list + metadata."""
    words = []
    text_parts = []

    for mono in raw.get("monologues", []):
        speaker = mono.get("speaker", 0)
        for el in mono.get("elements", []):
            if el.get("type") == "text":
                words.append(
                    {
                        "word": el["value"],
                        "start": el.get("ts", 0.0),
                        "end": el.get("end_ts", 0.0),
                        "confidence": el.get("confidence", 1.0),
                        "speaker": speaker,
                    }
                )
                text_parts.append(el["value"])
            elif el.get("type") == "punct":
                text_parts.append(el.get("value", ""))

    duration = words[-1]["end"] if words else 0.0
    return {
        "words": words,
        "full_text": "".join(text_parts).strip(),
        "duration": duration,
        "word_count": len(words),
    }


def build_timestamped_text(
    transcript: dict, chunk: int = 25, *, include_speakers: bool = True
) -> str:
    """Group words into N-word chunks with [MM:SS] and optional Rev speaker id per chunk."""
    words = transcript["words"]
    lines = []
    for i in range(0, len(words), chunk):
        group = words[i : i + chunk]
        ts = fmt_time(group[0]["start"])
        text = " ".join(w["word"] for w in group)
        sp = int(group[0].get("speaker", 0) or 0)
        tag = f" [Speaker {sp}]" if include_speakers else ""
        lines.append(f"[{ts}]{tag} {text}")
    return "\n".join(lines)


def speaker_prompt_summary(transcript: dict) -> str:
    """Short diarization stats for LLM prompts (who talks how much)."""
    words = transcript.get("words") or []
    if not words:
        return "(No word-level diarization.)"
    counts: dict[int, int] = {}
    for w in words:
        sp = int(w.get("speaker", 0) or 0)
        counts[sp] = counts.get(sp, 0) + 1
    total = len(words)
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    lines = [
        f"- Speaker {sp}: {100 * n / total:.1f}% of words ({n} words)"
        for sp, n in ranked[:8]
    ]
    top = ", ".join(str(sp) for sp, _ in ranked[:2])
    lines.append(
        f"\nThe interview guest/expert is usually among the top speakers by share (often Speakers {top}). "
        "Hooks should start on their substantive speech, not on a rare low-talk-time speaker line unless that line is clearly the expert."
    )
    return "\n".join(lines)


def fmt_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def _log(cb, msg: str):
    if cb:
        cb(msg)
