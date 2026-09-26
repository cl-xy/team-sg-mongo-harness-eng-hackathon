"""Short-term storage for raw harness conversation messages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol, Sequence
from uuid import uuid4


class IdempotencyConflict(ValueError):
    """An idempotency key was reused with different request contents."""


@dataclass(frozen=True)
class ConversationMessage:
    id: str
    session_id: str
    turn_id: str
    role: str
    content: str
    created_at: datetime
    idempotency_key: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "turn_id": self.turn_id,
            "role": self.role,
            "content": self.content,
            "created_at": _isoformat(self.created_at),
        }


class ConversationStore(Protocol):
    def create_user_turn(
        self, session_id: str, prompt: str, idempotency_key: str, created_at: datetime
    ) -> ConversationMessage: ...

    def get_user_turn(self, session_id: str, turn_id: str) -> ConversationMessage | None: ...

    def append_assistant_response(
        self,
        session_id: str,
        turn_id: str,
        content: str,
        idempotency_key: str,
        created_at: datetime,
    ) -> ConversationMessage: ...

    def list_messages(self, session_id: str, limit: int) -> Sequence[ConversationMessage]: ...


class MongoConversationStore:
    """MongoDB collection adapter; pass the Atlas ``short_term_events`` collection.

    It intentionally accepts a collection object instead of importing PyMongo,
    keeping the memory/API modules usable with test doubles and the team's
    existing MongoDB client configuration.
    """

    def __init__(self, collection: Any) -> None:
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("session_id", 1), ("idempotency_key", 1)], unique=True
        )
        self.collection.create_index(
            [("session_id", 1), ("turn_id", 1), ("role", 1)]
        )
        self.collection.create_index([("session_id", 1), ("created_at", -1)])

    def create_user_turn(
        self, session_id: str, prompt: str, idempotency_key: str, created_at: datetime
    ) -> ConversationMessage:
        existing = self._by_idempotency(session_id, idempotency_key)
        if existing is not None:
            return self._same_request(existing, "user", prompt)
        message = ConversationMessage(
            id=str(uuid4()),
            session_id=session_id,
            turn_id=str(uuid4()),
            role="user",
            content=prompt,
            created_at=_utc(created_at),
            idempotency_key=idempotency_key,
        )
        return self._insert_idempotently(message)

    def get_user_turn(self, session_id: str, turn_id: str) -> ConversationMessage | None:
        document = self.collection.find_one(
            {"session_id": session_id, "turn_id": turn_id, "role": "user"}
        )
        return _from_document(document) if document else None

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
        existing = self._by_idempotency(session_id, idempotency_key)
        if existing is not None:
            if existing.turn_id != turn_id:
                raise IdempotencyConflict("idempotency key belongs to another turn")
            return self._same_request(existing, "assistant", content)
        message = ConversationMessage(
            id=str(uuid4()),
            session_id=session_id,
            turn_id=turn_id,
            role="assistant",
            content=content,
            created_at=_utc(created_at),
            idempotency_key=idempotency_key,
        )
        return self._insert_idempotently(message)

    def list_messages(self, session_id: str, limit: int) -> Sequence[ConversationMessage]:
        cursor = self.collection.find({"session_id": session_id}).sort(
            [("created_at", -1), ("_id", -1)]
        ).limit(limit)
        return [_from_document(document) for document in reversed(list(cursor))]

    def _by_idempotency(self, session_id: str, key: str) -> ConversationMessage | None:
        document = self.collection.find_one(
            {"session_id": session_id, "idempotency_key": key}
        )
        return _from_document(document) if document else None

    def _insert_idempotently(self, message: ConversationMessage) -> ConversationMessage:
        document = {
            "_id": message.id,
            "session_id": message.session_id,
            "turn_id": message.turn_id,
            "role": message.role,
            "content": message.content,
            "created_at": message.created_at,
            "idempotency_key": message.idempotency_key,
        }
        try:
            self.collection.insert_one(document)
        except Exception as exc:
            # PyMongo DuplicateKeyError exposes code 11000. Re-read to resolve
            # retries and concurrent inserts without coupling to PyMongo types.
            if getattr(exc, "code", None) != 11000:
                raise
            existing = self._by_idempotency(message.session_id, message.idempotency_key)
            if existing is None:
                raise
            return self._same_request(existing, message.role, message.content)
        return message

    @staticmethod
    def _same_request(
        existing: ConversationMessage, role: str, content: str
    ) -> ConversationMessage:
        if existing.role != role or existing.content != content:
            raise IdempotencyConflict("idempotency key was reused with different content")
        return existing


def _from_document(document: Mapping[str, Any]) -> ConversationMessage:
    return ConversationMessage(
        id=str(document.get("_id", document.get("id"))),
        session_id=str(document["session_id"]),
        turn_id=str(document["turn_id"]),
        role=str(document["role"]),
        content=str(document["content"]),
        created_at=_utc(document["created_at"]),
        idempotency_key=str(document["idempotency_key"]),
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")
