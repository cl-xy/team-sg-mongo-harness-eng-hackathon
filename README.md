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

## Architecture

### Data Source

NYC 311 Open Data (Socrata API). ~28M records, updated daily. No API key needed. Fields: `complaint_type`, `descriptor`, `agency`, `borough`, `incident_zip`, `created_date`, `closed_date`, `resolution_description`, `lat/lon`.

### Memory Model (Human Brain-Inspired)

**Short-term memory** (MongoDB Atlas collection)

- Raw 311 complaints as they arrive → for evaluation, simulate the drips based on timestamps
- Agent's triage decisions, conversation history
- Current working context

**Consolidation pass** (async LLM process)

- Triggers on threshold (size or time — TBD (@xinyi, @jiacheng))
- Extracts salient patterns from short-term
- Embeds patterns via Voyage AI Automated Embeddings
- Writes to long-term memory
- Prunes short-term

**Long-term memory** (MongoDB Atlas collection + Vector Search)

- Consolidated patterns as embedded documents
- Clusters of related patterns form higher-order nodes
- Edges between clusters (e.g. "noise cluster → sanitation complaints 2 days later")
- Retrieved via vector similarity on each new complaint

**Decay** (periodic process)

- Long-term memories that never get retrieved lose salience
- Prevents vector search degradation as store grows
- Runs periodically (weekly or threshold-based)

### Three Flows

1. **Short-term → Long-term:** Consolidation pass extracts patterns, embeds, stores durably. (NREM replay)
2. **Clustering within long-term:** Related patterns get grouped into higher-order nodes with relational edges. (REM recombination)
3. **Decay:** Stale memories that stopped being relevant fade. (Synaptic homeostasis)

### Feedback Loop

1. Agent flags systemic issue + recommends intervention
2. Monitor complaint recurrence rate in that cluster over following days
3. Score: did recurrence drop?
4. Score feeds back into which patterns the agent trusts, how it prioritises, what it escalates
5. Patterns that lead to bad predictions get deprioritised or pruned

## Stack

- **Data layer:** MongoDB Atlas (hackathon sandbox — MUST use this for finalist eligibility)
- **Embeddings:** Voyage AI (Automated Embeddings in Atlas)
- **Search:** Atlas Vector Search + Atlas Search
- **Agent framework:** Strands
- **Models:** via OpenRouter
- **Frontend:** Vercel v0 (Next.js dashboard)

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

### 6. Vercel v0

- Redeem $30 credits at 10:30am (code sent to checked-in attendees)
- Use to scaffold Next.js dashboard: "Build a dashboard that monitors my agent's context, memory and tool calls in real time"
- Click Deploy for instant public URL for demo submission

### 8. OpenAI Codex (optional)

- 1250 credits, code sent at 10:30am
- Must redeem with a FREE account (not a paid plan)

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
