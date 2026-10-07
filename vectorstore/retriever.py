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
from sentence_transformers import SentenceTransformer

# Load the model and index once at module import for efficient reuse.
print("[RETRIEVER] Loading the index and embedding model...")
_model = SentenceTransformer("all-MiniLM-L6-v2")
_index = faiss.read_index("vectorstore/hdfs_index.faiss")

with open("vectorstore/hdfs_metadata.pkl", "rb") as f:
    _metadata = pickle.load(f)

print(f"[RETRIEVER] Ready - {_index.ntotal} patterns loaded")


def retrieve_similar_patterns(query_log: str, top_k: int = 3) -> list[dict]:
    """
    query_log: incoming log to search
    top_k: number of similar patterns to return

    Return dictionaries containing template, context metadata, and distance.
    """
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

    return results


# Quick standalone test - agar ye file directly chalayi jaaye
if __name__ == "__main__":
    test_log = "ERROR: Database connection timeout after 30s at checkout-service"
    print(f"\nTest query: {test_log}\n")

    results = retrieve_similar_patterns(test_log, top_k=3)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['dataset']}/{r['level']}] {r['component']}: {r['template']} (distance: {r['distance']:.2f})")
