"""
RETRIEVER
-----------
Kaam: Naya log aane par, saved FAISS index (multi-dataset knowledge base)
mein se sabse SIMILAR purane real-world patterns dhoondhna (top-k).

Ye function Investigator agents ke andar call hota hai - jitne bhi
Investigators dynamically spawn hon (1 ho, 5 ho, 100 ho), har ek apna
alag RAG search independently karta hai apne angle ke context mein.
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
    'dataset', 'distance' (kam distance = zyada similar)
    """
    query_embedding = _model.encode([query_log])

    distances, indices = _index.search(np.array(query_embedding).astype("float32"), top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        row = _metadata.iloc[idx]
        results.append({
            "template": row["EventTemplate"],
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