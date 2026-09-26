# Implementation plan — long-horizon graph memory

26 September 2026 · Team: Xinyi, Jiacheng, Matthew, Emmanuel · Target: integrated by 15:40; code freeze and recording at 16:00 (New York time).

## Agreed design and scope

Build one working path: timestamped 311 records → concept extraction → short-term graph → merge into the long-term graph → vector-seeded subgraph retrieval → agent recommendation.

**Louvain performs clustering. Cluster size triggers grouping. Process the largest eligible clusters first.** Grouping produces a higher-order memory with links to its supporting members. Forgetting stale memories is a separate, lower-priority operation.

The objective is to preserve useful information under a context budget. A smaller graph is not, by itself, evidence of better memory.

Keep MongoDB Atlas as the required persistent store, Voyage Automated Embeddings, Atlas Vector Search, Strands/OpenRouter and the Next.js dashboard. Use one Python backend for the proposed memory functions and NetworkX; keep an existing working backend if teammates already have one. Do not introduce a separate graph database or migrate working code for this plan. The repository began as documentation-only; this branch adds Matthew's storage-injected retrieval module, while the remaining application scaffold and Atlas adapter are still integration work.

## Work split

Assignments below are the proposed ownership split. Each person owns their files; agree interface changes in the shared contract before changing callers.

| Owner | Deliverable | Owns | Acceptance check |
| --- | --- | --- | --- |
| **Xinyi** | Input replay and concept extraction | `backend/ingestion/`, `backend/extraction/`, `fixtures/` | A small chronological input batch becomes a validated short-term graph; every fact and relation points to source records. |
| **Jiacheng** | Short-term → long-term merging | `backend/memory/merge.py`, `backend/memory/store.py`, `backend/memory/embeddings.py` | Replaying a batch adds no duplicate evidence; paraphrases can merge, but different locations and conflicting facts stay distinct. |
| **Matthew** | Long-term → session retrieval | `backend/memory/retrieval.py` | Query → vector seeds → bounded graph expansion → cited context, with deterministic node/token caps. |
| **Emmanuel** | Louvain grouping and integration | `backend/memory/grouping.py`, `backend/harness.py`, `backend/contracts.py`, `backend/api.py`, `frontend/`, `scripts/` | Largest oversized cluster is grouped first; the end-to-end path runs and exposes trace events for the demo. |

**Emmanuel is the integrator.** Prioritise the command-line end-to-end run and grouping before dashboard polish. Once extraction works, Xinyi takes the replay/evaluation run; once retrieval works, Matthew helps wire the dashboard against the frozen event contract. Jiacheng owns database write/index failures during integration.

Suggested branches: `feat/concept-extraction`, `feat/graph-merge`, `feat/subgraph-retrieval`, `feat/harness-grouping`. Use atomic semantic commits. Each owner can work against the shared fixture rather than waiting for the preceding implementation.

## First ten minutes: freeze contracts and prove access

1. Emmanuel creates the minimal backend scaffold and shared typed contracts. Keep functions callable without HTTP; add one thin API only if the dashboard needs it.
2. Jiacheng proves Atlas write/read and one real vector query. Own a single `search_memories(text, limit, filters)` adapter used by both merge and retrieval; other owners use a fixture-backed stub until it works.
3. Xinyi provides one small `GraphBatch` fixture containing a paraphrase, a distinct location, a conflicting assertion and a repeated source record. Use the same fixture across modules.
4. Matthew implements retrieval against this fixture while the index becomes ready.
5. Emmanuel supplies an event fixture immediately so the dashboard does not depend on completed backend work.

Atlas Automated Embeddings generates vectors for indexed text and query text. Index readiness and visibility of fresh writes must be checked before the demo; do not assume a newly written node is immediately searchable. If sandbox configuration blocks the automated path, time-box investigation to five minutes, then use explicit Voyage embeddings behind the same adapter and label that implementation accurately. [MongoDB Automated Embedding documentation](https://www.mongodb.com/docs/vector-search/crud-embeddings/automated-embedding/)

Use the official MongoDB driver for deterministic memory-module reads and writes. Expose these functions as agent tools. Managed MCP remains the README integration option; its setup must not block the memory pipeline.

## Shared data and function contracts

Use string IDs at module boundaries; UTC timestamps; JSON-serialisable payloads. The following are proposed application fields, not MongoDB system fields.

| Type / collection | Required fields |
| --- | --- |
| `SourceRecord` / `source_records` | `id`, `text`, `occurred_at`, `available_at`, `metadata` (including location and complaint type where available). |
| `MemoryNode` / `memory_nodes` | `id`, `kind` (`entity`, `fact`, `pattern`, `summary`), `text`, `scope_key`, `source_ids`, `first_seen_at`, `last_seen_at`, `last_retrieved_at` (nullable), `retrieval_count`, `status` (`active`, `archived`), `group_id` (nullable). |
| `MemoryEdge` / `memory_edges` | `id`, `source_id`, `target_id`, `relation`, `weight`, `source_ids`. Relation examples: `related_to`, `located_at`, `contradicts`, `member_of`. |
| `GraphBatch` / `short_term_batches` | `batch_id`, `session_id`, `as_of`, `nodes`, `edges`, `source_ids`, `status` (`pending`, `committed`). Node IDs are local until merging remaps them. |
| `MergeResult` | `batch_id`, `id_map`, `created_ids`, `updated_ids`, `edge_ids`, `committed`. |
| `RetrievalLimits` | `seed_limit` (5), `max_hops` (2), `max_nodes` (30), `max_edges` (60), `max_context_tokens` (2,000), `max_members_per_summary` (5). All are caller-overridable; values must be non-negative, with positive seed/node/token caps. |
| `RetrievedContext` | `seed_ids`, `nodes`, `edges`, `source_ids`, `context_text`, `token_count`, `truncated`. `context_text` is the compact prompt-ready rendering; the other fields retain structured provenance and trace data. |
| `GroupingResult` | `snapshot_id`, `communities`, `eligible_sizes`, `selected_member_ids`, `summary_id` (nullable), `context_tokens_before`, `context_tokens_after`. |
| `TraceEvent` | `run_id`, `sequence`, `simulated_at`, `type`, `payload`. Types: `ingested`, `extracted`, `merged`, `retrieved`, `clustered`, `grouped`, `recommended`, `scored`, `error`. |

Public functions:

```python
extract_concepts(records: list[SourceRecord], session_id: str) -> GraphBatch
merge_graph(batch: GraphBatch) -> MergeResult
retrieve_context(query: str, session_id: str, as_of: datetime,
                 limits: RetrievalLimits, *, store: RetrievalStore,
                 token_counter: TokenCounter | None = None) -> RetrievedContext
group_oversized_clusters(as_of: datetime, limits: GroupingLimits) -> GroupingResult
run_step(records: list[SourceRecord], mode: str) -> list[TraceEvent]
```

`source_ids` identify evidence, not a count supplied by the LLM. Count distinct source records for recurrence/support. A summary retains the union of its members' evidence. Create indexes for node IDs, source IDs and both edge endpoints. Jiacheng owns index definitions and the exact automated-embedding configuration.

## Xinyi — extraction

- Use one bounded 311 slice with recurring complaint types and locations across several dates. Do not load the full dataset.
- Convert structured fields directly into source metadata. Ask the LLM to chunk descriptive text by concept and return schema-constrained nodes and relations.
- Preserve identities, location, time and source references. Similar wording from different blocks must not silently become the same fact.
- Distinguish observations from hypotheses. Complaints alone do not establish an unlicensed bar or another root cause.
- Validate the result before persistence. Retry malformed output once; retain failed records for replay and emit an error instead of inventing a graph.
- Extraction produces a short-term graph. It does not decide canonical long-term IDs.

## Jiacheng — merging

1. Match exact source IDs and known entity keys first.
2. For each unmatched candidate, query the top five semantically similar long-term nodes within a compatible kind and scope.
3. Use exact identity checks or a bounded LLM decision to distinguish `same`, `related`, `contradictory` and `new`. Include locations, dates and evidence in that decision. Default uncertain cases to separate nodes.
4. Merge only equivalent nodes. Union source IDs and preserve provenance; related nodes receive an edge; conflicting assertions remain separate with a `contradicts` edge.
5. Remap local node IDs to canonical IDs, then upsert edges. Do not publish edges with missing endpoints.
6. Mark a batch committed only after all its writes succeed. For the demo use one merge writer, deterministic IDs/upserts and a batch checkpoint; replay must finish partial writes without double-counting evidence. Clear short-term working context only after commit; retain source records.

Embedding similarity can capture meaning, including paraphrases. It is a candidate-ranking signal, not an identity test or a calibrated probability. Do not choose one universal cosine threshold and use it as permission to merge. Keep newly created nodes in the current batch's candidate set so indexing delay does not create duplicates within that batch.

## Matthew — retrieval

`backend/memory/retrieval.py` defines the retrieval-specific `RetrievalLimits`, `RetrievedContext` and `RetrievalStore` protocol. The store is injected so the module can run against a fixture before Jiacheng's Atlas adapter is ready. It requires these adapter operations:

- `search_memories(text, limit, filters)` returns ranked hits shaped as `{"node": <MemoryNode document>, "score": <similarity score>}`. Support `status`, `first_seen_at`, `last_seen_at` and `group_id` filters.
- `get_memory_nodes(node_ids)` reads selected graph nodes.
- `get_memory_edges(node_ids, limit)` reads edges incident to either endpoint in the requested IDs. Edges need evidence `source_ids`; replay-time retrieval omits edges without timestampable evidence.
- `get_source_records(source_ids)` reads each source's `available_at` timestamp.
- `mark_nodes_retrieved(node_ids, retrieved_at)` increments counters only for nodes returned in context.

Retrieval steps:

1. Query the vector index for up to **5** active seed nodes, filtering `first_seen_at` and `last_seen_at` to the replay clock. Validate every node's source records against `available_at`; exclude a node if any supporting source is missing or future-only. Exclude a summary whose text may incorporate future evidence rather than trimming its citations and leaving future-derived text behind.
2. Rank seeds by vector score, with node ID as the deterministic tie-breaker. Expand through explicit edge queries with a visited set, to at most **2 hops**. Rank neighbors by parent relevance × relation factor × `0.5` per hop; stable ID ordering breaks ties. Follow `related_to`, `supports`, and `contradicts`. Do not traverse `located_at` by itself or use generic entity hubs as expansion pivots. Include graph edges in the result only when both endpoints are selected.
3. Treat summary expansion as an on-demand detail path. Include a summary seed directly. Expand its `member_of` links only when the query asks for record-level detail (one of `cite`, `evidence`, `example`, `exact`, `incident`, `proof`, `record`, `source`, `specific`, `when`, `where`, or `which`). Search within that summary's `group_id`, require a matching `member_of` edge, and take at most **5** relevant members ranked by the same query vector score. Do not expand summary members for broad questions by default.
4. Stop when any cap binds: **30 nodes, 60 edges, 2,000 context tokens**, or the applicable hop/member cap. These are initial demo limits, not tuned performance claims. Pack seed nodes first, then neighbors by descending score, depth, and ID; this keeps a selected summary ahead of its member details. Pack edges by descending weight then relation and ID. Set `truncated` when candidates are omitted by a cap.
5. Return a structured `RetrievedContext`. Its `context_text` contains the selected node text, up to five inline source IDs per node, and selected relationships in a prompt-ready format; `nodes`, `edges`, `seed_ids` and the full distinct `source_ids` remain available to the harness and dashboard. This keeps large summary provenance from consuming the prompt budget. The harness places `context_text` beside the current short-term context in the prompt. Empty retrieval returns an empty context and is valid.
6. Increment `retrieval_count` and set `last_retrieved_at` only for nodes present in the final `context_text`, using the simulated `as_of` time. Use the harness tokenizer via `token_counter` when available; otherwise use the module's deterministic UTF-8 byte-based estimate and report that it is an estimate.

No PageRank, extra graph database, runtime LLM summarization, or plan/decision persistence is part of Matthew's retrieval module. The vector search produces query-relevant seeds; edge traversal supplies bounded neighboring context. The vector index and knowledge graph remain separate structures. MongoDB requires `$vectorSearch` to be the first stage of its aggregation pipeline, so seed retrieval stays behind Jiacheng's shared `search_memories` adapter. [MongoDB query documentation](https://www.mongodb.com/docs/vector-search/query/aggregation-stages/vector-search-stage/)

## Emmanuel — Louvain, size-triggered grouping and harness

### Clustering and grouping policy

1. After a successful merge, take a graph snapshot. For this demo, cap the clustering input at **500 active, ungrouped fact/pattern nodes** and their relevant edges; report when this cap truncates the snapshot. Exclude summary nodes and generic entity hubs from the clustering projection.
2. Build an undirected weighted projection of that snapshot. Retain meaningful `related_to` links; aggregate positive support into edge weights. Exclude `contradicts`, `member_of` and self-loops. Keep the original typed graph unchanged. Add no invented links merely to obtain clusters.
3. Run NetworkX `louvain_communities(graph, weight='weight', resolution=1, seed=42)`. For an edgeless graph, return singleton communities without running Louvain. Sort the input for reproducibility.
4. Define **cluster size as the number of ungrouped fact/pattern nodes**, not the number of raw complaints, total degree or an LLM importance score.
5. A cluster becomes eligible when **size > `grouping_threshold`**, initially **8**. Sort eligible clusters by size descending, breaking ties by sorted member IDs. The threshold is configurable; do not tune it to manufacture a result.
6. Process the largest eligible cluster first, at most one cluster per maintenance pass. Persist a higher-order summary and `member_of` links, then mark the members with `group_id`. Use a fingerprint of the member IDs to make repeated attempts idempotent.
7. Keep member nodes and source records retrievable. Grouping changes the default context representation; it does not erase evidence. Record before/after context token counts and do not claim storage deletion or compression if only a summary was added.
8. Subsequent passes select the next largest eligible ungrouped cluster. Updating or recursively grouping existing summaries is deferred. Until implemented, expose new related memories separately rather than presenting an old summary as exhaustive.

**Trigger:** cluster size. **Priority:** cluster size, largest first. **Invocation point:** after a merge. Time/recency is not the grouping trigger.

Louvain is feasible for this bounded prototype: it returns communities using a modularity heuristic and supports weights, resolution and a random seed. It does not produce summaries or determine what to forget. [NetworkX documentation](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.community.louvain.louvain_communities.html)

Louvain can produce internally disconnected communities. Split any returned community into connected components before measuring eligibility; preserve isolated/rare facts instead of deleting them. Meaningful input edges matter more than adding an elaborate clustering algorithm. [Louvain/Leiden research](https://www.nature.com/articles/s41598-019-41695-z)

### Harness and display

- Run chronologically: ingest → retrieve historical context → reason/extract → merge → cluster/group → emit events. Give the agent current records directly; do not let a batch retrieve information from its own future.
- Keep model, prompts, input ordering and generation settings fixed between baseline and memory runs. Only the memory mechanism changes.
- Minimum display: current complaint batch, short-term/long-term node counts, retrieved sources, cluster sizes with selected cluster highlighted, summary and recommendation. A trace list is sufficient; an animated graph is optional.
- Show the recommended intervention as a hypothesis supported by evidence. Keep recurrence scoring separate from the memory retrieval scores.

## Integration timetable and cut line

| Time | Required outcome |
| --- | --- |
| 15:10–15:20 | Freeze contracts and shared fixtures; prove Atlas connectivity, model access and a vector query. All four owners build against fixtures. |
| 15:20–15:35 | Extraction, merge and retrieval functions work independently; Emmanuel completes size-prioritised grouping and the orchestrator. |
| 15:35–15:40 | Run one complete real Atlas path. Fix interface mismatches together. |
| 15:40–15:50 | Run the checks below; Xinyi runs replay/baseline, Matthew helps the display, Jiacheng fixes persistence, Emmanuel fixes integration. |
| 15:50–16:00 | Freeze features; prepare one reliable demo sequence and verify the recording setup. |
| 16:00 onwards | Record the one-minute video, verify playback, finish submission before the README's 17:00 deadline. |

**If behind:** keep extraction → merge → retrieval → recommendation; use a trace-based display; group only one eligible cluster. Drop animated graph rendering, recursive summaries, decay, graph-wide optimisation and production scaling. Keep real Atlas persistence and vector retrieval. Report incomplete comparison results honestly.

## Verification and demonstration

- **Provenance:** every extracted fact, merged pattern and summary resolves to existing sources.
- **Merge safety:** a paraphrase merges; different locations and conflicting facts do not; replaying the same batch changes no evidence count.
- **Retrieval bounds:** a cyclic graph terminates; archived and future-only evidence is excluded; output stays under node, edge and token caps.
- **Summary retrieval:** broad queries return the summary without all members; detail queries expand only matching `member_of` members, within node, edge and token budgets.
- **Retrieval accounting:** only nodes included in `context_text` have their counters incremented; future source evidence never appears in returned text or citations.
- **Grouping rule:** with clusters of 12, 9 and 4 ungrouped nodes and threshold 8, select 12 first, then 9 on the next pass. Size 8 does not trigger. Connectedness checks happen before these counts.
- **Grouping safety:** rerunning the same selection creates no duplicate summary; all member sources remain available; summary retrieval can expand back to members.
- **End-to-end:** an early pattern outside the baseline context window is retrieved later and cited. Show an actual run; do not assume the baseline will fail.

For recurrence, fix the cluster's complaint-type/location membership rule when it is flagged. Count complaints per observed day in matched seven-day pre/post windows; report insufficient follow-up and zero-denominator cases explicitly. Use only fields available at the replay time—later closure/resolution text must not leak into earlier decisions. Historical complaints cannot demonstrate the causal effect of a recommendation that was never executed; present recurrence as observed follow-up, not proven intervention efficacy.

The one-minute demo should show arrivals, durable merging, retrieved older evidence, the largest eligible cluster being grouped, and a cited upstream recommendation. Do not claim billion-token scalability from this bounded prototype.
