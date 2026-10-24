import json
from pathlib import Path

from vectorstore import retriever


def test_runtime_metadata_is_data_only_json():
    import faiss

    metadata_path = Path("vectorstore/hdfs_metadata.json")
    records = json.loads(metadata_path.read_text(encoding="utf-8"))
    index = faiss.read_index("vectorstore/hdfs_index.faiss")

    assert records
    assert index.ntotal == len(records)
    assert all("EventTemplate" in record for record in records)
    assert not Path("vectorstore/hdfs_metadata.pkl").exists()


def test_retriever_reuses_normalized_query_and_returns_independent_results(monkeypatch):
    calls = []

    def fake_retrieve(query, top_k):
        calls.append((query, top_k))
        return ({"template": "database timeout", "distance": 0.1},)

    monkeypatch.setattr(retriever, "_retrieve_uncached", fake_retrieve)
    retriever.clear_retrieval_cache()

    first = retriever.retrieve_similar_patterns("  database   timeout\n", top_k=3)
    first[0]["template"] = "caller mutation"
    second = retriever.retrieve_similar_patterns("database timeout", top_k=3)

    assert calls == [("database timeout", 3)]
    assert second == [{"template": "database timeout", "distance": 0.1}]


def test_retriever_rejects_invalid_top_k():
    for invalid in (0, -1, True):
        try:
            retriever.retrieve_similar_patterns("database timeout", top_k=invalid)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid top_k should raise ValueError")


def test_retriever_maps_json_records_to_faiss_results(monkeypatch):
    class FakeModel:
        def encode(self, values):
            return [[0.0, 1.0] for _ in values]

    class FakeIndex:
        def search(self, _query, _top_k):
            return [[0.25]], [[0]]

    monkeypatch.setattr(retriever, "_ensure_resources", lambda: None)
    monkeypatch.setattr(retriever, "_model", FakeModel())
    monkeypatch.setattr(retriever, "_index", FakeIndex())
    monkeypatch.setattr(
        retriever,
        "_metadata",
        [{
            "EventTemplate": "database timeout",
            "SampleContent": "connection timed out",
            "ExampleCount": 4,
            "Label": "E1",
            "Level": "ERROR",
            "Component": "database",
            "Dataset": "synthetic-test-fixture",
        }],
    )

    result = retriever._retrieve_uncached("database timeout", 1)
    assert result[0]["template"] == "database timeout"
    assert result[0]["example_count"] == 4
    assert result[0]["distance"] == 0.25
