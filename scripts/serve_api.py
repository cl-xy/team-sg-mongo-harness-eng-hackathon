"""Start the memory API server backed by Atlas for live demo."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.atlas import _load_env, connect
from backend.api import MemoryApiService, serve
from backend.memory.conversation import MongoConversationStore
from backend.memory.retrieval_adapter import MongoMemoryRetrievalStore
from backend.memory.embeddings import AtlasMemorySearch


def main() -> None:
    env = _load_env()
    db = connect()
    print(f"Connected to Atlas: {db.name}")
    print(f"  memory_nodes: {db['memory_nodes'].estimated_document_count()}")
    print(f"  memory_edges: {db['memory_edges'].estimated_document_count()}")
    print(f"  source_records: {db['source_records'].estimated_document_count()}")

    index_name = os.getenv("MEMORY_VECTOR_INDEX", "memory_automated_v1")
    search = AtlasMemorySearch(db["memory_nodes"], index_name=index_name)
    print(f"  vector index: {index_name}")

    conversation = MongoConversationStore(db["short_term_events"])
    conversation.ensure_indexes()

    class _Collections:
        def __init__(self, db):
            self.nodes = db["memory_nodes"]
            self.edges = db["memory_edges"]
            self.sources = db["source_records"]

    retrieval = MongoMemoryRetrievalStore(_Collections(db), search)

    service = MemoryApiService(conversation, retrieval, sources_collection=db["source_records"])

    host = os.getenv("API_HOST", "127.0.0.1")
    port = int(os.getenv("API_PORT", "8000"))
    print(f"\nServing on http://{host}:{port}")
    serve(service, host, port)


if __name__ == "__main__":
    main()
