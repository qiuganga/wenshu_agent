from app.agent.ranking.relationship_graph import TableRelationship, TableRelationshipGraph


def test_relationship_graph_distances_cycles_and_disconnected() -> None:
    graph = TableRelationshipGraph(
        [
            TableRelationship("orders", "items"),
            TableRelationship("items", "products"),
            TableRelationship("products", "orders"),
        ],
        max_depth=4,
    )

    assert graph.distance("orders", "orders") == 0
    assert graph.distance("orders", "items") == 1
    assert graph.distance("orders", "products") == 1
    assert graph.distance("orders", "regions") is None
    assert graph.connected(["orders", "items", "products"]) is True


def test_relationship_graph_ignores_unconfirmed_hints() -> None:
    graph = TableRelationshipGraph([TableRelationship("a", "b", confirmed=False)])

    assert graph.distance("a", "b") is None
