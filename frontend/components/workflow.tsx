"use client";
import { useState } from "react";
import {
  Inbox,
  ScanSearch,
  Waypoints,
  GitMerge,
  Boxes,
  Sparkles,
  Check,
  ChevronRight,
  ArrowRight,
  Info,
} from "lucide-react";
import type { Batch, DashboardData } from "@/lib/types";
const stages = [
  {
    type: "ingested",
    title: "Ingest",
    subtitle: "Timestamped 311 records",
    icon: Inbox,
    detail:
      "Read complaints in chronological order. Each source keeps its original location, timestamp and identity.",
  },
  {
    type: "retrieved",
    title: "Retrieve",
    subtitle: "Find historical context",
    icon: ScanSearch,
    detail:
      "Retrieve older evidence before processing the current batch. The production design uses vector seeds and bounded graph traversal; this recorded adapter uses lexical overlap.",
  },
  {
    type: "extracted",
    title: "Extract",
    subtitle: "Build short-term graph",
    icon: Waypoints,
    detail:
      "Turn current records into source-linked observations and relationships. The recorded adapter extracts deterministic facts from structured fields.",
  },
  {
    type: "merged",
    title: "Merge",
    subtitle: "Preserve durable memory",
    icon: GitMerge,
    detail:
      "Commit the short-term graph into long-term memory and preserve source IDs. In this replay, persistence is in-memory; Atlas is the production store.",
  },
  {
    type: "grouped",
    title: "Group",
    subtitle: "Louvain communities",
    icon: Boxes,
    detail:
      "Group the largest eligible connected community first. Size must exceed 8 ungrouped facts or patterns. A summary retains members and their supporting sources.",
  },
  {
    type: "recommended",
    title: "Recommend",
    subtitle: "Evidence-backed hypothesis",
    icon: Sparkles,
    detail:
      "Combine current complaints with retrieved evidence to recommend an investigation. An intervention remains a hypothesis, not a proven causal fix.",
  },
];
export default function Workflow({
  data,
  batch,
}: {
  data: DashboardData;
  batch: Batch | undefined;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const selectedStage = stages.find((s) => s.type === selected);
  const event = batch?.events.find((e) => e.type === selected);
  return (
    <section className="panel workflow-panel">
      <div className="panel-heading">
        <div>
          <h2>The memory workflow</h2>
          <p>Every step from an incoming complaint to an informed response.</p>
        </div>
        <span
          className={`badge ${data.mode === "replay" ? "green" : "neutral"}`}
        >
          {data.mode === "replay" ? (
            <>
              <Check size={12} /> Batch {batch?.number} complete
            </>
          ) : (
            <>
              <Info size={12} /> Architecture view
            </>
          )}
        </span>
      </div>
      <div className="pipeline">
        {stages.map((stage, index) => {
          const Icon = stage.icon;
          const present = batch?.events.some((e) => e.type === stage.type);
          const active = selected === stage.type;
          return (
            <div className="pipeline-step-wrap" key={stage.type}>
              <button
                className={`pipeline-step ${active ? "active" : ""}`}
                onClick={() => setSelected(active ? null : stage.type)}
                aria-expanded={active}
              >
                <div className={`stage-icon stage-${index}`}>
                  <Icon size={21} />
                  <span className={`stage-status ${present ? "" : "pending"}`}>
                    {present ? <Check size={9} /> : index + 1}
                  </span>
                </div>
                <strong>{stage.title}</strong>
                <span>{stage.subtitle}</span>
                <small>
                  {data.mode === "live"
                    ? stage.type === "retrieved"
                      ? `${data.context.nodes.length} returned nodes`
                      : "Separate pipeline"
                    : stage.type === "ingested"
                      ? `${batch?.record_ids.length || 0} records`
                      : stage.type === "grouped"
                        ? present
                          ? "Summary created"
                          : "No eligible cluster"
                        : stage.type === "extracted" && present
                          ? `${batch?.events.find((e) => e.type === "extracted")?.payload.node_count} short-term nodes`
                          : present
                            ? "Completed"
                            : "Not observed"}
                </small>
              </button>
              {index < stages.length - 1 && (
                <ChevronRight size={15} className="pipeline-arrow" />
              )}
            </div>
          );
        })}
      </div>
      {selectedStage ? (
        <div className="workflow-detail">
          <div>
            <span className="eyebrow">
              Inside the pipeline <ArrowRight size={11} /> {selectedStage.title}
            </span>
            <p>
              {data.mode === "live" && selectedStage.type === "retrieved"
                ? "The PR #4 API returns a bounded context graph, source IDs and prompt-ready text for this turn."
                : selectedStage.detail}
            </p>
          </div>
          {event && (
            <details>
              <summary>Inspect event payload</summary>
              <pre>{JSON.stringify(event.payload, null, 2)}</pre>
            </details>
          )}
        </div>
      ) : (
        <div className="workflow-foot">
          <span>
            <i className="tiny-dot" /> Historical retrieval happens before new
            memories are written
          </span>
          <span>
            Click a stage to explore <ArrowRight size={12} />
          </span>
        </div>
      )}
    </section>
  );
}
