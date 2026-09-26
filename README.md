# Team Singapore Long Horizon Engineering 🇸🇬

## Problem Statement

Statement Two: Long Horizon Engineering. Build a harness that sustains coherent memory across billions of tokens, optimises toward long-term goals, and learns from hard metric signals.

## Toy Long-horizon Task Example

An agent that continuously processes NYC 311 complaints and identifies systemic issues generating repeat complaints. It recommends upstream fixes to eliminate complaint clusters at the source.

## Task

"Your job is to identify systemic issues generating repeat 311 complaints and recommend the upstream fix that eliminates them."

Not per-ticket triage. The agent detects patterns that only become visible over days/weeks, e.g. 30 noise complaints on the same block over 3 weeks → a new bar opened without a sound permit → recommend enforcement visit.

## Metric Signal

**Complaint recurrence rate.** After the agent flags a systemic issue and recommends an intervention, did new complaints in that cluster drop in the following week? Measured directly from the data.

This recurrence score and the feedback loop below are target behaviour; the current harness does not calculate or learn from post-recommendation outcomes.

## Architecture

This section describes the target architecture. The implemented Python harness is narrower; see [Implemented Python Loop](#implemented-python-loop) and [Harness CLI](#harness-cli) for the current behaviour.

### Data Source

NYC 311 Open Data (Socrata API). ~28M records, updated daily. No API key needed. Fields: `complaint_type`, `descriptor`, `agency`, `borough`, `incident_zip`, `created_date`, `closed_date`, `resolution_description`, `lat/lon`.

### Memory Model (Human Brain-Inspired)

**Short-term memory** (MongoDB Atlas collection)

- Raw 311 complaints as they arrive → for evaluation, simulate the drips based on timestamps
- Agent's triage decisions, conversation history
- Current working context

**Consolidation pass** (target design; current implementation runs per batch)

- The Atlas harness currently uses a deterministic fixture extractor to create nodes for each batch
- The merge engine writes and merges those nodes in long-term memory; Atlas Automated Embeddings powers vector search when its index is ready
- LLM-based concept extraction and size/time-triggered consolidation remain future work
- Source records are retained for provenance and replay

**Long-term memory** (MongoDB Atlas collection + Vector Search)

- Consolidated patterns as embedded documents
- Clusters of related patterns form higher-order nodes
- Edges between clusters (e.g. "noise cluster → sanitation complaints 2 days later")
- Retrieved via vector similarity on each new complaint

**Decay** (planned; not implemented)

- Long-term memories that never get retrieved lose salience
- Prevents vector search degradation as store grows
- Runs periodically (weekly or threshold-based)

### Three Target Flows

1. **Short-term → Long-term:** Consolidation pass extracts patterns, embeds, stores durably. (NREM replay)
2. **Clustering within long-term:** Related patterns get grouped into higher-order nodes with relational edges. (REM recombination)
3. **Decay:** Stale memories that stopped being relevant fade. (Synaptic homeostasis)

### Feedback Loop (planned)

1. Agent flags systemic issue + recommends intervention
2. Monitor complaint recurrence rate in that cluster over following days
3. Score: did recurrence drop?
4. Score feeds back into which patterns the agent trusts, how it prioritises, what it escalates
5. Patterns that lead to bad predictions get deprioritised or pruned

## Stack

- **Data layer:** MongoDB Atlas (hackathon sandbox — MUST use this for finalist eligibility)
- **Embeddings:** Voyage AI (Automated Embeddings in Atlas)
- **Search:** Atlas Vector Search + Atlas Search
- **Agent orchestration (implemented):** custom Python CLI and harness loop (`scripts.run_harness` → `backend.harness.run_step`)
- **Agent framework (planned):** Strands is not currently used by the harness
- **Models:** via OpenRouter
- **Frontend (planned):** Vercel v0 (Next.js dashboard; not implemented in this repository)

### Implemented Python Loop

The current run is a direct Python service loop, not a Strands agent. The CLI sorts records by availability time, divides them into batches, and calls `run_step` for each batch. In memory mode, each step ingests the source records, retrieves historical context, extracts memory nodes, durably merges them, groups an eligible cluster, and produces a recommendation. The Atlas factory uses the deterministic fixture extractor; OpenRouter can be used for merge judgements and the final recommendation. Baseline mode skips retrieval, extraction, merging and grouping.

The loop emits JSON trace events for each step. Strands integration, an interactive agent tool loop, and the planned dashboard are not part of the current implementation.

## Setup Checklist

### 1. MongoDB Atlas Sandbox (REQUIRED)

- Check email for sandbox invite link
- Create project + cluster through that link
- Load or connect your 311 data
- Add your current IP address so your laptop can connect
- Enable Automated Embeddings on the long-term memory collection (select Voyage AI model, pick which fields to embed)
- Create a Vector Search index on the same collection
- Create an Atlas Search index if you need keyword/full-text queries

### 2. MongoDB MCP Server

- Use the **Atlas Managed MCP Server** — hosted, no local infra needed
- Connects via Atlas service accounts, not personal credentials
- Lets the agent read/write to Atlas through tool calls
- Alternatively: connect the **MongoDB MCP Server** to Cursor for dev-time DB access
- Team connection steps: [MongoDB Atlas MCP setup](docs/mongodb-atlas-mcp-setup.md)

### 3. MongoDB Agent Skills

- Install into Cursor / Claude Code
- Gives your AI coding assistant MongoDB best practices for schemas, queries, indexes
- Reference the **Natural Language to MongoDB Queries** prompting guide during dev

### 4. Voyage AI

- Create account: https://dash.voyageai.com
- Generate API key (save immediately — shown once)
- Add payment method (no charge, unlocks rate limits)
- 200M free tokens for the event

### 5. OpenRouter

- Credit code distributed at 10:30am after check-in
- One API key, 500+ models
- Expires 1 Oct

### 6. Frontend dashboard

- Run the Next.js dashboard locally using the [frontend setup guide](frontend/README.md).
- Inspect a recorded harness replay immediately, or configure the memory API and OpenRouter for live response comparisons.

### 8. OpenAI Codex (optional)

- 1250 credits, code sent at 10:30am
- Must redeem with a FREE account (not a paid plan)

## Harness CLI

Import every NYC 311 complaint in the six-month window directly into Atlas. The importer applies no complaint-type, borough or ZIP filters, has no row cap, and never writes a local data dump. It pages by day, preserves source IDs and event-time metadata, and keeps only fields available at complaint creation time:

```sh
uv run python -m scripts.import_311_to_atlas \
  --start 2026-03-26 \
  --end 2026-09-27
```

The end date is exclusive. The current window contains 1,964,526 NYC 311 records across all complaint types.

Run the same pipeline against the Atlas sandbox (reads `311_memory.source_records`, persists `memory_nodes`, `memory_edges` and resumable `short_term_batches`; needs `MONGODB_URI` and `MONGODB_DATABASE` in `.env`). This uses the durable graph merge service and Matthew's bounded vector-seeded graph retriever (up to 5 seeds, 2 hops, 30 nodes, 60 edges and 2,000 estimated context tokens). The vector Search index must be READY and queryable for historical retrieval; until then, exact-identity merging remains available and retrieval returns empty context. With `OPENROUTER_API_KEY` set, the final recommendation is written by the model (default `anthropic/claude-haiku-4.5`, override with `OPENROUTER_MODEL`) from the current batch, the grouped summary and retrieved historical memory; without it, or if the call fails, the template recommendation is emitted and labelled `recommender: template`:

```sh
uv run python -m scripts.run_harness \
  --records atlas \
  --services backend.atlas:create_services \
  --mode memory \
  --batch-size 200
```

The bundled `backend.runtime:create_services` factory is a deterministic, in-memory integration adapter; it does not connect to Atlas or call an LLM. It groups repeated observations using the available complaint type, descriptor and borough/ZIP fields; recommendations are explicitly labelled hypotheses, not validated root causes. Use `--mode baseline` for the no-retrieval comparison; baseline runs ingest and recommend without extracting, merging or grouping memories. The CLI prints ordered JSON trace events and exits non-zero if the run emits an error.

## Demo run

Proven end-to-end path against Atlas: deterministic extraction and merge, Louvain grouping, vector-seeded historical retrieval, and a model-written upstream-fix hypothesis citing current and historical source IDs. One 500-record batch emits every trace event type in about 30 seconds:

```sh
GROUPING_THRESHOLD=3 uv run python -m scripts.run_harness \
  --records fixtures/311-small.json \
  --services backend.atlas:create_fast_services \
  --mode memory \
  --batch-size 500
```

`backend.atlas:create_merge_services` runs Jiacheng's durable merge engine with the OpenRouter identity judge and Matthew's bounded graph retrieval through the same harness. It is slower and needs any pending batch recovered first; it is not the recorded demo path.

## Frontend dashboard

The Next.js dashboard shows the backend workflow, memory graph, source evidence, event trace and a side-by-side normal versus memory response evaluation.

```sh
cd frontend
npm install
npm run dev
```

Open http://localhost:3000. A clearly labeled recorded replay works immediately. For live comparisons, configure the merged memory API and OpenRouter in `frontend/.env.local`. See [frontend setup and evaluation details](frontend/README.md).

## Submission

- **Platform:** Cerebral Valley
- **Deliverables:** public GitHub repo + 1-min demo video + project description
- **Deadline:** 5pm Sept 26
- **Video:** verify audio + video playback, all team members added
- **Finalists:** top 6 announced on Sept 26, exhibit at MongoDB.local NYC on Sept 30 (Pier 36, 10am–4:30pm, at least 1 team member must attend)

## Useful MongoDB Resources

- **Data Modeling in MongoDB** — best practices for structuring data for agents
- **State & Persistence: The Problem of Agent Reliability** — checkpoints, suspend/resume, crash recovery
- **GraphRAG with MongoDB and LangChain** — relationship-aware context retrieval (relevant if we go explicit graph in long-term memory)
- **GenAI Showcase** — example applications across AI frameworks
- **MongoDB and Python Quickstart** — if scaffolding from scratch

## Demo Story (60 seconds)

1. Show complaints arriving into short-term memory
2. Show consolidation pass extracting patterns into long-term
3. Show the agent surfacing a systemic issue that only emerges across days of data
4. Show decay pruning stale patterns that are no longer relevant

### Evaluation

> Run A (naive baseline): sliding window context, no long-term memory. When context fills up, oldest turns get dropped or summarised. This is what ChatGPT/Claude does today.
>
> Run B (our architecture): short-term + consolidation + long-term retrieval + decay.

## Open Questions

- Consolidation trigger: fixed context size vs fixed time interval vs hybrid?
- Graph implementation: explicit graph structure in MongoDB or vector proximity as implicit clustering?
- Decay function: exponential decay on retrieval count? Time-based? Hybrid?
- Agent framework choice: Strands vs LangGraph vs custom loop?

## Key Differentiator

Not naive summarisation or unlimited accumulation. Brain-inspired memory management: consolidation (what survives), abstraction (clustering into higher-order patterns), and decay (pruning what's no longer relevant). Better context retrieval with fewer tokens.

## Attributions

We were thinking of grounding / mimicking memory storage grounded on biology: the human brain. On literature review, we discovered this paper: Kerestecioglu, D., Robsky, A., Vasters, C., Sharma, A., & Kesselman, Y. (2026). Human-inspired memory architecture for LLM agents. arXiv preprint arXiv:2605.08538. https://arxiv.org/abs/2605.08538.

In "Future Work", "while exercising the high-volume, repetitive event regime our architecture targets" → this is exactly what 311 data is.
