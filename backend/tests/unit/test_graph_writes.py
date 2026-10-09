"""Neo4j writes: regulation graph builder and IFC graph (queries recorded, no database)."""

import pytest

from src.knowledge_graph import graph_builder, ifc_to_graph

STANDARD = {
    "standard_code": "QCVN 99:2024/BXD", "standard_name": "Quy chuẩn thử nghiệm", "year": 2024,
    "status": "expired", "eff_status": "Hết hiệu lực toàn bộ", "expired": True, "doc_num": "01/2024/TT-BXD",
    "supersedes": "QCVN 99:2015/BXD", "related_standards": ["QCVN 06:2022/BXD", "QCVN 99:2024/BXD"],
    "chapters": [{"number": "1", "kind": "chapter", "title": "CHUNG", "sections": [
        {"number": "1.1", "title": "Phạm vi", "articles": [
            {"number": "1.1.1", "title": "a", "content": "1.1.1 a", "requirements": [
                {"type": "minimum_value", "description": "Điều 1.1.1: x", "min_value": 3.0, "unit": "m"}]},
            {"number": "1.1.2", "title": "b", "content": "1.1.2 b", "requirements": []}]}]}],
}


@pytest.fixture
def writes(monkeypatch):
    calls = []
    monkeypatch.setattr(graph_builder, "run_write_query", lambda q, p=None: calls.append((" ".join(q.split()), p or {})))
    return calls


class TestRegulationGraph:
    def test_standard_node_carries_validity(self, writes):
        graph_builder.build_graph_from_dict(STANDARD)
        query, params = writes[0]
        assert query.startswith("MERGE (s:Standard {code: $code})")
        assert params["status"] == "expired" and params["expired"] is True
        assert params["eff_status"] == "Hết hiệu lực toàn bộ" and params["doc_num"] == "01/2024/TT-BXD"

    def test_old_content_deleted_before_rebuild(self, writes):
        graph_builder.build_graph_from_dict(STANDARD)
        assert "DETACH DELETE" in writes[1][0] and writes[1][1] == {"code": "QCVN 99:2024/BXD"}

    def test_batched_writes(self, writes):
        graph_builder.build_graph_from_dict(STANDARD)
        article_writes = [p for q, p in writes if "MERGE (a:Article" in q]
        assert len(article_writes) == 1  # one UNWIND for both articles
        ids = [row["article_id"] for row in article_writes[0]["rows"]]
        assert ids == ["QCVN 99:2024/BXD_art1.1.1", "QCVN 99:2024/BXD_art1.1.2"]
        req_rows = next(p for q, p in writes if "MERGE (r:Requirement" in q)["rows"]
        assert req_rows[0]["min_value"] == 3.0 and req_rows[0]["unit"] == "m" and "req" not in req_rows[0]

    def test_references_exclude_self(self, writes):
        graph_builder.build_graph_from_dict(STANDARD)
        related = next(p for q, p in writes if "RELATED_TO" in q)
        assert related["related"] == ["QCVN 06:2022/BXD"]
        assert any("SUPERSEDES" in q and p["supersedes"] == "QCVN 99:2015/BXD" for q, p in writes)


class FakeSession:
    def __init__(self, log):
        self.log = log

    def run(self, query, *args, **params):
        self.log.append((" ".join(query.split()), params))
        if query.startswith("SHOW CONSTRAINTS"):
            return [{"name": "constraint_old_storey"}]
        return []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeDriver:
    def __init__(self, log):
        self.log = log

    def session(self, **kw):
        return FakeSession(self.log)

    def close(self):
        pass


@pytest.fixture
def neo4j_log(monkeypatch):
    log = []
    monkeypatch.setattr(ifc_to_graph.GraphDatabase, "driver", lambda *a, **k: FakeDriver(log))
    return log


def ifc(building):
    return {
        "building_name": building, "project_name": "P", "storeys": [{"name": "Tầng 1", "elevation": 0}],
        "materials": [], "spaces": [{"global_id": f"{building}-sp", "name": "P1", "storey": "Tầng 1"}],
        "elements": [{"global_id": f"{building}-w1", "ifc_type": "IfcWall", "name": "W", "storey": "Tầng 1"}],
    }


class TestIfcStoreys:
    def test_storeys_scoped_by_building(self, neo4j_log):
        """Regression: UNIQUE(Storey.name) merged "Tầng 1" of every building into one node."""
        ifc_to_graph.build_ifc_graph(ifc("Nhà A"))
        ifc_to_graph.build_ifc_graph(ifc("Nhà B"))
        storey_ids = [p["storey_id"] for q, p in neo4j_log if q.startswith("MERGE (s:Storey")]
        assert storey_ids == ["Nhà A::Tầng 1", "Nhà B::Tầng 1"]
        links = [p["storey_id"] for q, p in neo4j_log if "MATCH (s:Storey {storey_id: $storey_id})" in q]
        assert set(links) == {"Nhà A::Tầng 1", "Nhà B::Tầng 1"}

    def test_old_name_constraint_dropped(self, neo4j_log):
        ifc_to_graph.build_ifc_graph(ifc("Nhà A"))
        queries = [q for q, _ in neo4j_log]
        assert "DROP CONSTRAINT `constraint_old_storey` IF EXISTS" in queries
        assert any("REQUIRE s.storey_id IS UNIQUE" in q for q in queries)
        assert not any("REQUIRE s.name IS UNIQUE" in q and "Storey" in q for q in queries)
