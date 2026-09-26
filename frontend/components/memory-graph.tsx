"use client";
import { useMemo, useState } from "react";
import { ArrowUpRight, Expand, Network, X, FileText } from "lucide-react";
import type { DashboardData, MemoryNode } from "@/lib/types";

const colors = ["#7c6cce", "#45a594", "#dd9d56", "#7393cf"];
export default function MemoryGraph({
  data,
  expanded = false,
  onExpand,
  onSource,
}: {
  data: DashboardData;
  expanded?: boolean;
  onExpand?: () => void;
  onSource: (id: string) => void;
}) {
  const [selection, setSelection] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const layout = useMemo(() => {
    const summaries = data.nodes.filter((n) => n.kind === "summary").slice(-3);
    const groups: { label: string; nodes: MemoryNode[]; total: number }[] =
      summaries.map((summary, index) => {
        const members = data.nodes.filter(
          (n) =>
            n.group_id === summary.id ||
            data.edges.some(
              (e) =>
                e.relation === "member_of" &&
                e.source_id === n.id &&
                e.target_id === summary.id,
            ),
        );
        return {
          label: `Memory group ${index + 1}`,
          nodes: [summary, ...members.slice(0, 10)],
          total: members.length,
        };
      });
    const ungrouped = data.nodes.filter(
      (n) =>
        n.kind !== "summary" &&
        !summaries.some((summary) => n.group_id === summary.id) &&
        !groups.some((g) => g.nodes.some((item) => item.id === n.id)),
    );
    if (ungrouped.length)
      groups.push({
        label:
          data.mode === "live" ? "Retrieved context" : "Other observations",
        nodes: ungrouped.slice(0, groups.length ? 10 : 30),
        total: ungrouped.length,
      });
    if (filter !== "all") {
      const filtered = data.nodes.filter((node) =>
        filter === "summary"
          ? node.kind === "summary"
          : data.context.seed_ids.includes(node.id),
      );
      return {
        groups: [],
        positions: filtered.slice(0, 30).map((node, index) => ({
          node,
          x: 370 + Math.cos(index * 2.39996) * (45 + (index % 4) * 25),
          y: 157 + Math.sin(index * 2.39996) * (45 + (index % 3) * 20),
          color: colors[index % colors.length],
          isCenter: node.kind === "summary",
        })),
      };
    }
    const count = Math.max(groups.length, 1);
    const positions = groups.flatMap((group, groupIndex) => {
      const cx = count === 1 ? 370 : 105 + groupIndex * (530 / (count - 1));
      const cy = count === 1 ? 158 : groupIndex % 2 === 0 ? 152 : 180;
      return group.nodes.map((node, index) => {
        const isCenter = node.kind === "summary";
        const angle = index * 2.39996 + groupIndex;
        const radius = isCenter ? 0 : 38 + (index % 3) * 19;
        return {
          node,
          x: cx + Math.cos(angle) * radius,
          y: cy + Math.sin(angle) * radius,
          color: colors[groupIndex % colors.length],
          isCenter,
        };
      });
    });
    return { groups, positions };
  }, [data, filter]);
  const positions = layout.positions.filter(
    (p) =>
      filter === "all" ||
      (filter === "summary"
        ? p.node.kind === "summary"
        : data.context.seed_ids.includes(p.node.id)),
  );
  const ids = new Set(positions.map((p) => p.node.id));
  const edges = data.edges.filter(
    (e) => ids.has(e.source_id) && ids.has(e.target_id),
  );
  const selected = data.nodes.find((n) => n.id === selection);
  return (
    <section
      className={`panel graph-panel ${expanded ? "graph-expanded" : ""}`}
    >
      <div className="panel-heading">
        <div>
          <h2>
            <Network size={17} />
            {data.mode === "live"
              ? "Retrieved memory graph"
              : "Long-term memory graph"}
          </h2>
          <p>Connected evidence. Preserved context.</p>
        </div>
        {onExpand && (
          <button
            className="icon-button"
            aria-label="Expand memory graph"
            onClick={onExpand}
          >
            <Expand size={16} />
          </button>
        )}
      </div>
      <div className="graph-toolbar">
        <div className="segmented" aria-label="Graph filter">
          {[
            ["all", "All memories"],
            ["summary", "Summaries"],
            ["retrieved", "Retrieved"],
          ].map(([value, label]) => (
            <button
              key={value}
              onClick={() => {
                setFilter(value);
                setSelection(null);
              }}
              aria-pressed={filter === value}
              className={filter === value ? "selected" : ""}
            >
              {label}
            </button>
          ))}
        </div>
        <span className="mini-label">
          {positions.length} of {data.nodes.length} nodes
        </span>
      </div>
      <div className="graph-canvas">
        {positions.length ? (
          <svg
            viewBox="0 0 740 315"
            role="group"
            aria-label="Schematic graph of actual memory nodes and their connections"
          >
            <defs>
              <pattern
                id="dots"
                x="0"
                y="0"
                width="18"
                height="18"
                patternUnits="userSpaceOnUse"
              >
                <circle cx="1" cy="1" r=".8" fill="#e4e6ed" />
              </pattern>
            </defs>
            <rect width="740" height="315" fill="url(#dots)" />
            {layout.groups.map((group, index) => {
              const p = layout.positions.find(
                (p) => p.node.id === group.nodes[0]?.id,
              );
              return (
                p && (
                  <g key={group.label}>
                    <text
                      x={p.x}
                      y={30}
                      textAnchor="middle"
                      fill="#667083"
                      fontSize="10"
                      fontWeight="500"
                    >
                      {group.label.toUpperCase()}
                    </text>
                  </g>
                )
              );
            })}
            {edges.map((edge) => {
              const source = positions.find(
                (p) => p.node.id === edge.source_id,
              )!;
              const target = positions.find(
                (p) => p.node.id === edge.target_id,
              )!;
              return (
                <line
                  key={edge.id}
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke={source.color}
                  strokeOpacity={edge.relation === "member_of" ? 0.5 : 0.16}
                  strokeWidth={edge.relation === "member_of" ? 1.5 : 0.8}
                  strokeDasharray={
                    edge.relation === "member_of" ? "4 3" : undefined
                  }
                />
              );
            })}
            {positions.map(({ node, x, y, color, isCenter }) => (
              <g
                key={node.id}
                role="button"
                tabIndex={0}
                aria-label={`${node.kind}: ${node.text}`}
                aria-pressed={selection === node.id}
                onClick={() => setSelection(node.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelection(node.id);
                  }
                }}
                className="graph-node"
              >
                <circle
                  cx={x}
                  cy={y}
                  r={isCenter ? 23 : 14}
                  fill="transparent"
                />
                {(isCenter || selection === node.id) && (
                  <circle
                    cx={x}
                    cy={y}
                    r={isCenter ? 24 : 14}
                    fill={color}
                    opacity=".11"
                  />
                )}
                <circle
                  cx={x}
                  cy={y}
                  r={isCenter ? 14 : 5.5}
                  fill={isCenter ? color : "#fff"}
                  stroke={color}
                  strokeWidth={isCenter ? 0 : 2}
                />
                {isCenter && (
                  <text
                    x={x}
                    y={y + 4}
                    textAnchor="middle"
                    fill="#fff"
                    fontSize="11"
                    fontWeight="600"
                  >
                    {node.source_ids.length}
                  </text>
                )}
                {data.context.seed_ids.includes(node.id) && (
                  <circle
                    cx={x}
                    cy={y}
                    r={isCenter ? 28 : 10}
                    stroke={color}
                    strokeWidth="1"
                    fill="none"
                  />
                )}
              </g>
            ))}
            <text
              x="370"
              y="294"
              textAnchor="middle"
              fill="#8b92a2"
              fontSize="10"
            >
              Select a node to inspect its evidence · Schematic layout
            </text>
          </svg>
        ) : (
          <div className="empty-state">
            <Network size={28} />
            <strong>
              No{" "}
              {filter === "all"
                ? "memory nodes"
                : filter === "summary"
                  ? "summaries"
                  : "retrieved seeds"}{" "}
              in this view
            </strong>
            <span>Try another filter or run a comparison.</span>
          </div>
        )}
      </div>
      <div className="graph-legend">
        <span>
          <i className="legend-dot purple" />
          Fact / observation
        </span>
        <span>
          <i className="legend-dot filled" />
          Higher-order summary
        </span>
        <span>
          <i className="legend-line" />
          Evidence relationship
        </span>
      </div>
      {selected && (
        <div className="node-detail">
          <div className="node-detail-heading">
            <span className="eyebrow">
              {selected.kind} · {selected.source_ids.length} sources
            </span>
            <button
              className="icon-button"
              aria-label="Close node details"
              onClick={() => setSelection(null)}
            >
              <X size={14} />
            </button>
          </div>
          <p>{selected.text}</p>
          <div className="source-chips">
            {selected.source_ids.map((id) => (
              <button key={id} onClick={() => onSource(id)}>
                <FileText size={11} />
                {id}
                <ArrowUpRight size={10} />
              </button>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
