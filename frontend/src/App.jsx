import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  FileSpreadsheet,
  FileVideo,
  Film,
  Loader2,
  Table2,
  UploadCloud,
} from "lucide-react";

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const ACCEPTED_TYPES = [
  ".mp4",
  ".mov",
  ".avi",
  ".mkv",
  ".webm",
  ".flv",
  ".mp3",
  ".wav",
  ".m4a",
  ".aac",
  ".flac",
  ".ogg",
].join(",");

function apiUrl(path) {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

function formatTime(seconds = 0) {
  const total = Math.max(0, Math.floor(Number(seconds) || 0));
  const minutes = Math.floor(total / 60).toString().padStart(2, "0");
  const secs = (total % 60).toString().padStart(2, "0");
  return `${minutes}:${secs}`;
}

function formatSize(bytes = 0) {
  if (!bytes) return "0 MB";
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return { detail: await response.text() };
}

export default function App() {
  const fileInputRef = useRef(null);
  const [models, setModels] = useState({});
  const [model, setModel] = useState("");
  const [file, setFile] = useState(null);
  const [job, setJob] = useState(null);
  const [activeTab, setActiveTab] = useState("table");
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const running = job?.status === "queued" || job?.status === "running";
  const result = job?.result;
  const reels = result?.analysis?.reels || [];
  const brand = result?.analysis?.brand_story || {};

  useEffect(() => {
    let mounted = true;
    fetch(apiUrl("/api/models"))
      .then(parseResponse)
      .then((data) => {
        if (!mounted) return;
        setModels(data.models || {});
        setModel(data.default_model || Object.keys(data.models || {})[0] || "");
      })
      .catch(() => {
        if (!mounted) return;
        setModels({});
      });
    return () => {
      mounted = false;
    };
  }, []);

  useEffect(() => {
    if (!job?.id || job.status === "complete" || job.status === "failed") {
      return undefined;
    }

    const poll = window.setInterval(async () => {
      try {
        const response = await fetch(apiUrl(`/api/jobs/${job.id}`));
        const data = await parseResponse(response);
        if (!response.ok) {
          throw new Error(data.detail || "Could not refresh job status.");
        }
        setJob(data);
        if (data.status === "complete") {
          setActiveTab("table");
        }
      } catch (pollError) {
        setError(pollError.message);
      }
    }, 2500);

    return () => window.clearInterval(poll);
  }, [job?.id, job?.status]);

  const tabs = useMemo(
    () => [
      { id: "table", label: "Reels Table", icon: Table2 },
      { id: "story", label: "Brand Story", icon: BookOpenText },
      ...reels.map((reel) => ({
        id: `reel-${reel.id}`,
        label: `Reel ${reel.id}`,
        icon: Film,
      })),
    ],
    [reels]
  );

  function selectFile(nextFile) {
    if (!nextFile) return;
    setFile(nextFile);
    setError("");
  }

  async function submitJob(event) {
    event.preventDefault();
    if (!file) {
      setError("Choose a video or audio file first.");
      return;
    }
    if (!model) {
      setError("Choose a Claude model.");
      return;
    }

    const body = new FormData();
    body.append("file", file);
    body.append("model", model);

    setError("");
    setJob({
      id: "",
      filename: file.name,
      status: "queued",
      progress: 0,
      logs: ["Uploading file"],
    });

    try {
      const response = await fetch(apiUrl("/api/jobs"), {
        method: "POST",
        body,
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        throw new Error(data.detail || "Could not start the job.");
      }
      setJob(data);
      setActiveTab("table");
    } catch (submitError) {
      setJob(null);
      setError(submitError.message);
    }
  }

  async function download(kind) {
    if (!job?.id) return;
    try {
      const response = await fetch(apiUrl(`/api/jobs/${job.id}/downloads/${kind}`));
      if (!response.ok) {
        const data = await parseResponse(response);
        throw new Error(data.detail || "Download failed.");
      }
      const blob = await response.blob();
      const disposition = response.headers.get("content-disposition") || "";
      const match = disposition.match(/filename="?([^"]+)"?/i);
      const fallback = "inside_success_reels.xlsx";
      const filename = match?.[1] || fallback;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (downloadError) {
      setError(downloadError.message);
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="logo-lockup">
          <img src="/inside-success-logo.png" alt="Inside Success" />
          <div>
            <h1>Reel Cuts</h1>
          </div>
        </div>
        <StatusPill job={job} />
      </header>

      <main className="workspace">
        <aside className="control-rail">
          <form onSubmit={submitJob} className="control-stack">
            <section className="control-block">
              <div className="block-title">
                <FileVideo size={18} />
                <span>Media</span>
              </div>
              <button
                type="button"
                className={`upload-zone ${dragging ? "is-dragging" : ""}`}
                onClick={() => fileInputRef.current?.click()}
                onDragEnter={(event) => {
                  event.preventDefault();
                  setDragging(true);
                }}
                onDragOver={(event) => event.preventDefault()}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => {
                  event.preventDefault();
                  setDragging(false);
                  selectFile(event.dataTransfer.files?.[0]);
                }}
              >
                <UploadCloud size={30} />
                <span>{file ? file.name : "Drop documentary file"}</span>
                <small>{file ? formatSize(file.size) : "Video or audio"}</small>
              </button>
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_TYPES}
                onChange={(event) => selectFile(event.target.files?.[0])}
                hidden
              />
            </section>

            <section className="control-block">
              <label className="field">
                <span>Model</span>
                <select value={model} onChange={(event) => setModel(event.target.value)}>
                  {Object.entries(models).map(([id, label]) => (
                    <option value={id} key={id}>
                      {label}
                    </option>
                  ))}
                  {!Object.keys(models).length && <option value="">Loading models</option>}
                </select>
              </label>
            </section>

            <button className="primary-action" disabled={running} type="submit">
              {running ? <Loader2 className="spin" size={18} /> : <Film size={18} />}
              <span>{running ? "Generating" : "Generate Reels"}</span>
            </button>
          </form>

          {job && <ProgressPanel job={job} />}
          {error && (
            <div className="alert">
              <AlertTriangle size={18} />
              <span>{error}</span>
            </div>
          )}
        </aside>

        <section className="result-area">
          {!result ? (
            <EmptyState job={job} />
          ) : (
            <>
              <ResultHeader job={job} result={result} onDownload={download} />
              <nav className="tabs" aria-label="Result sections">
                {tabs.map((tab) => {
                  const Icon = tab.icon;
                  return (
                    <button
                      key={tab.id}
                      className={activeTab === tab.id ? "active" : ""}
                      onClick={() => setActiveTab(tab.id)}
                      type="button"
                    >
                      <Icon size={16} />
                      <span>{tab.label}</span>
                    </button>
                  );
                })}
              </nav>
              <div className="result-panel">
                {activeTab === "table" && <ReelsTable reels={reels} />}
                {activeTab === "story" && <BrandStory brand={brand} />}
                {activeTab.startsWith("reel-") && (
                  <ReelDetail
                    reel={reels.find((item) => `reel-${item.id}` === activeTab)}
                  />
                )}
              </div>
            </>
          )}
        </section>
      </main>
    </div>
  );
}

function StatusPill({ job }) {
  if (!job) return <div className="status-pill idle">Ready</div>;
  if (job.status === "complete") {
    return (
      <div className="status-pill done">
        <CheckCircle2 size={16} />
        Complete
      </div>
    );
  }
  if (job.status === "failed") {
    return (
      <div className="status-pill failed">
        <AlertTriangle size={16} />
        Failed
      </div>
    );
  }
  return (
    <div className="status-pill running">
      <Loader2 className="spin" size={16} />
      Running
    </div>
  );
}

function ProgressPanel({ job }) {
  return (
    <section className="progress-panel">
      <div className="progress-top">
        <span>{job.filename}</span>
        <strong>{job.progress || 0}%</strong>
      </div>
      <div className="progress-track">
        <div style={{ width: `${job.progress || 0}%` }} />
      </div>
      <ol className="log-list">
        {(job.logs || []).slice(-8).map((line, index) => (
          <li key={`${line}-${index}`}>{line}</li>
        ))}
      </ol>
    </section>
  );
}

function EmptyState({ job }) {
  if (job?.status === "failed") {
    return (
      <div className="empty-state failed-state">
        <AlertTriangle size={42} />
        <h2>Pipeline stopped</h2>
        <p>{job.error || "The backend returned an error."}</p>
      </div>
    );
  }
  if (job) {
    return (
      <div className="empty-state">
        <Loader2 className="spin" size={42} />
        <h2>Processing documentary</h2>
        <p>Results will appear here when the backend finishes.</p>
      </div>
    );
  }
  return (
    <div className="empty-state">
      <Film size={42} />
      <h2>Upload a documentary</h2>
      <p>Generate reel picks, timestamped hooks, a brand story, and Excel.</p>
    </div>
  );
}

function ResultHeader({ job, result, onDownload }) {
  const transcript = result.transcript || {};
  const reels = result.analysis?.reels || [];
  const previews = (result.previews || []).slice();
  const dl = job?.downloads || {};
  return (
    <section className="result-header">
      <div className="result-header-top">
        <div>
          <p className="eyebrow">{result.filename}</p>
          <h2>Generated Reel Report</h2>
        </div>
        <div className="stat-row">
          <Stat value={reels.length} label="Reels" />
          <Stat value={(transcript.word_count || 0).toLocaleString()} label="Words" />
          <Stat value={transcript.duration_label || formatTime(transcript.duration)} label="Runtime" />
        </div>
        <div className="download-row">
          <button type="button" onClick={() => onDownload("xlsx")}>
            <FileSpreadsheet size={17} />
            XLSX
          </button>
          {previews.map((p) =>
            dl[p.kind] ? (
              <button key={p.kind} type="button" onClick={() => onDownload(p.kind)}>
                <FileVideo size={17} />
                {p.label}
              </button>
            ) : null,
          )}
        </div>
      </div>
      {previews.some((p) => dl[p.kind]) ? (
        <section className="preview-block">
          <h3 className="eyebrow">Cut previews (joined as suggested)</h3>
          <div className="preview-grid">
            {previews.map((p) => {
              const url = dl[p.kind];
              if (!url) return null;
              const abs = apiUrl(url);
              const isVid = p.mime?.startsWith("video/");
              return (
                <div key={p.kind} className="preview-card">
                  <p>{p.label}</p>
                  {isVid ? (
                    <video controls src={abs} preload="metadata" />
                  ) : (
                    <audio controls src={abs} preload="metadata" />
                  )}
                </div>
              );
            })}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function Stat({ value, label }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  );
}

function ReelsTable({ reels }) {
  if (!reels.length) return <p className="soft-copy">No reels were extracted.</p>;

  return (
    <div className="stack">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Title</th>
              <th>Reel start</th>
              <th>Reel end</th>
              <th>Hook line IN</th>
              <th>Hook line OUT</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {reels.map((reel) => (
              <tr key={reel.id}>
                <td>{reel.id}</td>
                <td>{reel.title}</td>
                <td>{formatTime(reel.start_time_seconds)}</td>
                <td>{formatTime(reel.end_time_seconds)}</td>
                <td>{formatTime(reel.hook_line_start_seconds ?? reel.start_time_seconds)}</td>
                <td>{formatTime(reel.hook_line_end_seconds ?? reel.start_time_seconds)}</td>
                <td>{Math.round(reel.duration_seconds || 0)}s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section>
        <h3>Cut sheet (per reel)</h3>
        <p className="soft-copy">
          Full reel range, then hook line window, then other parts — cut in order for the timeline.
        </p>
        <div className="moment-grid">
          {reels.map((reel) => (
            <article className="moment" key={`cuts-${reel.id}`}>
              <div>
                <strong>Reel {reel.id}</strong>
                <span>
                  {formatTime(reel.start_time_seconds)} – {formatTime(reel.end_time_seconds)}
                </span>
              </div>
              <p className="eyebrow">Hook line</p>
              <p>
                {formatTime(reel.hook_line_start_seconds ?? reel.start_time_seconds)} –{" "}
                {formatTime(reel.hook_line_end_seconds ?? reel.start_time_seconds)}
              </p>
              <blockquote>{reel.hook_line || reel.hook}</blockquote>
              <ul className="cut-list">
                {(reel.editor_cut_sheet || []).map((row, idx) => (
                  <li key={idx}>
                    <strong>{row.label || `Part ${idx + 1}`}</strong>{" "}
                    {formatTime(row.start_time_seconds)} – {formatTime(row.end_time_seconds)}
                    {row.note ? <span> — {row.note}</span> : null}
                  </li>
                ))}
              </ul>
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function BrandStory({ brand }) {
  if (!brand || !Object.keys(brand).length) {
    return <p className="soft-copy">No brand story was extracted.</p>;
  }

  const arc = brand.journey_arc || {};
  const arcItems = [
    ["Origin", arc.origin],
    ["The Leap", arc.leap],
    ["Struggle", arc.struggle],
    ["Breakthrough", arc.breakthrough],
    ["Today", arc.today],
    ["Vision", arc.vision],
  ].filter(([, value]) => value);

  const cutSheet = brand.documentary_cut_sheet || brand.cut_sheet || [];

  return (
    <div className="stack">
      <section className="copy-block">
        <h3>Documentary cut sheet (join in sequence order)</h3>
        {brand.cut_sheet_assembly_note ? <p>{brand.cut_sheet_assembly_note}</p> : null}
        {cutSheet.length ? (
          <div className="table-wrap">
            <table>
                <thead>
                <tr>
                  <th>Seq</th>
                  <th>Section</th>
                  <th>IN</th>
                  <th>OUT</th>
                  <th>Verbatim (transcript)</th>
                  <th>Instruction</th>
                </tr>
              </thead>
              <tbody>
                {cutSheet.map((row, idx) => (
                  <tr key={String(row.sequence ?? idx)}>
                    <td>{row.sequence}</td>
                    <td>{row.section_title}</td>
                    <td>{formatTime(row.start_time_seconds)}</td>
                    <td>{formatTime(row.end_time_seconds)}</td>
                    <td className="verbatim-cell">{row.verbatim_transcript || "—"}</td>
                    <td>{row.cut_instruction}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="soft-copy">No cut sheet rows in this result.</p>
        )}
      </section>

      <div className="brand-meta">
        <Stat value={brand.founder_name || "-"} label="Founder" />
        <Stat value={brand.company_name || "-"} label="Company" />
        <Stat value={brand.industry || "-"} label="Industry" />
      </div>

      <section className="copy-block">
        <h3>SEO Headline</h3>
        <blockquote>{brand.seo_headline}</blockquote>
        <h3>Meta Description</h3>
        <blockquote>{brand.meta_description}</blockquote>
      </section>

      <section className="story-text">
        <div>
          <h3>Full Brand Story</h3>
          <span>
            {brand.word_count || 0} words &middot; {Math.floor((brand.estimated_read_time_seconds || 0) / 60)}m{" "}
            {(brand.estimated_read_time_seconds || 0) % 60}s
          </span>
        </div>
        <div className="story-body">{brand.full_story}</div>
      </section>

      {!!(brand.seo_keywords || []).length && (
        <section>
          <h3>SEO Keywords</h3>
          <div className="keyword-row">
            {brand.seo_keywords.map((keyword) => (
              <span key={keyword}>{keyword}</span>
            ))}
          </div>
        </section>
      )}

      {!!arcItems.length && (
        <section>
          <h3>Founder Journey Arc</h3>
          <div className="arc-list">
            {arcItems.map(([label, value]) => (
              <details key={label}>
                <summary>{label}</summary>
                <p>{value}</p>
              </details>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function ReelDetail({ reel }) {
  if (!reel) return <p className="soft-copy">Choose a reel tab.</p>;
  const words = reel.timestamped_words || [];
  const chunks = [];
  for (let index = 0; index < words.length; index += 20) {
    chunks.push(words.slice(index, index + 20));
  }

  const [captionCopied, setCaptionCopied] = useState(false);
  const handleCopyCaption = () => {
    const text = reel.seo_caption || reel.suggested_caption || "";
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
      setCaptionCopied(true);
      setTimeout(() => setCaptionCopied(false), 2000);
    });
  };

  return (
    <div className="reel-detail">
      {reel.segment_label && (
        <div className="segment-badge">{reel.segment_label}</div>
      )}

      <section className="reel-summary">
        <div className="time-box">
          <span>{formatTime(reel.start_time_seconds)}</span>
          <span>{formatTime(reel.end_time_seconds)}</span>
          <small>{Math.round(reel.duration_seconds || 0)}s</small>
        </div>
        <div>
          <p className="eyebrow">{reel.hook_type}</p>
          <h2>{reel.title}</h2>
          <p className="eyebrow">Hook line window</p>
          <p>
            {formatTime(reel.hook_line_start_seconds ?? reel.start_time_seconds)} –{" "}
            {formatTime(reel.hook_line_end_seconds ?? reel.start_time_seconds)}
          </p>
          <blockquote>{reel.hook_line || reel.hook}</blockquote>
          {reel.hook_line_verbatim ? (
            <p className="soft-copy verbatim-inline">
              <strong>Transcript:</strong> {reel.hook_line_verbatim}
            </p>
          ) : null}
          <p>{reel.why_this_hooks || reel.why_compelling}</p>
          <small>{reel.assembly_note || reel.editor_note}</small>
        </div>
      </section>

      {(reel.key_quote_1 || reel.key_quote_2) && (
        <section className="key-quotes">
          <h3>Key Quotes</h3>
          {reel.key_quote_1 && <blockquote>{reel.key_quote_1}</blockquote>}
          {reel.key_quote_2 && <blockquote>{reel.key_quote_2}</blockquote>}
        </section>
      )}

      {(reel.seo_caption || reel.suggested_caption) && (
        <section className="seo-caption-block">
          <div className="seo-caption-header">
            <h3>Instagram / TikTok Caption (ready to post)</h3>
            <button type="button" className="copy-btn" onClick={handleCopyCaption}>
              {captionCopied ? "Copied!" : "Copy caption"}
            </button>
          </div>
          <p className="seo-caption-text">{reel.seo_caption || reel.suggested_caption}</p>
        </section>
      )}

      {!!(reel.editor_cut_sheet || []).length && (
        <section>
          <h3>Parts (cut in order)</h3>
          <ul className="cut-list">
            {reel.editor_cut_sheet.map((row, index) => (
              <li key={index}>
                <strong>{row.label || `Part ${index + 1}`}</strong>{" "}
                {formatTime(row.start_time_seconds)} – {formatTime(row.end_time_seconds)}
                {row.note ? <span> — {row.note}</span> : null}
                {row.verbatim_transcript ? (
                  <p className="soft-copy verbatim-inline">
                    <strong>Transcript:</strong> {row.verbatim_transcript}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      )}

      {!!(reel.key_moments || []).length && (
        <section>
          <h3>Key Moments</h3>
          <div className="moment-grid">
            {reel.key_moments.map((moment, index) => (
              <article className="moment" key={index}>
                <div>
                  <strong>{formatTime(moment.timestamp_seconds)}</strong>
                  <span>{moment.emotion}</span>
                </div>
                <p>{moment.quote}</p>
              </article>
            ))}
          </div>
        </section>
      )}

      <section>
        <h3>Timestamped Transcript</h3>
        {chunks.length ? (
          <div className="transcript">
            {chunks.map((chunk, index) => (
              <p key={index}>
                <code>{chunk[0]?.ts || formatTime(chunk[0]?.time)}</code>
                {chunk.map((word) => word.word).join(" ")}
              </p>
            ))}
          </div>
        ) : (
          <p className="transcript-fallback">{reel.transcript_excerpt}</p>
        )}
      </section>
    </div>
  );
}
