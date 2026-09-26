"""Unit and WSGI-boundary tests for the conversation memory API."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import unittest
from typing import Any, Mapping, Sequence

from backend.api import MemoryApiService, create_app
from backend.harness import HarnessClient, MemoryApiClient
from backend.memory.conversation import ConversationMessage, IdempotencyConflict


NOW = datetime(2026, 9, 26, 14, tzinfo=timezone.utc)


class FakeConversationStore:
    def __init__(self) -> None:
        self.messages: list[ConversationMessage] = []
        self.idempotency: dict[tuple[str, str], ConversationMessage] = {}

    def create_user_turn(
        self, session_id: str, prompt: str, idempotency_key: str, created_at: datetime
    ) -> ConversationMessage:
        key = (session_id, idempotency_key)
        existing = self.idempotency.get(key)
        if existing:
            if existing.role != "user" or existing.content != prompt:
                raise IdempotencyConflict("idempotency key was reused with different content")
            return existing
        message = ConversationMessage(
            f"message-{len(self.messages) + 1}", session_id,
            f"turn-{len(self.messages) + 1}", "user", prompt, created_at, idempotency_key,
        )
        self.messages.append(message)
        self.idempotency[key] = message
        return message

    def get_user_turn(self, session_id: str, turn_id: str) -> ConversationMessage | None:
        return next((
            message for message in self.messages
            if message.session_id == session_id
            and message.turn_id == turn_id
            and message.role == "user"
        ), None)

    def append_assistant_response(
        self,
        session_id: str,
        turn_id: str,
        content: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> ConversationMessage:
        if self.get_user_turn(session_id, turn_id) is None:
            raise KeyError("turn not found")
        key = (session_id, idempotency_key)
        existing = self.idempotency.get(key)
        if existing:
            if existing.turn_id != turn_id or existing.content != content:
                raise IdempotencyConflict("idempotency key was reused with different content")
            return existing
        message = ConversationMessage(
            f"message-{len(self.messages) + 1}", session_id,
            turn_id, "assistant", content, created_at, idempotency_key,
        )
        self.messages.append(message)
        self.idempotency[key] = message
        return message

    def list_messages(self, session_id: str, limit: int) -> Sequence[ConversationMessage]:
        return [message for message in self.messages if message.session_id == session_id][-limit:]


class FakeRetrievalStore:
    def __init__(self) -> None:
        self.searches: list[tuple[str, datetime]] = []
        self.hits: list[dict[str, Any]] = []
        self.sources: list[dict[str, Any]] = []

    def search_memories(self, text: str, limit: int, filters: Mapping[str, Any]) -> list[dict[str, Any]]:
        self.searches.append((text, filters["first_seen_at"]["$lte"]))
        return self.hits[:limit]

    def get_memory_nodes(self, node_ids: Sequence[str]) -> list[dict[str, Any]]:
        return []

    def get_memory_edges(self, node_ids: Sequence[str], limit: int) -> list[dict[str, Any]]:
        return []

    def get_source_records(self, source_ids: Sequence[str]) -> list[dict[str, Any]]:
        return [source for source in self.sources if source["id"] in source_ids]

    def mark_nodes_retrieved(self, node_ids: Sequence[str], retrieved_at: datetime) -> None:
        pass


class WsgiTransport:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        from urllib.parse import urlsplit

        parsed = urlsplit(path)
        encoded_body = json.dumps(body).encode("utf-8") if body is not None else b""
        environ = {
            "REQUEST_METHOD": method,
            "PATH_INFO": parsed.path,
            "QUERY_STRING": parsed.query,
            "CONTENT_LENGTH": str(len(encoded_body)),
            "wsgi.input": BytesIO(encoded_body),
        }
        if headers and "Authorization" in headers:
            environ["HTTP_AUTHORIZATION"] = headers["Authorization"]
        state: dict[str, Any] = {}

        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            state["status"] = status
            state["headers"] = headers

        response = b"".join(self.app(environ, start_response))
        self.calls.append((method, parsed.path))
        if not state["status"].startswith(("200", "201")):
            state["body"] = json.loads(response.decode("utf-8"))
            raise RuntimeError(f"HTTP {state['status']}: {state['body']}")
        return json.loads(response.decode("utf-8"))


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conversations = FakeConversationStore()
        self.graph = FakeRetrievalStore()
        self.service = MemoryApiService(
            self.conversations,
            self.graph,
            clock=lambda: NOW,
        )
        self.transport = WsgiTransport(create_app(self.service))
        self.client = MemoryApiClient(self.transport)

    def test_http_flow_persists_prompt_context_and_response(self) -> None:
        created = self.client.create_turn("session-1", "What changed?", "user-1")
        turn_id = created["turn_id"]
        context = self.client.retrieve_context("session-1", turn_id)
        response = self.client.record_response(
            "session-1", turn_id, "The pattern increased.", f"{turn_id}:assistant"
        )

        self.assertEqual(created["prompt_message"]["role"], "user")
        self.assertEqual(context["context_text"], "")
        self.assertEqual(response["role"], "assistant")
        self.assertEqual([item.role for item in self.conversations.messages], ["user", "assistant"])
        self.assertEqual(self.graph.searches[0], ("What changed?", NOW))

    def test_retry_is_idempotent_and_reuse_with_different_content_conflicts(self) -> None:
        first = self.client.create_turn("session-1", "Question", "stable-key")
        retry = self.client.create_turn("session-1", "Question", "stable-key")
        self.assertEqual(first["turn_id"], retry["turn_id"])
        self.assertEqual(len(self.conversations.messages), 1)

        with self.assertRaisesRegex(RuntimeError, "HTTP 409"):
            self.client.create_turn("session-1", "Different question", "stable-key")

    def test_missing_turn_returns_not_found(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HTTP 404"):
            self.client.retrieve_context("session-1", "unknown-turn")

    def test_validation_rejects_blank_prompt(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
            self.client.create_turn("session-1", "   ", "prompt-1")

    def test_health_check_is_public(self) -> None:
        token_service = MemoryApiService(
            self.conversations, self.graph, clock=lambda: NOW, api_token="shared-token"
        )
        transport = WsgiTransport(create_app(token_service))
        self.assertEqual(transport.request("GET", "/healthz"), {"ok": True})

    def test_api_token_rejects_unauthenticated_requests(self) -> None:
        token_service = MemoryApiService(
            self.conversations, self.graph, clock=lambda: NOW, api_token="shared-token"
        )
        transport = WsgiTransport(create_app(token_service))
        with self.assertRaisesRegex(RuntimeError, "HTTP 401"):
            transport.request("GET", "/v1/sessions/session-1/messages?limit=1")
        self.assertEqual(
            transport.request(
                "GET",
                "/v1/sessions/session-1/messages?limit=1",
                headers={"Authorization": "Bearer shared-token"},
            ),
            {"messages": []},
        )

    def test_harness_orders_memory_calls_and_injects_context(self) -> None:
        self.graph.hits = [{
            "node": {
                "id": "memory-1",
                "kind": "pattern",
                "text": "Older system pattern",
                "scope_key": "noise|Manhattan|10001",
                "source_ids": ["source-1"],
                "first_seen_at": NOW,
                "last_seen_at": NOW,
                "status": "active",
            },
            "score": 0.95,
        }]
        self.graph.sources = [{"id": "source-1", "available_at": NOW}]
        # Seed history by making a completed turn through the API.
        prior = self.client.create_turn("session-1", "Earlier question", "prior-user")
        self.client.record_response("session-1", prior["turn_id"], "Earlier answer", "prior-assistant")
        self.transport.calls.clear()
        observed: list[list[dict[str, str]]] = []

        result = HarnessClient(self.client).run_turn(
            "session-1",
            "Current question",
            "current-user",
            lambda messages: observed.append(messages) or "Current answer",
        )

        self.assertEqual(
            [method for method, _ in self.transport.calls], ["GET", "POST", "POST", "POST"]
        )
        self.assertEqual(observed[0][-1], {"role": "user", "content": "Current question"})
        self.assertEqual(observed[0][-2], {"role": "assistant", "content": "Earlier answer"})
        self.assertIn("Older system pattern", observed[0][0]["content"])
        self.assertEqual(result["assistant_message"]["content"], "Current answer")
        self.assertEqual(len(self.conversations.messages), 4)


if __name__ == "__main__":
    unittest.main()
