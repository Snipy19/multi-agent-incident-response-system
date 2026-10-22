"""
RETRIEVER
-----------
Purpose: retrieve the most similar historical patterns from the saved
multi-dataset FAISS knowledge base.

The investigator calls this function independently for each investigation
angle, regardless of whether one or many investigators are spawned.
"""

import faiss
import pickle
import numpy as np
from functools import lru_cache
from threading import Lock
from sentence_transformers import SentenceTransformer

# Resources are loaded on the first real retrieval, not while importing the
# application. This keeps API startup and test discovery fast. The lock avoids
# duplicate model/index loads when parallel investigators start together.
_model = None
_index = None
_metadata = None
_resource_lock = Lock()


def _ensure_resources() -> None:
    global _model, _index, _metadata
    if _model is not None and _index is not None and _metadata is not None:
        return

    with _resource_lock:
        if _model is not None and _index is not None and _metadata is not None:
            return
        print("[RETRIEVER] Loading the index and embedding model...")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _index = faiss.read_index("vectorstore/hdfs_index.faiss")
        with open("vectorstore/hdfs_metadata.pkl", "rb") as f:
            _metadata = pickle.load(f)
        print(f"[RETRIEVER] Ready - {_index.ntotal} patterns loaded")


def _retrieve_uncached(query_log: str, top_k: int) -> tuple[dict, ...]:
    """Run the actual embedding and FAISS search once for a cache miss."""
    _ensure_resources()
    # Encode the incoming query with the same model used during index build.
    query_embedding = _model.encode([query_log])

    distances, indices = _index.search(np.array(query_embedding).astype("float32"), top_k)

    # FAISS returns row positions; metadata must remain aligned with the index.
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        row = _metadata.iloc[idx]
        results.append({
            "template": row["EventTemplate"],
            "sample_content": row.get("SampleContent", row["EventTemplate"]),
            "example_count": int(row.get("ExampleCount", 1)),
            "label": row.get("Label", "Unknown"),
            "level": row["Level"],
            "component": row["Component"],
            "dataset": row["Dataset"],
            "distance": float(dist)
        })

    # The cached value is immutable at the outer level. The public function
    # returns fresh dictionaries so callers cannot mutate shared cache state.
    return tuple(results)


def _normalize_query(query_log: str) -> str:
    """Collapse irrelevant whitespace so equivalent log prompts share a key."""
    return " ".join(str(query_log).split())


@lru_cache(maxsize=128)
def _retrieve_cached(normalized_query: str, top_k: int) -> tuple[dict, ...]:
    """Bound repeated investigator/aggregator lookups without changing results."""
    return _retrieve_uncached(normalized_query, top_k)


def clear_retrieval_cache() -> None:
    """Clear cached RAG lookups after rebuilding or replacing the index."""
    _retrieve_cached.cache_clear()


def retrieve_similar_patterns(query_log: str, top_k: int = 3) -> list[dict]:
    """
    query_log: incoming log to search
    top_k: number of similar patterns to return

    Return dictionaries containing template, context metadata, and distance.
    """
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    normalized_query = _normalize_query(query_log)
    return [dict(result) for result in _retrieve_cached(normalized_query, top_k)]


# Quick standalone test - agar ye file directly chalayi jaaye
if __name__ == "__main__":
    test_log = "ERROR: Database connection timeout after 30s at checkout-service"
    print(f"\nTest query: {test_log}\n")

    results = retrieve_similar_patterns(test_log, top_k=3)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['dataset']}/{r['level']}] {r['component']}: {r['template']} (distance: {r['distance']:.2f})")
