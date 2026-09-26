"""Fly.io production entry point for the Atlas-backed memory API."""

from __future__ import annotations

import os

from backend.api import MemoryApiService, create_app
from backend.memory.conversation import MongoConversationStore
from backend.memory.embeddings import AtlasMemorySearch
from backend.memory.retrieval_adapter import MongoMemoryRetrievalStore
from backend.memory.store import MongoMemoryStore


def build_app():
    """Build the WSGI app from Fly runtime environment variables.

    The Atlas database must already contain the source and memory graph data,
    with its configured Vector Search index ready for queries.
    """
    store = MongoMemoryStore.from_env()
    store.ensure_indexes()
    conversations = MongoConversationStore(store.database["short_term_events"])
    conversations.ensure_indexes()
    search = AtlasMemorySearch.from_env(store.nodes)
    retrieval = MongoMemoryRetrievalStore(store, search)
    return create_app(
        MemoryApiService(
            conversations,
            retrieval,
            sources_collection=store.sources,
            api_token=os.getenv("MEMORY_API_TOKEN"),
        )
    )


app = build_app()
