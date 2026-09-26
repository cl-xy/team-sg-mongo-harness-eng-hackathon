# Jiacheng: merge and persistence implementation

Implements the ownership and acceptance checks in `implementation-plan.md`. The
older architecture diagrams are conceptual; the implementation plan governs.

## Execution checklist

- [x] Specify merge safety and interrupted-write recovery with failing tests.
- [x] Implement deterministic merge planning, evidence unions, and checkpoints.
- [x] Implement the PyMongo store, regular indexes, and shared vector adapter.
- [x] Test automated/explicit search pipelines and bounded model decisions.
- [ ] Prove real Atlas write/read and vector visibility when credentials arrive.

## Decisions and integration boundary

- Work on `feat/graph-merge` in the current checkout. Shared contracts, extraction,
  retrieval, grouping, and harness files remain with their assigned owners.
- Accept dictionaries, dataclasses, or Pydantic models containing the plan's
  fields. Return the shared `backend.contracts.MergeResult`, including on replay
  and recovery. Persist checkpoints as serializable dictionaries.
- Treat shared source IDs as candidate lookup keys, not proof that two extracted
  facts are equivalent. One source can support multiple different facts.
- Match exact, location-scoped entity keys or equivalent text/time identities
  first; use a bounded model decision for semantic candidates. Uncertain or
  malformed decisions keep memories separate. Similarity scores never authorize
  a merge. Explicit contradictions veto equivalence.
- Persist a complete deterministic write plan before applying it. A single writer
  replays pending plans using evidence unions and deterministic edge IDs, and marks
  the batch committed only after all writes succeed. Pending writes are not an
  atomic snapshot: the harness must retrieve/group only after merge returns.
- Store original text variants with their evidence and timestamps; never replace
  canonical text with an invented summary. Retain all raw source records.
- Default to Atlas Automated Embeddings; explicit Voyage is an opt-in fallback.
  An in-memory store is for fixtures/tests only, never an automatic live fallback.

## Required access

- `MONGODB_URI` and `MONGODB_DATABASE`: hackathon sandbox database credentials;
  read/write, collection creation, regular indexes, and Search index management.
  The machine running the backend must be allowed by the Atlas network list.
- Atlas Automated Embeddings enabled/available. Project access is only necessary
  if someone must change the network list or enable the feature; teammates may
  perform those setup steps instead of sharing project-admin access.
- `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`: an accessible model supporting JSON
  structured output, for live same/related/contradictory/new judgments.
- `VOYAGE_API_KEY` only for explicit embeddings if the automated path is blocked.
- The shared contracts, real extraction path, and repository fixture are now
  covered by local integration tests; no further access is needed for these.

Keep credentials in an ignored local `.env` or environment variables. No GitHub,
Vercel, MongoDB MCP, or frontend credentials are needed for this ownership slice.

## Setup and live verification

From the repository root (Python 3.11+):

```sh
python3 -m venv .venv-memory
.venv-memory/bin/python -m pip install -r backend/memory/requirements-dev.txt
.venv-memory/bin/python -m pytest tests backend/memory/tests -q
```

The repository-root `.env` has been created locally, is ignored by Git, and has
owner-only permissions. `backend/memory/.env.example` documents its field names
without secrets. Fill the four Atlas/OpenRouter fields before live integration.

```sh
.venv-memory/bin/python -m backend.memory.embeddings --setup --probe --timeout 120
```

This command pings Atlas, creates missing regular/vector indexes, waits for the
index to report both READY and queryable, writes a uniquely scoped probe through
the merge path, checks readback and replay, and waits for that specific fresh
write to appear in a real vector query. It removes only its own probe documents
in a finally block. A timeout or API error is a failed probe, never a mock pass.
Index creation can take longer than the configured wait; rerun after checking the
Atlas index status. An incompatible existing definition is reported, not replaced.

If Automated Embeddings is blocked, investigate for at most five minutes. Set
`MEMORY_EMBEDDING_MODE=explicit` and `VOYAGE_API_KEY` to choose the explicit path.
It uses a separate default index name and embeds document and query text with
the appropriate Voyage input type. This is explicitly labeled in probe output.
For a fresh demo collection the fallback works directly; existing nodes need a
deliberate embedding backfill before they all become searchable. Do not change
embedding models/dimensions on an existing corpus without re-embedding it.

## Harness wiring

```python
from dotenv import load_dotenv
from backend.memory.store import MongoMemoryStore
from backend.memory.embeddings import AtlasMemorySearch, OpenRouterJudge, configure_search
from backend.memory.merge import MergeEngine, configure_merge, merge_graph

load_dotenv()
store = MongoMemoryStore.from_env()
search = AtlasMemorySearch.from_env(store.nodes)
store.search = search  # supplies explicit document embeddings if fallback is selected
configure_search(search)
judge = OpenRouterJudge.from_env()
configure_merge(store, search, judge)

# Recover persisted decisions before accepting another batch after a restart.
recovery = MergeEngine(store, search, judge)
for batch_id in store.pending_batch_ids():
    recovery.resume_batch(batch_id)

# Ingestion persists SourceRecords before handing GraphBatch to merge.
# for record in records: store.put_source(record)
# result = merge_graph(batch)
# Retrieve/group/clear working context only after result.committed is True.
```

`backend.memory.services.MemoryHarnessServices` implements the pulled harness
service boundary. Construct it with `store`, `search`, optional `judge`, and the
team's `extract`, `retrieve`, `recommend`, and `build_summary` callbacks. Pass it
to `backend.harness.run_step`, or expose it through a factory for the CLI's
`--services module:factory` option. The default runtime remains the team's fixture
implementation; this adapter does not select live models or retrieval implicitly.

Ingestion accepts shared and extraction SourceRecord dataclasses. The adapter
aligns the extracted batch clock to source availability (the harness replay
clock), while preserving observed node dates. Its grouping store projects persisted
documents into shared node/edge types, blocks pending merges, checks node and edge
source availability, and preserves the grouping module's snapshot-limit signal.
Hypotheses are labeled in grouping text because the shared node type has no
assertion field. Persisted nodes, variants, and judge inputs retain that field;
observation and hypothesis nodes cannot merge.

Close `store.database.client` at shutdown. Keep merge calls serialized across
processes; the demo deliberately does not implement a distributed writer lock.

Matthew can use `search.search_memories(text, limit=5, filters={...})` or the
module-level `search_memories` after `configure_search`. Results are node
dictionaries with an additional `score` field; scores rank candidates only. The
adapter defaults to active nodes and accepts indexed ID, kind, scope, status,
first/last-seen, and source-ID prefilters. Pass datetime objects for date filters.
Retrieval must still check source `available_at` at the replay clock: node dates
alone do not prove that all their evidence was available.

Extraction may include an optional `entity_key` on entity nodes. A known key is
scoped by `scope_key`; unequal known keys veto equivalence even if labels match.
Extractor facts retain their `source:<id>` scope, so separate source blocks stay
distinct. Facts at nonoverlapping observed times stay distinct (possibly related).
Use pattern nodes to represent explicitly recurring conditions across dates.
New evidence for an already grouped memory becomes a separate related memory;
the existing summary and member provenance remain stable. Summary refresh and
recursive grouping remain deferred, as specified in the implementation plan.
Local input edge endpoints must refer to nodes in that batch. Canonical edges use
deterministic endpoint/relation IDs, max input weight, and unioned source IDs;
derive support from distinct evidence, never from repeated upsert counts.

## Bounds and verification record

- Demo limit: 100 nodes and 500 edges per batch. There is one top-five Atlas
  query per unmatched node. All compatible current-batch nodes remain candidates;
  up to five recent persisted nodes cover a small index-lag window across batches.
  Beyond that window, an unindexed paraphrase may remain a separate memory.
- The production identity judge makes one request per candidate set, with at most
  210 candidates, 24,000 input characters, 8,192 output tokens and a 30-second read
  timeout. Oversized/ambiguous/malformed decisions keep nodes separate and log a
  warning where appropriate. This conservative policy can retain duplicates; it
  does not authorize lossy merges to meet a storage target.
- The combined local suite passes 65 tests plus 4 subtests, including the pulled
  harness/extraction tests, real extractor-to-merge-to-grouping integration,
  repository fixture replay, and Mongo update semantics exercised with mongomock.
  Those are not live Atlas integration tests.
- Independent review found BSON timestamp replay, future-evidence leakage,
  conflicting entity keys, and arbitrary candidate truncation issues. Each was
  reproduced with a failing test and fixed; recovery-by-ID was added as well.
- Live Atlas write/read/vector search and real-model paraphrase quality remain
  unverified; run the credentialed probe above to verify the deployment.
- Compatibility changes are contained in Jiacheng's modules and tests. No changes
  were made to teammates' implementation files.

Official API references used for the adapters:
[MongoDB automated embedding quick start](https://www.mongodb.com/docs/vector-search/tutorials/quick-start/),
[PyMongo index management](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/indexes/),
[Voyage embedding API](https://docs.voyageai.com/reference/embeddings-api),
[OpenRouter structured output](https://openrouter.ai/docs/guides/features/structured-outputs).
