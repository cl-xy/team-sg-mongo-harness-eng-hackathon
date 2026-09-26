"use client";
import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  FileText,
  FlaskConical,
  MessageSquare,
  Sparkles,
  Equal,
  Clock3,
} from "lucide-react";
import type { DashboardData, ResponseResult } from "@/lib/types";
function ResponseCard({
  result,
  memory,
  onSource,
}: {
  result: ResponseResult;
  memory?: boolean;
  onSource: (id: string) => void;
}) {
  const [showAllSources, setShowAllSources] = useState(false);
  const ids = [
    ...new Set([...result.current_source_ids, ...result.historical_source_ids]),
  ];
  return (
    <article className={`response-card ${memory ? "memory-response" : ""}`}>
      <div className="response-header">
        <div className={`response-icon ${memory ? "memory" : ""}`}>
          {memory ? <Sparkles size={17} /> : <MessageSquare size={17} />}
        </div>
        <div>
          <h3>{memory ? "Our response" : "Normal response"}</h3>
          <p>
            {memory
              ? "With long-term graph memory"
              : "Without long-term memory"}
          </p>
        </div>
        <span className={`badge ${memory ? "green" : "neutral"}`}>
          {memory ? "Memory" : "Baseline"}
        </span>
      </div>
      <div className="response-text">{result.text}</div>
      <div className="response-evidence">
        <span className="eyebrow">Available source evidence</span>
        {ids.length ? (
          <div className="source-chips">
            {(showAllSources ? ids : ids.slice(0, 5)).map((id) => (
              <button onClick={() => onSource(id)} key={id}>
                <FileText size={11} />
                {id}
              </button>
            ))}
            {ids.length > 5 && (
              <button
                aria-expanded={showAllSources}
                onClick={() => setShowAllSources(!showAllSources)}
              >
                {showAllSources ? "Show fewer" : `+${ids.length - 5} more`}
              </button>
            )}
          </div>
        ) : (
          <p>No structured source IDs supplied.</p>
        )}
      </div>
      <div className="response-footer">
        <span>
          {memory ? <Check size={13} /> : <MessageSquare size={13} />}
          {result.historical_source_ids.length} historical sources
        </span>
        <span>
          <Clock3 size={12} />
          {result.latency_ms === null
            ? "Not measured"
            : `${(result.latency_ms / 1000).toFixed(2)}s`}
        </span>
      </div>
    </article>
  );
}
export default function Evaluation({
  data,
  onSource,
  onEvaluate,
  compact = false,
}: {
  data: DashboardData;
  onSource: (id: string) => void;
  onEvaluate: () => void;
  compact?: boolean;
}) {
  const same = data.baseline.text === data.memory.text;
  const current = new Set(data.memory.current_source_ids).size;
  const historical = new Set(data.memory.historical_source_ids).size;
  const takeawayTitle = same
    ? historical > 0
      ? "The recommendation is unchanged. The available evidence is broader."
      : "No response difference observed in this run."
    : "Two responses, one controlled comparison.";
  const takeawayDescription =
    same && data.mode === "replay"
      ? `The deterministic adapter returns the same text; memory supplies ${historical} historical sources alongside ${current} current sources. Answer quality has not been scored.`
      : same
        ? `Both model calls returned identical text. The memory call received ${historical} historical sources; no answer-quality improvement has been demonstrated.`
        : "Both runs use the same model, prompt and recent history. Only the retrieved memory differs. More context alone does not demonstrate higher answer quality.";
  return (
    <section className="evaluation-section">
      <div className="section-heading">
        <div>
          <span className="eyebrow purple-text">THE COMPARISON</span>
          <h2>Same question. More context.</h2>
          <p>See what changes when the agent can remember.</p>
        </div>
        {compact && (
          <button className="text-button" onClick={onEvaluate}>
            Explore evaluation <ArrowUpRight size={15} />
          </button>
        )}
      </div>
      <div className="question-strip">
        <span>
          <MessageSquare size={15} />
          Prompt
        </span>
        <p>{data.prompt}</p>
        <span className="badge neutral">
          {data.mode === "replay" ? "Recorded replay" : "Same model · T = 0"}
        </span>
      </div>
      <div className="response-grid">
        <ResponseCard result={data.baseline} onSource={onSource} />
        <ResponseCard result={data.memory} memory onSource={onSource} />
      </div>
      <div className="evaluation-takeaway">
        <div className="takeaway-icon">
          {same ? <Equal size={18} /> : <FlaskConical size={18} />}
        </div>
        <div>
          <strong>{takeawayTitle}</strong>
          <p>{takeawayDescription}</p>
        </div>
      </div>
      {!compact && (
        <div className="panel metrics-table">
          <div className="panel-heading">
            <div>
              <h2>Evaluation breakdown</h2>
              <p>
                Measured values are kept separate from outcomes that need
                follow-up.
              </p>
            </div>
            <FlaskConical size={18} />
          </div>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Normal response</th>
                  <th>Our response</th>
                  <th>What it tells us</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td>Historical sources supplied</td>
                  <td>{data.baseline.historical_source_ids.length}</td>
                  <td className="green-text">{historical}</td>
                  <td>Evidence available to the response</td>
                </tr>
                <tr>
                  <td>Current sources supplied</td>
                  <td>{data.baseline.current_source_ids.length}</td>
                  <td>{current}</td>
                  <td>Source records from the latest batch</td>
                </tr>
                <tr>
                  <td>
                    Retrieved context{" "}
                    {data.mode === "replay" ? "word estimate" : "tokens"}
                  </td>
                  <td>0</td>
                  <td>
                    {data.context.token_count}
                    {data.context.truncated ? " · limited" : ""}
                  </td>
                  <td>
                    {data.mode === "replay"
                      ? "Whitespace estimate from the replay adapter"
                      : "Backend context count; configured cap 2,000"}
                  </td>
                </tr>
                <tr>
                  <td>Model input tokens</td>
                  <td>{data.baseline.input_tokens ?? "Not measured"}</td>
                  <td>{data.memory.input_tokens ?? "Not measured"}</td>
                  <td>Provider-reported model usage</td>
                </tr>
                <tr>
                  <td>Model output tokens</td>
                  <td>{data.baseline.output_tokens ?? "Not measured"}</td>
                  <td>{data.memory.output_tokens ?? "Not measured"}</td>
                  <td>Provider-reported model usage</td>
                </tr>
                <tr>
                  <td>Response latency</td>
                  <td>
                    {data.baseline.latency_ms === null
                      ? "Not measured"
                      : `${data.baseline.latency_ms} ms`}
                  </td>
                  <td>
                    {data.memory.latency_ms === null
                      ? "Not measured"
                      : `${data.memory.latency_ms} ms`}
                  </td>
                  <td>Model call only, excluding retrieval</td>
                </tr>
                <tr>
                  <td>Answer quality</td>
                  <td>Not scored</td>
                  <td>Not scored</td>
                  <td>Requires an independent evaluation rubric</td>
                </tr>
                <tr>
                  <td>Complaint recurrence</td>
                  <td>Insufficient follow-up</td>
                  <td>Insufficient follow-up</td>
                  <td>Matched 7-day observed windows required</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}
