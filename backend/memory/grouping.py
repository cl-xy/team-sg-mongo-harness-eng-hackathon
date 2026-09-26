from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Protocol

import networkx as nx

from backend.contracts import GroupingLimits, GroupingResult, MemoryEdge, MemoryNode


class GroupingStore(Protocol):
    def graph_snapshot(self) -> tuple[str, Sequence[MemoryNode], Sequence[MemoryEdge]]: ...
    def insert_summary(self, summary: MemoryNode) -> None: ...
    def insert_member_edge(self, edge: MemoryEdge) -> None: ...
    def assign_group(self, member_ids: Sequence[str], summary_id: str) -> None: ...
    def context_token_count(self, node_ids: Sequence[str]) -> int: ...


SummaryBuilder = Callable[[Sequence[MemoryNode]], str]


def _fingerprint(member_ids: Sequence[str]) -> str:
    value = '\n'.join(sorted(member_ids)).encode('utf-8')
    return hashlib.sha256(value).hexdigest()[:24]


def _cluster_projection(
    nodes: Sequence[MemoryNode], edges: Sequence[MemoryEdge], limits: GroupingLimits,
) -> tuple[nx.Graph, list[MemoryNode], bool]:
    candidates = sorted(
        (node for node in nodes
         if node.kind in ('fact', 'pattern') and node.status == 'active' and node.group_id is None),
        key=lambda node: node.id,
    )
    truncated = len(candidates) > limits.max_snapshot_nodes
    selected = candidates[:limits.max_snapshot_nodes]
    selected_ids = {node.id for node in selected}
    graph = nx.Graph()
    graph.add_nodes_from(selected_ids)
    for edge in sorted(edges, key=lambda item: item.id):
        if (edge.relation == 'related_to' and edge.source_id in selected_ids
                and edge.target_id in selected_ids and edge.source_id != edge.target_id
                and edge.weight > 0):
            existing = graph.get_edge_data(edge.source_id, edge.target_id)
            graph.add_edge(
                edge.source_id,
                edge.target_id,
                weight=(existing['weight'] if existing else 0.0) + edge.weight,
            )
    return graph, selected, truncated


def _communities(graph: nx.Graph) -> list[list[str]]:
    if graph.number_of_edges() == 0:
        return [[node_id] for node_id in sorted(graph.nodes)]
    detected = nx.community.louvain_communities(
        graph, weight='weight', resolution=1, seed=42,
    )
    split: list[list[str]] = []
    for community in detected:
        subgraph = graph.subgraph(community)
        split.extend(sorted(component) for component in nx.connected_components(subgraph))
    return sorted(split, key=lambda members: (len(members), members), reverse=True)


def group_oversized_clusters(
    store: GroupingStore,
    as_of: datetime,
    limits: GroupingLimits,
    build_summary: SummaryBuilder,
) -> GroupingResult:
    if limits.grouping_threshold < 1 or limits.max_snapshot_nodes < 1:
        raise ValueError('Grouping limits must be positive')

    snapshot_id, all_nodes, edges = store.graph_snapshot()
    graph, selected, truncated = _cluster_projection(all_nodes, edges, limits)
    communities = _communities(graph)
    by_id = {node.id: node for node in selected}
    eligible = [members for members in communities if len(members) > limits.grouping_threshold]
    eligible.sort(key=lambda members: (-len(members), members))
    before = store.context_token_count([node.id for node in selected])
    if not eligible:
        return GroupingResult(
            snapshot_id, communities, [], [], None, before, before, truncated,
        )

    member_ids = eligible[0]
    members = [by_id[node_id] for node_id in member_ids]
    summary_id = f'summary-{_fingerprint(member_ids)}'
    summary = MemoryNode(
        id=summary_id,
        kind='summary',
        text=build_summary(members),
        scope_key=members[0].scope_key,
        source_ids=sorted({source_id for node in members for source_id in node.source_ids}),
        first_seen_at=min(node.first_seen_at for node in members),
        last_seen_at=max(node.last_seen_at for node in members),
    )
    store.insert_summary(summary)
    for member_id in member_ids:
        edge_id = f'member-{summary_id}-{member_id}'
        store.insert_member_edge(MemoryEdge(
            id=edge_id,
            source_id=member_id,
            target_id=summary_id,
            relation='member_of',
            weight=1.0,
            source_ids=by_id[member_id].source_ids.copy(),
        ))
    store.assign_group(member_ids, summary_id)
    after_ids = [node.id for node in selected if node.id not in set(member_ids)] + [summary_id]
    after = store.context_token_count(after_ids)
    return GroupingResult(
        snapshot_id=snapshot_id,
        communities=communities,
        eligible_sizes=[len(group) for group in eligible],
        selected_member_ids=member_ids,
        summary_id=summary_id,
        context_tokens_before=before,
        context_tokens_after=after,
        truncated=truncated,
    )
