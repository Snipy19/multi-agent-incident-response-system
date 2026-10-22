from vectorstore import retriever


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
