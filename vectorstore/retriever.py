"""
RETRIEVER
-----------
Kaam: Naya log aane par, saved FAISS index mein se sabse SIMILAR
purane patterns dhoondhna (top-k).

Ye "search karo purane incidents mein" wala function hai jo
baad mein Investigator/Aggregator prompts mein context ke tarah use hoga.
"""

import faiss
import pickle
import numpy as np
from sentence_transformers import SentenceTransformer

# Model aur index sirf EK BAAR load karte hain (module load hote waqt),
# taaki baar baar disk se na padhna pade - performance ke liye important
print("[RETRIEVER] Index aur model load kar rahe hain...")
_model = SentenceTransformer("all-MiniLM-L6-v2")
_index = faiss.read_index("vectorstore/hdfs_index.faiss")

with open("vectorstore/hdfs_metadata.pkl", "rb") as f:
    _metadata = pickle.load(f)

print(f"[RETRIEVER] Ready - {_index.ntotal} patterns loaded")


def retrieve_similar_patterns(query_log: str, top_k: int = 3) -> list[dict]:
    """
    query_log: naya incoming log jo hum check karna chahte hain
    top_k: kitne sabse similar patterns chahiye

    Return: list of dicts, har ek mein 'template', 'level', 'component',
    'distance' (kam distance = zyada similar)
    """
    # Query ko bhi usi model se embedding mein convert karo
    query_embedding = _model.encode([query_log])

    # FAISS se top_k sabse similar embeddings dhoondo
    distances, indices = _index.search(np.array(query_embedding).astype("float32"), top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        row = _metadata.iloc[idx]
        results.append({
            "template": row["EventTemplate"],
            "level": row["Level"],
            "component": row["Component"],
            "distance": float(dist)
        })

    return results


# Quick standalone test - agar ye file directly chalayi jaaye
if __name__ == "__main__":
    test_log = "ERROR: Database connection timeout after 30s at checkout-service"
    print(f"\nTest query: {test_log}\n")

    results = retrieve_similar_patterns(test_log, top_k=3)
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['level']}] {r['component']}: {r['template']} (distance: {r['distance']:.2f})")