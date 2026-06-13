import json
import re

from anthropic import Anthropic
from src.transcription import (
    build_timestamped_text,
    fmt_time,
    speaker_prompt_summary,
)
from src.transcript_snippets import verbatim_from_words

# Available models shown in the UI toggle
CLAUDE_MODELS = {
    "claude-opus-4-7": "Claude Opus 4.7",
    "claude-opus-4-6": "Claude Opus 4.6",
}


# ── Public entry point ─────────────────────────────────────────────────────────

def analyze_with_claude(
    transcript: dict,
    model: str,
    api_key: str,
    progress_cb=None,
) -> dict:
    """
    Two-pass Claude analysis:
      Pass 1 — Extract 10 hooking reel segments with timestamps
      Pass 2 — Craft an SEO-optimized brand story
    Returns merged dict with word timestamps attached to each reel.
    """
    client = Anthropic(api_key=api_key)
    ts_text = build_timestamped_text(transcript, include_speakers=True)
    duration = fmt_time(transcript["duration"])
    speaker_hint = speaker_prompt_summary(transcript)

    _log(progress_cb, f"Pass 1 — Extracting 10 hooking reels ({model})...")
    reels = _extract_reels(client, model, ts_text, duration, speaker_hint)

    _log(progress_cb, "Pass 2 — Crafting SEO brand story...")
    brand = _extract_brand_story(client, model, ts_text, duration)

    analysis = {"reels": reels, "brand_story": brand}
    _normalize_cut_sheets(analysis, float(transcript.get("duration") or 0))

    _log(progress_cb, "Filling verbatim transcript text for each cut window...")
    _attach_verbatim_for_segments(analysis, transcript)

    _log(progress_cb, "Attaching Rev.ai word timestamps to each reel...")
    _attach_words(analysis, transcript["words"])

    return analysis


# ── Pass 1: Reel extraction ────────────────────────────────────────────────────

def _extract_reels(
    client: Anthropic, model: str, ts_text: str, duration: str, speaker_hint: str
) -> list:
    prompt = f"""# ROLE
You are a senior short-form video strategist who has produced viral reels for business, legal, medical, and entrepreneurial documentaries. You understand Instagram Reels, YouTube Shorts, and TikTok algorithms — hook strength in the first ~3s, retention, watch-time, loop potential.

# INPUT
Timestamped transcript of an interview ({duration} total runtime). Each line is `[MM:SS] [Speaker N] …words` from Rev.ai diarization.

# DIARIZATION HINT (use this — do not ignore)
{speaker_hint}

# OBJECTIVE
Extract exactly 10 DISTINCT reels. Each reel is self-contained; an editor cuts from the master using ABSOLUTE seconds (same timebase as transcript).

Group the 10 reels into **thematic segments (parts)** so the client immediately sees where each reel belongs in the bigger story. Assign each reel a `segment_label` (e.g. "Part A — Origin Story", "Part B — The Struggle", "Part C — Breakthrough & Results", "Part D — Vision & Advice"). Use 3–5 segments total; multiple reels can share a segment. The segment gives context about the person's work, job, company, journey, or expertise.

# WHO MUST SPEAK FIRST (CRITICAL)
- The **interview guest / subject** (founder, expert, doctor, lawyer — the person being interviewed) must be the **first audible words** in the final playout. **Order 1 = HOOK** must begin at a timestamp where **that guest is already talking** — not silence, not music-only, not a title card beat.
- **Do not** open the HOOK on: off-screen **voice-over / narrator / announcer**; generic show bumper; host "welcome / thanks for joining" unless the **guest speaks in the same first second** and you trim so the **guest's first word** is the start of `start_time_seconds` for the HOOK.
- **Voice-over and narrator lines are lowest priority** for hooks and for opening the reel. If a great line exists but VO leads into it, **narrow the HOOK window** so playback starts on the guest's first word of that idea (drop the VO from the cut).
- **Interviewer** setup is also a poor hook opener unless the guest answers immediately inside the same HOOK window and the clip **starts on the guest**.

# NON-NEGOTIABLE RULES
1. **Duration (PLAYBACK)**: Sum of all `playback_segments` durations MUST be ≥ 40s and ≤ 60s. Never exceed 60s.
2. **Hook first in PLAYBACK**: `playback_segments` MUST be ordered for the FINAL timeline. Segment with `role` "HOOK" is **order 1** and plays first even if that moment appears later in the interview than body clips (stitching allowed).
3. **Hook length**: HOOK segment should be ~5–10s of punchy transcript (contrarian, stakes, curiosity, emotion — NOT weak intros).
4. **Stitching**: 2–4 segments total per reel (HOOK + 1–3 BODY/PAYOFF). Non-contiguous source times are OK. Each segment needs precise `start_time_seconds` / `end_time_seconds` on the master.
5. **Self-contained**: No "as I mentioned earlier". Different theme per reel. No overlapping HOOK quotes across reels.
6. **Loop**: Prefer an ending that echoes the hook or rewards a re-watch.
7. **Reel `id`: 1** must be your **strongest single reel** in the batch: highest specificity (numbers, stakes, names), tightest guest-led hook, zero filler at the top — treat it as the hero asset for the channel.
8. **Short-form optimized**: Every reel must be optimized for maximum reach on Instagram Reels / YouTube Shorts / TikTok. Think: scroll-stopping hook, tight pacing, clear value or emotion delivered fast, no dead air, strong closer that makes people share or save.

# TWO KEY QUOTES PER REEL
For each reel, extract the **two most powerful spoken lines** (verbatim from the transcript) that capture what the reel is about. These give the client a quick read on the reel's content without watching.
- `key_quote_1`: The strongest / most shareable line (often overlaps with the hook).
- `key_quote_2`: A second impactful line from the body/payoff that adds context or delivers the payoff.

# SEO CAPTION (ready-to-post)
For each reel, write a **complete, ready-to-post social media caption** in `seo_caption`. The client should be able to copy-paste this directly when uploading the reel. The caption MUST:
- **Match the specific video content** — reference what the person actually says/does in this reel.
- Open with a scroll-stopping first line (this shows in the "…more" preview).
- Include 2–3 sentences of value/context that make a viewer want to watch, share, or save.
- End with a clear CTA (question, tag prompt, or save/share nudge).
- Include 15–20 relevant hashtags (mix of broad reach + niche/industry-specific).
- Include the person's name / company / niche naturally so it helps their discoverability.
- Be written as if the client's social media manager wrote it — professional but human, not robotic.

# QUALITY CHECK (verify before returning)
- HOOK is order 1 in `playback_segments` (plays first in final cut) and **first words are the guest**, not VO/host/silence.
- Sum of segment lengths is ≥ 40s and ≤ 60s; timestamps add up; no overlapping HOOK quotes across the 10 reels.
- Each reel stands alone; 10 different themes; hook would stop a scroll at 2x speed.
- Every `seo_caption` is unique, specific to that reel's content, and ready to post as-is.
- Every reel has a `segment_label` and exactly 2 key quotes.

# OUTPUT — Return ONLY valid JSON (no markdown). Each reel MUST include `playback_segments` (this is the source of truth for stitching order).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSCRIPT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ts_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
JSON SHAPE (example — replace with real values):
{{
  "reels": [
    {{
      "id": 1,
      "segment_label": "Part A — Origin Story",
      "title": "4–7 word punchy title",
      "theme": "One line what this reel is about",
      "hook_type": "CONTRARIAN / STAKES / CURIOSITY / EMOTION / INSIDER",
      "hook_line": "Exact quoted hook line from transcript (inside HOOK segment times)",
      "key_quote_1": "Verbatim strongest spoken line from this reel",
      "key_quote_2": "Verbatim second impactful spoken line from this reel",
      "suggested_text_overlay": "7–10 words for on-screen text",
      "suggested_caption": "1–2 lines + question + 3–5 hashtags as one string",
      "seo_caption": "Full ready-to-post caption: scroll-stopping opener → 2–3 value sentences → CTA → 15–20 hashtags. Written as if the client's social media manager wrote it.",
      "why_will_perform": "2 short sentences on algorithm levers",
      "assembly_note": "Final playback = playback_segments in ascending order",
      "playback_segments": [
        {{
          "order": 1,
          "role": "HOOK",
          "start_time_seconds": 0.0,
          "end_time_seconds": 0.0,
          "description": "What is said / why it stops the scroll"
        }},
        {{
          "order": 2,
          "role": "BODY",
          "start_time_seconds": 0.0,
          "end_time_seconds": 0.0,
          "description": "Context or payoff after hook"
        }}
      ]
    }}
  ]
}}"""

    with client.messages.stream(
        model=model,
        max_tokens=24000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        full_text = stream.get_final_text()
    return _parse_json(full_text, "reels")


# ── Pass 2: Brand story ────────────────────────────────────────────────────────

def _extract_brand_story(
    client: Anthropic, model: str, ts_text: str, duration: str
) -> dict:
    prompt = f"""You are an elite brand storyteller, SEO copywriter, and content strategist.
You specialize in founder narratives that perform on Google, LinkedIn, and press features.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MISSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Extract and craft a 1.5–2.5 minute SEO-optimized brand story from this founder interview.
The client will copy-paste this directly into:
  → Their website About/Origin page
  → LinkedIn Featured section
  → Press kit founder bio
  → Marketing material / pitch decks

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DELIVERABLES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

① SEO HEADLINE (55–65 characters)
   — Contains primary keyword + founder name/brand + transformation/claim
   — Click-worthy but honest (no clickbait)
   — Example: "From $0 to 7 Figures: How [Name] Built [X] Without VC Funding"

② META DESCRIPTION (150–160 characters)
   — Summarizes the story arc in one punchy sentence
   — Includes primary keyword naturally
   — Ends with value proposition or intrigue
   — This goes in <meta name="description"> and LinkedIn/press summaries

③ FULL BRAND STORY (250–375 words — exactly 1.5–2.5 min spoken at 150 wpm)
   — Written in FIRST PERSON as if the founder is speaking (polished but authentic)
   — NOT corporate PR speak — raw, human, specific
   — STRUCTURE:
     PARAGRAPH 1 (Hook/Origin): Drop into a specific moment or bold statement. Grab attention.
     PARAGRAPH 2 (The World Before): What problem did they see? What was broken?
     PARAGRAPH 3 (The Leap & The Struggle): What made them start? What almost stopped them?
     PARAGRAPH 4 (Breakthrough): The moment of proof/turning point. Be specific.
     PARAGRAPH 5 (Today & Vision): Where are they now? Where are they taking this?
   — Naturally weave in 5–8 SEO keywords from their actual story
   — Avoid vague statements — use NUMBERS, NAMES, PLACES, DATES when present

④ SEO KEYWORDS (8–12 terms)
   — Mix short-tail (1–2 words) and long-tail (3–5 words)
   — Based entirely on THEIR actual content, industry, expertise
   — These should feel natural, not stuffed

⑤ DOCUMENTARY CUT SHEET — **1.5–2.5 minute sizzle ONLY (NOT the full interview)**
   — HARD RULE: The SUM of (end_time_seconds − start_time_seconds) across ALL rows MUST be **≥ 90** and **≤ 150** seconds. This is a short joined preview arc, not full documentary coverage.
   — 4–7 rows. Each row = one contiguous master clip with ABSOLUTE `start_time_seconds` / `end_time_seconds` (same timebase as transcript).
   — `sequence` = 1,2,3… is join order. `cut_instruction` = one line what to pull.

⑥ `key_moments` may be an empty array [].

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSCRIPT ({duration} total runtime)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{ts_text}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT — Return ONLY valid JSON. No markdown. No explanation.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "brand_story": {{
    "founder_name": "Name if mentioned, else empty string",
    "company_name": "Company/brand if mentioned, else empty string",
    "industry": "Their industry / niche (e.g. 'SaaS / B2B Tech', 'E-commerce', 'Health & Wellness')",
    "seo_headline": "SEO headline (55–65 chars)",
    "meta_description": "SEO meta description (150–160 chars)",
    "full_story": "Complete 250–375 word brand story in founder's first-person voice",
    "word_count": 0,
    "estimated_read_time_seconds": 0,
    "seo_keywords": [
      "keyword 1", "keyword 2", "keyword 3", "keyword 4",
      "keyword 5", "keyword 6", "keyword 7", "keyword 8"
    ],
    "journey_arc": {{
      "origin": "What was their world before? What problem did they see?",
      "leap": "What made them start / take the risk?",
      "struggle": "What almost stopped them? (specific, not generic)",
      "breakthrough": "The exact turning point — be specific",
      "today": "Where are they now?",
      "vision": "Where are they taking this?"
    }},
    "documentary_cut_sheet": [
      {{
        "sequence": 1,
        "section_title": "e.g. OPEN / STRUGGLE / TURN / TODAY",
        "start_time_seconds": 0.0,
        "end_time_seconds": 0.0,
        "cut_instruction": "One line — what to pull from master for this segment"
      }}
    ],
    "cut_sheet_assembly_note": "One line reminder: follow sequence numbers when joining",
    "key_moments": [],
    "emotional_themes": ["theme1", "theme2", "theme3"]
  }}
}}"""

    with client.messages.stream(
        model=model,
        max_tokens=6000,
        messages=[{"role": "user", "content": prompt}],
    ) as stream:
        full_text = stream.get_final_text()
    result = _parse_json(full_text, "brand_story")
    # Normalise — the JSON root key may or may not be nested
    if isinstance(result, dict) and "brand_story" in result:
        return result["brand_story"]
    return result


# ── Helpers ────────────────────────────────────────────────────────────────────

def _float_safe(x, default: float = 0.0) -> float:
    if x is None:
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _row_duration(row: dict) -> float:
    a = _float_safe(row.get("start_time_seconds"))
    b = _float_safe(row.get("end_time_seconds"))
    return max(0.0, b - a)


def _clamp_segment_row(row: dict, tmax: float) -> None:
    a = _float_safe(row.get("start_time_seconds"))
    b = _float_safe(row.get("end_time_seconds"))
    if tmax > 0:
        a = max(0.0, min(a, tmax))
        b = max(0.0, min(b, tmax))
    if b <= a:
        b = min(a + 0.25, tmax) if tmax > 0 else a + 0.25
    row["start_time_seconds"], row["end_time_seconds"] = a, b


def _playback_total_seconds(rows: list[dict]) -> float:
    return sum(_row_duration(r) for r in rows)


def _cap_playback_rows(rows: list[dict], max_total: float) -> list[dict]:
    """Trim from the end of the last segments until total duration <= max_total."""
    rows = [r for r in rows if _row_duration(r) > 0.001]
    if not rows:
        return rows
    excess = _playback_total_seconds(rows) - max_total
    while excess > 0.02 and rows:
        last = rows[-1]
        a = _float_safe(last.get("start_time_seconds"))
        b = _float_safe(last.get("end_time_seconds"))
        dur = max(0.0, b - a)
        if dur - excess >= 0.12:
            last["end_time_seconds"] = b - excess
            excess = 0.0
        elif dur > 0.12:
            last["end_time_seconds"] = a + 0.1
            excess -= dur - 0.1
        else:
            rows.pop()
            excess -= dur
    return rows


def _maybe_extend_playback_rows(
    rows: list[dict], min_total: float, transcript_end: float
) -> list[dict]:
    if not rows or transcript_end <= 0:
        return rows
    deficit = min_total - _playback_total_seconds(rows)
    if deficit <= 0.02:
        return rows
    last = rows[-1]
    a = _float_safe(last.get("start_time_seconds"))
    b = _float_safe(last.get("end_time_seconds"))
    room = transcript_end - b
    if room <= 0.02:
        return rows
    last["end_time_seconds"] = min(b + deficit, b + room, transcript_end)
    if _float_safe(last.get("end_time_seconds")) <= b + 0.01:
        return rows
    return rows


def _seg_order_key(x: dict) -> int:
    o = x.get("order")
    if o is None:
        return 0
    try:
        return int(float(o))
    except (TypeError, ValueError):
        return 0


def _build_editor_cut_sheet_from_playback(reel: dict) -> list[dict] | None:
    pbs = reel.get("playback_segments")
    if not isinstance(pbs, list) or not pbs:
        return None
    ordered = sorted(pbs, key=_seg_order_key)
    rows: list[dict] = []
    for seg in ordered:
        role = str(seg.get("role") or "BODY").strip().upper() or "BODY"
        if role not in ("HOOK", "BODY", "PAYOFF"):
            role = "BODY"
        try:
            a = float(seg.get("start_time_seconds") or 0)
            b = float(seg.get("end_time_seconds") or 0)
        except (TypeError, ValueError):
            a, b = 0.0, 0.0
        rows.append(
            {
                "order": len(rows) + 1,
                "role": role,
                "label": "HOOK" if role == "HOOK" else ("PAYOFF" if role == "PAYOFF" else "BODY"),
                "start_time_seconds": a,
                "end_time_seconds": b,
                "note": (seg.get("description") or "")[:500],
            }
        )
    for i, row in enumerate(rows, start=1):
        row["order"] = i
    return rows


def _normalize_cut_sheets(analysis: dict, transcript_duration: float = 0.0) -> None:
    """Build editor_cut_sheet from playback_segments, enforce reel 40–60s and brand 90–150s for previews."""
    tmax = max(0.0, float(transcript_duration or 0.0))

    for reel in analysis.get("reels", []):
        sheet = _build_editor_cut_sheet_from_playback(reel)
        if sheet is None:
            sheet = reel.get("editor_cut_sheet")
        if not isinstance(sheet, list):
            sheet = []

        for row in sheet:
            _clamp_segment_row(row, tmax)
            if _row_duration(row) <= 0.001:
                a = _float_safe(row.get("start_time_seconds"))
                row["end_time_seconds"] = a + 6.0
                _clamp_segment_row(row, tmax)

        sheet = [r for r in sheet if _row_duration(r) > 0.001]
        sheet = sorted(sheet, key=lambda x: (_seg_order_key(x), _float_safe(x.get("start_time_seconds"))))
        for i, row in enumerate(sheet, start=1):
            row["order"] = i

        if not sheet:
            rs = _float_safe(reel.get("start_time_seconds"))
            re_ = _float_safe(reel.get("end_time_seconds"))
            if re_ <= rs:
                re_ = rs + 45.0
            if tmax > 0:
                re_ = min(re_, tmax)
            mid = rs + min(8.0, max(4.0, (re_ - rs) * 0.15))
            sheet = [
                {
                    "order": 1,
                    "role": "HOOK",
                    "label": "HOOK",
                    "start_time_seconds": rs,
                    "end_time_seconds": min(mid, re_),
                    "note": (reel.get("hook_line") or "")[:500],
                },
                {
                    "order": 2,
                    "role": "BODY",
                    "label": "BODY",
                    "start_time_seconds": min(mid, re_),
                    "end_time_seconds": re_,
                    "note": (reel.get("editor_note") or reel.get("emotional_arc") or "")[:500],
                },
            ]
            for row in sheet:
                _clamp_segment_row(row, tmax)

        hook_row = next((r for r in sheet if str(r.get("role") or "").upper() == "HOOK"), sheet[0])
        if _row_duration(hook_row) <= 0.001:
            ha = _float_safe(hook_row.get("start_time_seconds"))
            hook_row["end_time_seconds"] = ha + 6.0
            _clamp_segment_row(hook_row, tmax)
        reel["hook_line_start_seconds"] = _float_safe(hook_row.get("start_time_seconds"))
        reel["hook_line_end_seconds"] = _float_safe(hook_row.get("end_time_seconds"))
        if reel["hook_line_end_seconds"] <= reel["hook_line_start_seconds"]:
            reel["hook_line_end_seconds"] = reel["hook_line_start_seconds"] + 5.0
        _hook_win = {
            "start_time_seconds": reel["hook_line_start_seconds"],
            "end_time_seconds": reel["hook_line_end_seconds"],
        }
        _clamp_segment_row(_hook_win, tmax)
        reel["hook_line_start_seconds"] = _float_safe(_hook_win["start_time_seconds"])
        reel["hook_line_end_seconds"] = _float_safe(_hook_win["end_time_seconds"])
        hook_row["start_time_seconds"] = reel["hook_line_start_seconds"]
        hook_row["end_time_seconds"] = reel["hook_line_end_seconds"]

        sheet = _cap_playback_rows(sheet, 60.0)
        sheet = _maybe_extend_playback_rows(sheet, 40.0, tmax)
        sheet = _cap_playback_rows(sheet, 60.0)

        hook_after = next(
            (r for r in sheet if str(r.get("role") or "").upper() == "HOOK"),
            sheet[0] if sheet else None,
        )
        if hook_after:
            reel["hook_line_start_seconds"] = _float_safe(hook_after.get("start_time_seconds"))
            reel["hook_line_end_seconds"] = _float_safe(hook_after.get("end_time_seconds"))

        all_starts = [_float_safe(r.get("start_time_seconds")) for r in sheet]
        all_ends = [_float_safe(r.get("end_time_seconds")) for r in sheet]
        reel["editor_cut_sheet"] = sheet
        reel["start_time_seconds"] = min(all_starts) if all_starts else 0.0
        reel["end_time_seconds"] = max(all_ends) if all_ends else reel["start_time_seconds"] + 45.0
        reel["duration_seconds"] = round(_playback_total_seconds(sheet), 1)

    brand = analysis.get("brand_story") or {}
    dcs = brand.get("documentary_cut_sheet") or brand.get("cut_sheet")
    if not isinstance(dcs, list):
        dcs = []
    if not dcs:
        kms = brand.get("key_moments")
        if isinstance(kms, list) and kms:
            sorted_km = sorted(kms, key=lambda m: _float_safe(m.get("timestamp_seconds")))
            cap_rows = 5
            budget = 120.0
            n = min(cap_rows, len(sorted_km)) or 1
            per = min(24.0, budget / n)
            for i, m in enumerate(sorted_km[:cap_rows]):
                ts = _float_safe(m.get("timestamp_seconds"))
                end_ts = min(ts + per, ts + 28.0)
                if tmax > 0:
                    end_ts = min(end_ts, tmax)
                dcs.append(
                    {
                        "sequence": i + 1,
                        "section_title": m.get("moment_type") or "BEAT",
                        "start_time_seconds": ts,
                        "end_time_seconds": max(end_ts, ts + 5.0),
                        "cut_instruction": (
                            m.get("narrative_significance") or m.get("quote") or ""
                        )[:500],
                    }
                )
    else:
        dcs = sorted(
            dcs,
            key=lambda x: (_seg_order_key({**x, "order": x.get("sequence")}), _float_safe(x.get("start_time_seconds"))),
        )
        for i, row in enumerate(dcs, start=1):
            row["sequence"] = i

    for row in dcs:
        _clamp_segment_row(row, tmax)

    while dcs:
        cur = sum(
            max(0.0, _float_safe(r.get("end_time_seconds")) - _float_safe(r.get("start_time_seconds")))
            for r in dcs
        )
        if cur <= 150.0 + 0.01:
            break
        last = dcs[-1]
        a = _float_safe(last.get("start_time_seconds"))
        b = _float_safe(last.get("end_time_seconds"))
        dur = max(0.0, b - a)
        excess = cur - 150.0
        if dur - excess >= 1.0:
            last["end_time_seconds"] = b - excess
            break
        dcs.pop()

    if dcs and tmax > 0:
        cur = sum(
            max(0.0, _float_safe(r.get("end_time_seconds")) - _float_safe(r.get("start_time_seconds")))
            for r in dcs
        )
        if cur < 90.0 - 0.5:
            deficit = 90.0 - cur
            last = dcs[-1]
            b = _float_safe(last.get("end_time_seconds"))
            room = tmax - b
            if room > 0.5:
                last["end_time_seconds"] = min(b + deficit, b + room, tmax)

    while dcs:
        cur = sum(
            max(0.0, _float_safe(r.get("end_time_seconds")) - _float_safe(r.get("start_time_seconds")))
            for r in dcs
        )
        if cur <= 150.0 + 0.01:
            break
        last = dcs[-1]
        a = _float_safe(last.get("start_time_seconds"))
        b = _float_safe(last.get("end_time_seconds"))
        dur = max(0.0, b - a)
        excess = cur - 150.0
        if dur - excess >= 1.0:
            last["end_time_seconds"] = b - excess
            break
        dcs.pop()

    brand["documentary_cut_sheet"] = dcs
    brand.setdefault(
        "cut_sheet_assembly_note",
        "Cut and join segments in SEQUENCE order on your timeline (brand sizzle target 1.5–2.5 min total).",
    )
    analysis["brand_story"] = brand


def _attach_verbatim_for_segments(analysis: dict, transcript: dict) -> None:
    """Add verbatim_transcript from Rev.ai words for brand rows and reel cut-sheet parts."""
    words = transcript.get("words") or []
    brand = analysis.get("brand_story") or {}
    for row in brand.get("documentary_cut_sheet") or []:
        try:
            a = float(row.get("start_time_seconds") or 0)
            b = float(row.get("end_time_seconds") or 0)
        except (TypeError, ValueError):
            a, b = 0.0, 0.0
        row["verbatim_transcript"] = verbatim_from_words(words, a, b)

    for reel in analysis.get("reels", []):
        try:
            hs = float(reel.get("hook_line_start_seconds") or reel.get("start_time_seconds") or 0)
            he = float(reel.get("hook_line_end_seconds") or hs)
        except (TypeError, ValueError):
            hs, he = 0.0, 0.0
        reel["hook_line_verbatim"] = verbatim_from_words(words, hs, he)
        for part in reel.get("editor_cut_sheet") or []:
            try:
                a = float(part.get("start_time_seconds") or 0)
                b = float(part.get("end_time_seconds") or 0)
            except (TypeError, ValueError):
                a, b = 0.0, 0.0
            part["verbatim_transcript"] = verbatim_from_words(words, a, b)


def _attach_words(analysis: dict, words: list) -> None:
    """Attach Rev.ai word objects across stitched reel segments (playback order)."""
    for reel in analysis.get("reels", []):
        collected: list[dict] = []
        parts = sorted(
            reel.get("editor_cut_sheet") or [],
            key=lambda x: (_seg_order_key(x), _float_safe(x.get("start_time_seconds"))),
        )
        if parts:
            for part in parts:
                start = _float_safe(part.get("start_time_seconds"))
                end = _float_safe(part.get("end_time_seconds"))
                for w in words:
                    t = _float_safe(w.get("start"))
                    if start <= t <= end:
                        collected.append(
                            {
                                "word": w.get("word", ""),
                                "time": t,
                                "ts": fmt_time(t),
                                "speaker": w.get("speaker", 0),
                            }
                        )
        else:
            start = _float_safe(reel.get("start_time_seconds"))
            end = _float_safe(reel.get("end_time_seconds"))
            for w in words:
                t = _float_safe(w.get("start"))
                if start <= t <= end:
                    collected.append(
                        {
                            "word": w.get("word", ""),
                            "time": t,
                            "ts": fmt_time(t),
                            "speaker": w.get("speaker", 0),
                        }
                    )
        collected.sort(key=lambda x: x["time"])
        seen: set[tuple[float, str]] = set()
        uniq: list[dict] = []
        for item in collected:
            key = (round(float(item["time"]), 3), str(item.get("word", "")))
            if key in seen:
                continue
            seen.add(key)
            uniq.append(item)
        reel["timestamped_words"] = uniq


def _parse_json(text: str, expected_key: str):
    """Extract and parse the first JSON object from a Claude response."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise ValueError(
            f"Claude returned no valid JSON for '{expected_key}'.\n"
            f"Response preview:\n{text[:500]}"
        )
    parsed = json.loads(match.group())
    # Unwrap top-level key if present
    if expected_key in parsed:
        return parsed[expected_key]
    return parsed


def _log(cb, msg: str):
    if cb:
        cb(msg)
