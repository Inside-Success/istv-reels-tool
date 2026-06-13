"""
Cut and join media (video or audio) with ffmpeg using cut-sheet timecodes.
Outputs preview files for brand documentary assembly and each reel assembly.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from src.audio_processor import VIDEO_EXTS, check_ffmpeg


def _is_video(path: str) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXTS


def _ext_for_container(is_video: bool) -> str:
    return ".mp4" if is_video else ".mp3"


def _ffmpeg_cut(
    input_path: str,
    out_path: str,
    start: float,
    end: float,
    *,
    is_video: bool,
) -> None:
    duration = max(0.08, float(end) - float(start))
    if is_video:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            input_path,
            "-t",
            f"{duration:.3f}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            out_path,
        ]
    else:
        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-i",
            input_path,
            "-t",
            f"{duration:.3f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "160k",
            out_path,
        ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg segment cut failed ({out_path}): {proc.stderr[-800:]!s}"
        )


def _ffmpeg_concat(segment_paths: list[str], output_path: str, *, cwd: str) -> None:
    if not segment_paths:
        raise ValueError("No segments to concat")
    if len(segment_paths) == 1:
        shutil.copy2(segment_paths[0], output_path)
        try:
            os.remove(segment_paths[0])
        except OSError:
            pass
        return
    list_path = os.path.join(cwd, "_concat_list.txt")
    names = [os.path.basename(p) for p in segment_paths]
    with open(list_path, "w", encoding="utf-8") as handle:
        for name in names:
            handle.write(f"file '{name}'\n")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        os.path.basename(list_path),
        "-c",
        "copy",
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    try:
        os.remove(list_path)
    except OSError:
        pass
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {proc.stderr[-800:]!s}")


def _segments_from_cut_sheet(rows: list) -> list[tuple[float, float]]:
    segs: list[tuple[float, float]] = []
    for row in rows:
        try:
            a = float(row.get("start_time_seconds") or 0)
            b = float(row.get("end_time_seconds") or 0)
        except (TypeError, ValueError):
            continue
        if b <= a:
            continue
        segs.append((a, b))
    return segs


def _segments_for_reel(reel: dict) -> list[tuple[float, float]]:
    parts = reel.get("editor_cut_sheet") or []

    def _ord(x: dict) -> int:
        o = x.get("order")
        if o is None:
            return 0
        try:
            return int(float(o))
        except (TypeError, ValueError):
            return 0

    ordered = sorted(
        parts,
        key=lambda x: (_ord(x), float(x.get("start_time_seconds") or 0)),
    )
    return _segments_from_cut_sheet(ordered)


def render_cut_previews(
    upload_path: str,
    analysis: dict,
    work_dir: str,
    stem: str,
) -> dict[str, str]:
    """
    Build joined preview files. Returns map download_key -> absolute file path.
    Keys: preview_brand_story, preview_reel_<id>
    """
    check_ffmpeg()
    if not os.path.isfile(upload_path):
        raise FileNotFoundError(upload_path)

    is_video = _is_video(upload_path)
    ext = _ext_for_container(is_video)
    safe_stem = re.sub(r"[^\w\-]+", "_", str(stem))[:80]
    out: dict[str, str] = {}

    brand = analysis.get("brand_story") or {}
    dcs = brand.get("documentary_cut_sheet") or []
    brand_segs = _segments_from_cut_sheet(sorted(dcs, key=lambda x: (x.get("sequence", 0), x.get("start_time_seconds", 0))))
    if brand_segs:
        seg_paths: list[str] = []
        for i, (a, b) in enumerate(brand_segs):
            seg = os.path.join(work_dir, f"_brand_seg_{i:03d}{ext}")
            _ffmpeg_cut(upload_path, seg, a, b, is_video=is_video)
            seg_paths.append(seg)
        joined = os.path.join(work_dir, f"{safe_stem}_brand_cut_preview{ext}")
        _ffmpeg_concat(seg_paths, joined, cwd=work_dir)
        for p in seg_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        out["preview_brand_story"] = joined

    for reel in analysis.get("reels") or []:
        rid = reel.get("id")
        if rid is None:
            continue
        segs = _segments_for_reel(reel)
        if not segs:
            continue
        seg_paths = []
        for i, (a, b) in enumerate(segs):
            seg = os.path.join(work_dir, f"_reel{rid}_seg_{i:03d}{ext}")
            _ffmpeg_cut(upload_path, seg, a, b, is_video=is_video)
            seg_paths.append(seg)
        key = f"preview_reel_{int(rid)}"
        joined = os.path.join(work_dir, f"{safe_stem}_reel{int(rid)}_preview{ext}")
        _ffmpeg_concat(seg_paths, joined, cwd=work_dir)
        for p in seg_paths:
            try:
                os.remove(p)
            except OSError:
                pass
        out[key] = joined

    return out


def preview_media_type(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext == ".mp4":
        return "video/mp4"
    if ext == ".webm":
        return "video/webm"
    if ext == ".mp3":
        return "audio/mpeg"
    if ext in (".m4a", ".aac"):
        return "audio/mp4"
    return "application/octet-stream"
