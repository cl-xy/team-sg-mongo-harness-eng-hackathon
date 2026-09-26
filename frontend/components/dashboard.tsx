"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Clock3,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  Inbox,
  Layers3,
  LayoutDashboard,
  LoaderCircle,
  MapPin,
  Network,
  Play,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Terminal,
  X,
} from "lucide-react";
import type { Configuration, DashboardData } from "@/lib/types";
import MemoryGraph from "./memory-graph";
import Workflow from "./workflow";
import Evaluation from "./evaluation";

type View = "overview" | "memory" | "evaluation" | "events";
const navigation = [
  { id: "overview" as const, label: "Overview", icon: LayoutDashboard },
  { id: "memory" as const, label: "Memory explorer", icon: Network },
  {
    id: "evaluation" as const,
    label: "Response evaluation",
    icon: FlaskConical,
  },
  { id: "events" as const, label: "Event trace", icon: Activity },
];
const format = (value: number) => new Intl.NumberFormat("en-US").format(value);
const date = (value: string) =>
  new Date(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });

export default function Dashboard({
  initialData,
}: {
  initialData: DashboardData;
}) {
  const [data, setData] = useState(initialData);
  const [view, setView] = useState<View>("overview");
  const [batchIndex, setBatchIndex] = useState(initialData.batches.length - 1);
  const [busy, setBusy] = useState<"replay" | "evaluate" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [config, setConfig] = useState<Configuration | null>(null);
  const [modal, setModal] = useState<"settings" | "compare" | "source" | null>(
    null,
  );
  const [sourceId, setSourceId] = useState("");
  const [search, setSearch] = useState("");
  const [eventFilter, setEventFilter] = useState("all");
  const [prompt, setPrompt] = useState(
    "I'm a city council member with limited staff and budget. Which recurring 311 complaint patterns should I prioritise for the biggest constituent impact?",
  );
  const [session, setSession] = useState("311-dashboard");
  const dialog = useRef<HTMLDialogElement>(null);
  const closeDialog = useCallback(() => setModal(null), []);
  useEffect(() => {
    const readView = () => {
      const value = new URLSearchParams(window.location.search).get("view");
      setView(
        navigation.some((n) => n.id === value) ? (value as View) : "overview",
      );
    };
    readView();
    window.addEventListener("popstate", readView);
    fetch("/api/config")
      .then((r) => r.json())
      .then(setConfig)
      .catch(() => setConfig(null));
    return () => window.removeEventListener("popstate", readView);
  }, []);
  useEffect(() => {
    if (modal) dialog.current?.showModal();
    else dialog.current?.close();
  }, [modal]);
  function navigate(next: View) {
    setView(next);
    const url = new URL(window.location.href);
    url.searchParams.set("view", next);
    window.history.pushState({}, "", url);
    window.scrollTo({ top: 0, behavior: "instant" });
  }
  function inspectSource(id: string) {
    setSourceId(id);
    setModal("source");
  }
  async function runReplay() {
    setBusy("replay");
    setError("");
    setNotice("");
    try {
      const response = await fetch("/api/replay", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      setData(payload);
      setBatchIndex(payload.batches.length - 1);
      setNotice(
        "Replay complete. Both modes processed the same chronological batches.",
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Replay could not run. Previous results are still visible.",
      );
    } finally {
      setBusy(null);
    }
  }
  async function runComparison(event: React.FormEvent) {
    event.preventDefault();
    setBusy("evaluate");
    setError("");
    setNotice("");
    setModal(null);
    try {
      const response = await fetch("/api/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt,
          session_id: session,
          request_id: crypto.randomUUID(),
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error);
      setData(payload);
      setBatchIndex(0);
      navigate("evaluation");
      setNotice(
        "Comparison complete. Both responses were saved to their respective sessions.",
      );
    } catch (error) {
      setError(
        error instanceof Error
          ? error.message
          : "Comparison failed. Previous results are still visible.",
      );
    } finally {
      setBusy(null);
    }
  }
  function exportRun() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `long-horizon-${data.mode}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  const batch = data.batches[batchIndex];
  const source = data.records.find((r) => r.id === sourceId);
  const sourceNodes = data.nodes.filter((n) => n.source_ids.includes(sourceId));
  const summaries = data.nodes.filter((n) => n.kind === "summary");
  const events = data.batches.flatMap((b) =>
    b.events.map((event) => ({ ...event, batch: b.number })),
  );
  const visibleEvents = events.filter(
    (event) => eventFilter === "all" || event.type === eventFilter,
  );
  const grouped = batch?.events.find((e) => e.type === "grouped");
  const clustered = batch?.events.find((e) => e.type === "clustered");
  const communities =
    (clustered?.payload.communities as string[][] | undefined) || [];
  const selectedMembers =
    (grouped?.payload.member_ids as string[] | undefined) || [];
  const sortedCommunities = [...communities].sort(
    (a, b) => b.length - a.length,
  );
  const records = data.records.filter((r) =>
    `${r.id} ${r.text}`.toLowerCase().includes(search.toLowerCase()),
  );
  const dayCounts = data.records.reduce<Record<string, number>>(
    (acc, record) => {
      const day = record.available_at.slice(0, 10);
      acc[day] = (acc[day] || 0) + 1;
      return acc;
    },
    {},
  );
  const days = Object.entries(dayCounts).sort(([a], [b]) => a.localeCompare(b));
  const currentTitle =
    view === "overview"
      ? "Workflow overview"
      : navigation.find((n) => n.id === view)!.label;
  return (
    <div className="app-shell">
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <aside className="sidebar">
        <a className="brand" href="/?view=overview">
          <div className="brand-symbol">
            <Network size={24} strokeWidth={1.7} />
          </div>
          <div>
            long horizon<span>MEMORY INTELLIGENCE</span>
          </div>
        </a>
        <div className="workspace-switch">
          <span className="workspace-avatar">SG</span>
          <div>
            Team Singapore<small>Engineering workspace</small>
          </div>
          <ChevronDown size={14} />
        </div>
        <span className="nav-heading">WORKSPACE</span>
        <nav aria-label="Main navigation">
          {navigation.map((item) => (
            <button
              key={item.id}
              onClick={() => navigate(item.id)}
              className={`nav-item ${view === item.id ? "active" : ""}`}
              aria-current={view === item.id ? "page" : undefined}
            >
              <item.icon size={18} strokeWidth={1.7} />
              <span>{item.label}</span>
              {item.id === "events" && <small>{events.length}</small>}
            </button>
          ))}
        </nav>
        <div className="sidebar-project">
          <span className="nav-heading">CURRENT PROJECT</span>
          <div>
            <span className="project-dot" />
            <span>NYC 311 intelligence</span>
          </div>
          <p>Building a memory that lasts.</p>
        </div>
        <div className="sidebar-bottom">
          <div className="architecture-card">
            <div>
              <Layers3 size={18} />
              <span>Built to remember</span>
            </div>
            <p>
              Short-term observations.
              <br />
              Long-term understanding.
            </p>
            <button onClick={() => setModal("settings")}>
              Explore the architecture <ArrowUpRight size={13} />
            </button>
          </div>
          <button className="nav-item" onClick={() => setModal("settings")}>
            <Settings2 size={17} />
            <span>Connection settings</span>
          </button>
          <a
            className="nav-item"
            href="https://github.com/theodorayy/team-sg-mongo-harness-eng-hackathon/blob/main/docs/implementation-plan.md"
            target="_blank"
            rel="noreferrer"
          >
            <BookOpen size={17} />
            <span>Documentation</span>
            <ArrowUpRight size={13} />
          </a>
          <div className="workspace-profile">
            <span className="profile-avatar">SG</span>
            <div>
              Team Singapore<small>Long Horizon Engineering</small>
            </div>
            <span className="online-dot" />
          </div>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <div className="breadcrumbs">
            Workspace <ChevronRight size={13} />
            <span>311 intelligence</span>
          </div>
          <div className="topbar-right">
            <span className="environment">
              <i />
              {data.mode === "replay" ? "Recorded demo" : "Live comparison"}
            </span>
            <span className="topbar-divider" />
            <button
              className="icon-button"
              aria-label="About this dashboard"
              onClick={() => setModal("settings")}
            >
              <CircleHelp size={18} />
            </button>
            <span className="top-avatar">SG</span>
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                <span className="tiny-dot" /> LONG-HORIZON ENGINEERING
              </div>
              <h1>
                {currentTitle}
                <span className="title-dot">.</span>
              </h1>
              <p>
                {view === "overview"
                  ? "Follow the evidence. Understand the memory. See the difference."
                  : view === "memory"
                    ? "Explore the connections behind every memory and the sources that support it."
                    : view === "evaluation"
                      ? "A transparent comparison of responses with and without long-term memory."
                      : "Every backend event, in the order it actually happened."}
              </p>
            </div>
            <div className="page-actions">
              <button className="button secondary" onClick={exportRun}>
                <ArrowDownToLine size={15} />
                <span>Export run</span>
              </button>
              <button
                className="button primary"
                disabled={!!busy}
                onClick={runReplay}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={15} />
                ) : (
                  <Play size={14} fill="currentColor" />
                )}
                <span>
                  {busy === "evaluate"
                    ? "Comparing…"
                    : busy === "replay"
                      ? "Running…"
                      : "Run replay"}
                </span>
              </button>
            </div>
          </div>
          <div aria-live="polite">
            {error && (
              <div className="alert error" role="alert">
                <CircleHelp size={17} />
                <p>{error}</p>
                <button
                  className="icon-button"
                  onClick={() => setError("")}
                  aria-label="Dismiss error"
                >
                  <X size={15} />
                </button>
              </div>
            )}
            {notice && (
              <div className="alert success">
                <Check size={16} />
                <p>{notice}</p>
                <button
                  className="icon-button"
                  onClick={() => setNotice("")}
                  aria-label="Dismiss notice"
                >
                  <X size={15} />
                </button>
              </div>
            )}
          </div>
          <div className="run-context">
            <div>
              <span className="dataset-icon">
                <Database size={15} />
              </span>
              <strong>NYC 311</strong>
              <span className="context-separator" />
              {data.mode === "replay" ? (
                <span>Manhattan · 10031</span>
              ) : (
                <span>Retrieved context</span>
              )}
              <span className="badge neutral">
                {data.mode === "replay" ? "Noise complaints" : data.adapter}
              </span>
            </div>
            <span>
              <Clock3 size={13} />
              {data.mode === "replay" && data.records.length
                ? `${date(data.records[0].available_at)} – ${date(data.records.at(-1)!.available_at)}, 2026 · UTC`
                : new Date(data.generated_at).toLocaleString("en-US", {
                    timeZone: "UTC",
                  }) + " UTC"}
            </span>
          </div>
          {(view === "overview" || view === "memory") && (
            <div className="stats-grid">
              <Stat
                label={
                  data.mode === "replay"
                    ? "Complaints processed"
                    : "Sources retrieved"
                }
                value={format(data.record_count)}
                icon={<Inbox size={18} />}
                color="purple"
                foot={
                  data.mode === "replay"
                    ? `${data.batches.length} chronological batches`
                    : "Distinct source references"
                }
              >
                <div className="micro-bars">
                  {days.map(([day, count]) => (
                    <i
                      key={day}
                      style={{
                        height: `${8 + (count / Math.max(...days.map((d) => d[1]))) * 24}px`,
                      }}
                    />
                  ))}
                </div>
              </Stat>
              <Stat
                label={
                  data.mode === "replay"
                    ? "Long-term memories"
                    : "Retrieved nodes"
                }
                value={format(data.nodes.length)}
                icon={<Network size={18} />}
                color="blue"
                foot={`${format(data.edges.length)} evidence relationships`}
              >
                <span className="stat-annotation">
                  <GitBranch size={20} />
                  Connected
                </span>
              </Stat>
              <Stat
                label="Higher-order summaries"
                value={format(summaries.length)}
                icon={<Layers3 size={18} />}
                color="amber"
                foot={
                  data.mode === "replay"
                    ? "Evidence retained in member nodes"
                    : "Within the retrieved subgraph"
                }
              >
                <span className="stat-annotation">
                  <ShieldCheck size={20} />
                  Traceable
                </span>
              </Stat>
              <Stat
                label="Historical sources retrieved"
                value={format(data.context.source_ids.length)}
                icon={<ScanIcon />}
                color="green"
                foot={
                  data.mode === "replay"
                    ? "Available to the latest recommendation"
                    : "Available to the memory response"
                }
              >
                <span className="stat-annotation green-text">
                  <ArrowUpRight size={20} />
                  Context
                </span>
              </Stat>
            </div>
          )}
          {view === "overview" && (
            <>
              <div className="section-controls">
                <span className="eyebrow">PIPELINE AT A GLANCE</span>
                {data.batches.length > 0 && (
                  <label className="batch-picker">
                    Inspect batch
                    <select
                      aria-label="Inspect batch"
                      value={batchIndex}
                      onChange={(event) =>
                        setBatchIndex(Number(event.target.value))
                      }
                    >
                      {data.batches.map((b, index) => (
                        <option key={b.number} value={index}>
                          Batch {b.number} · {date(b.as_of)}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
              <Workflow data={data} batch={batch} />
              <div className="graph-row">
                <MemoryGraph
                  data={data}
                  onExpand={() => navigate("memory")}
                  onSource={inspectSource}
                />
                <section className="panel grouping-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Memory consolidation</h2>
                      <p>Patterns become lasting context.</p>
                    </div>
                    <Boxes size={18} />
                  </div>
                  <div className="grouping-hero">
                    <span className="consolidation-symbol">
                      <Layers3 size={25} />
                    </span>
                    <div>
                      <strong>
                        {data.mode === "replay"
                          ? "Largest cluster, first."
                          : "Evidence, connected."}
                      </strong>
                      <p>
                        {data.mode === "replay"
                          ? "Louvain finds communities. Size triggers grouping."
                          : "Only the returned context graph is visible in this run."}
                      </p>
                    </div>
                  </div>
                  {sortedCommunities.length > 0 ? (
                    <div className="cluster-list">
                      {sortedCommunities.slice(0, 3).map((members, index) => {
                        const selected = members.some((id) =>
                          selectedMembers.includes(id),
                        );
                        return (
                          <div
                            className={`cluster-item ${selected ? "chosen" : ""}`}
                            key={members[0]}
                          >
                            <div>
                              <span>Cluster {index + 1}</span>
                              {selected && (
                                <span className="badge purple">Selected</span>
                              )}
                              <strong>
                                {members.length}
                                <small> nodes</small>
                              </strong>
                            </div>
                            <div className="cluster-track">
                              <i
                                style={{
                                  width: `${(members.length / Math.max(8, sortedCommunities[0].length)) * 100}%`,
                                }}
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div className="grouping-empty">
                      {data.mode === "replay"
                        ? "No communities in this batch."
                        : "Grouping telemetry is not exposed by the conversation API."}
                    </div>
                  )}
                  <div className="grouping-rule">
                    <span>Grouping threshold</span>
                    <strong>&gt; 8 nodes</strong>
                  </div>
                  <div className="preserved-note">
                    <ShieldCheck size={16} />
                    <span>Summaries preserve their source evidence.</span>
                  </div>
                </section>
              </div>
              <Evaluation
                data={data}
                onSource={inspectSource}
                onEvaluate={() => navigate("evaluation")}
                compact
              />
              <div className="bottom-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Current complaint batch</h2>
                      <p>
                        {batch
                          ? `${batch.record_ids.length} records · ${date(batch.as_of)}`
                          : "Live conversation comparison"}
                      </p>
                    </div>
                    <button
                      className="text-button"
                      onClick={() => navigate("memory")}
                    >
                      View sources <ArrowRight size={13} />
                    </button>
                  </div>
                  <div className="record-preview">
                    {batch ? (
                      batch.record_ids.slice(0, 3).map((id) => {
                        const record = data.records.find((r) => r.id === id);
                        return (
                          <button key={id} onClick={() => inspectSource(id)}>
                            <span className="record-icon">
                              <FileText size={17} />
                            </span>
                            <div>
                              <strong>
                                {String(
                                  record?.metadata.complaint_type ||
                                    "Source record",
                                )}
                              </strong>
                              <p>
                                #{id} ·{" "}
                                {String(
                                  record?.metadata.location ||
                                    "Location unavailable",
                                )}
                              </p>
                            </div>
                            <ArrowUpRight size={14} />
                          </button>
                        );
                      })
                    ) : (
                      <p className="inline-note">
                        Source IDs are available in the response cards. The
                        conversation API does not return raw complaints.
                      </p>
                    )}
                  </div>
                </section>
                <section className="panel activity-panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Complaint arrivals</h2>
                      <p>Observed records by day · UTC</p>
                    </div>
                    <Activity size={17} />
                  </div>
                  {days.length > 0 ? (
                    <div
                      className="arrival-chart"
                      role="img"
                      aria-label={days
                        .map(([day, count]) => `${day}: ${count} records`)
                        .join(", ")}
                    >
                      {days.map(([day, count]) => (
                        <div key={day}>
                          <span>{count}</span>
                          <i
                            style={{
                              height: `${10 + (count / Math.max(...days.map((d) => d[1]))) * 70}px`,
                            }}
                          />
                          <small>{day.slice(8)}</small>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="inline-note">
                      Arrival data is not included in the context endpoint.
                    </p>
                  )}
                  <div className="chart-caption">
                    {days.length
                      ? "September 2026 · NYC 311 replay fixture"
                      : "No arrival telemetry"}
                  </div>
                </section>
              </div>
            </>
          )}
          {view === "memory" && (
            <>
              <MemoryGraph data={data} expanded onSource={inspectSource} />
              <section className="panel source-panel">
                <div className="panel-heading">
                  <div>
                    <h2>Source evidence</h2>
                    <p>Original records remain available after grouping.</p>
                  </div>
                  <label className="search-field">
                    <Search size={15} />
                    <input
                      value={search}
                      onChange={(e) => setSearch(e.target.value)}
                      placeholder="Search sources…"
                      aria-label="Search sources"
                    />
                  </label>
                </div>
                {data.records.length > 0 ? (
                  <div className="table-scroll">
                    <table>
                      <thead>
                        <tr>
                          <th>Source ID</th>
                          <th>Complaint</th>
                          <th>Location</th>
                          <th>Available at (UTC)</th>
                          <th />
                        </tr>
                      </thead>
                      <tbody>
                        {records.slice(0, 60).map((record) => (
                          <tr key={record.id}>
                            <td className="mono">#{record.id}</td>
                            <td>
                              {String(
                                record.metadata.complaint_type || record.text,
                              )}
                            </td>
                            <td>{String(record.metadata.location || "—")}</td>
                            <td>
                              {new Date(record.available_at).toLocaleString(
                                "en-US",
                                { timeZone: "UTC" },
                              )}
                            </td>
                            <td>
                              <button
                                className="icon-button"
                                onClick={() => inspectSource(record.id)}
                                aria-label={`Inspect source ${record.id}`}
                              >
                                <ArrowUpRight size={15} />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!records.length && (
                      <div className="empty-state">
                        No sources match “{search}”.
                      </div>
                    )}
                    <p className="table-foot">
                      Showing {Math.min(records.length, 60)} of {records.length}{" "}
                      matching records. Export the run for the complete dataset.
                    </p>
                  </div>
                ) : (
                  <div className="empty-state">
                    <FileText size={24} />
                    <strong>
                      Raw source records are not returned by the API.
                    </strong>
                    <span>Inspect a graph node for its source references.</span>
                  </div>
                )}
              </section>
            </>
          )}
          {view === "evaluation" && (
            <>
              <div className="live-comparison-callout">
                <div>
                  <span className="callout-icon">
                    <Sparkles size={22} />
                  </span>
                  <div>
                    <h2>Put long-term memory to the test.</h2>
                    <p>
                      Ask a question and compare two responses from the same
                      model.
                    </p>
                  </div>
                </div>
                <button
                  className="button primary"
                  onClick={() => setModal("compare")}
                  disabled={!!busy}
                >
                  {busy === "evaluate" ? (
                    <LoaderCircle className="spin" size={15} />
                  ) : (
                    <FlaskConical size={15} />
                  )}
                  New comparison
                </button>
              </div>
              <Evaluation
                data={data}
                onSource={inspectSource}
                onEvaluate={() => setModal("compare")}
              />
            </>
          )}
          {view === "events" && (
            <section className="panel events-panel">
              <div className="panel-heading">
                <div>
                  <h2>
                    Backend event log{" "}
                    <span className="badge neutral">
                      {events.length} events
                    </span>
                  </h2>
                  <p>
                    Events emitted by the harness, grouped by chronological
                    batch.
                  </p>
                </div>
                <select
                  aria-label="Filter event type"
                  value={eventFilter}
                  onChange={(e) => setEventFilter(e.target.value)}
                >
                  <option value="all">All event types</option>
                  {[...new Set(events.map((e) => e.type))].map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </div>
              {visibleEvents.map((event) => (
                <details
                  className="event-row"
                  key={`${event.run_id}-${event.sequence}`}
                >
                  <summary>
                    <span className="event-sequence">
                      {String(event.sequence + 1).padStart(2, "0")}
                    </span>
                    <span
                      className={`event-dot ${event.type === "grouped" ? "green" : ""}`}
                    />
                    <strong>{event.type}</strong>
                    <span>Batch {event.batch}</span>
                    <time>
                      {new Date(event.simulated_at).toLocaleString("en-US", {
                        timeZone: "UTC",
                      })}{" "}
                      UTC
                    </time>
                    <ChevronDown size={14} />
                  </summary>
                  <pre>{JSON.stringify(event.payload, null, 2)}</pre>
                </details>
              ))}
              {!visibleEvents.length && (
                <div className="empty-state">
                  <Terminal size={26} />
                  <strong>No pipeline trace events in this run</strong>
                  <span>
                    The PR #4 conversation API returns context and messages. Run
                    the recorded replay to inspect the full ingestion pipeline.
                  </span>
                  <button
                    className="button secondary"
                    onClick={runReplay}
                    disabled={!!busy}
                  >
                    Run replay
                  </button>
                </div>
              )}
            </section>
          )}
          <footer className="page-footer">
            <span>
              <Network size={13} /> Long Horizon <span>·</span> Team Singapore
            </span>
            <span>
              {data.mode === "replay"
                ? "Recorded in-memory harness · No live Atlas or model calls"
                : `Live memory API · ${data.adapter}`}
            </span>
          </footer>
        </main>
      </div>
      <dialog
        ref={dialog}
        onCancel={closeDialog}
        onClick={(event) => {
          if (event.target === event.currentTarget) closeDialog();
        }}
        aria-labelledby="dialog-title"
      >
        <div className="dialog-heading">
          <div>
            <span className="eyebrow">LONG HORIZON</span>
            <h2 id="dialog-title">
              {modal === "source"
                ? `Source #${sourceId}`
                : modal === "compare"
                  ? "Run a live comparison"
                  : "Your workspace connection"}
            </h2>
          </div>
          <button
            className="icon-button"
            aria-label="Close dialog"
            onClick={closeDialog}
          >
            <X size={19} />
          </button>
        </div>
        {modal === "settings" && (
          <div className="dialog-content">
            <p>
              The recorded replay works immediately. Connect the memory API from
              PR #4 and a model to run live comparisons.
            </p>
            <div className="connection-row">
              <Database size={18} />
              <div>
                <strong>Memory API</strong>
                <small>Turns, context, responses and history</small>
              </div>
              <span
                className={`badge ${config?.memory_api ? "green" : "neutral"}`}
              >
                {config?.memory_api ? "Configured" : "Not configured"}
              </span>
            </div>
            <div className="connection-row">
              <Sparkles size={18} />
              <div>
                <strong>OpenRouter model</strong>
                <small>
                  {config?.model_name ||
                    "Use the same model for both responses"}
                </small>
              </div>
              <span className={`badge ${config?.model ? "green" : "neutral"}`}>
                {config?.model ? "Configured" : "Not configured"}
              </span>
            </div>
            <p className="setup-label">
              Set these values in <code>frontend/.env.local</code>, then restart
              the frontend:
            </p>
            <pre>
              MEMORY_API_URL=http://127.0.0.1:8000{"\n"}
              OPENROUTER_API_KEY=your-key{"\n"}OPENROUTER_MODEL=your-model
            </pre>
            <p className="inline-note">
              Credentials stay on the server. Configuration status does not
              confirm connectivity. The conversation API retrieves memory;
              extraction, merging and grouping run in the separate backend
              pipeline.
            </p>
            <a
              className="button secondary"
              href="https://github.com/theodorayy/team-sg-mongo-harness-eng-hackathon/pull/4"
              target="_blank"
              rel="noreferrer"
            >
              View API integration <ArrowUpRight size={14} />
            </a>
          </div>
        )}
        {modal === "compare" && (
          <form className="dialog-content" onSubmit={runComparison}>
            <p>
              The same model, generation settings, prompt and recent
              conversation history are used for both responses. Retrieved memory
              is added only to our response.
            </p>
            <label className="form-label">
              Session ID
              <input
                value={session}
                onChange={(e) => setSession(e.target.value)}
                required
                pattern="[A-Za-z0-9._:\-]+"
                maxLength={160}
              />
            </label>
            <label className="form-label">
              Your question
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                rows={5}
                maxLength={20000}
                required
              />
            </label>
            {(!config?.memory_api || !config?.model) && (
              <div className="setup-notice">
                <Settings2 size={16} />
                <span>
                  Live comparison requires the memory API and model connection.
                </span>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => setModal("settings")}
                >
                  Setup <ArrowRight size={13} />
                </button>
              </div>
            )}
            <div className="dialog-actions">
              <button
                className="button secondary"
                type="button"
                onClick={closeDialog}
              >
                Cancel
              </button>
              <button
                className="button primary"
                type="submit"
                disabled={
                  !!busy ||
                  !config?.memory_api ||
                  !config?.model ||
                  !prompt.trim()
                }
              >
                <FlaskConical size={15} />
                Compare responses
              </button>
            </div>
          </form>
        )}
        {modal === "source" && (
          <div className="dialog-content">
            {source ? (
              <>
                <span className="badge purple">Original 311 record</span>
                <p className="source-text">{source.text}</p>
                <div className="source-metadata">
                  <span>
                    <Clock3 size={15} />
                    {new Date(source.available_at).toLocaleString("en-US", {
                      timeZone: "UTC",
                    })}{" "}
                    UTC
                  </span>
                  <span>
                    <MapPin size={15} />
                    {String(source.metadata.location || "Location unavailable")}
                  </span>
                </div>
                <details>
                  <summary>View full source record</summary>
                  <pre>{JSON.stringify(source, null, 2)}</pre>
                </details>
              </>
            ) : (
              <p>
                The API returned this source reference, but not the raw source
                record. The supporting memory text is shown below.
              </p>
            )}
            <h3 className="source-support-title">
              Supporting memories{" "}
              <span className="badge neutral">{sourceNodes.length}</span>
            </h3>
            {sourceNodes.map((node) => (
              <div className="supporting-node" key={node.id}>
                <span className="badge neutral">{node.kind}</span>
                <p>{node.text}</p>
              </div>
            ))}
            {!sourceNodes.length && (
              <p className="inline-note">
                No supporting memory node was included in this view.
              </p>
            )}
          </div>
        )}
      </dialog>
    </div>
  );
}
function ScanIcon() {
  return <Search size={18} />;
}
function Stat({
  label,
  value,
  icon,
  color,
  foot,
  children,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  color: string;
  foot: string;
  children: React.ReactNode;
}) {
  return (
    <section className="stat-card">
      <div className="stat-top">
        <span>{label}</span>
        <div className={`stat-icon ${color}`}>{icon}</div>
      </div>
      <div className="stat-value">
        <strong>{value}</strong>
        {children}
      </div>
      <p>
        <span className={`tiny-dot ${color}`} />
        {foot}
      </p>
    </section>
  );
}
