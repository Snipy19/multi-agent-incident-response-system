"""
BUILD VECTOR INDEX (Multi-Dataset Version)
---------------------------------------------
Kaam: data/ folder mein jitni bhi *_2k.log_structured.csv files hain,
sabko automatically dhoondh ke unke unique EventTemplates ko combine
karna, embeddings banana, aur FAISS index mein save karna.

Isse hamara knowledge base diverse ho jaata hai - HDFS, Apache, Hadoop,
Linux, OpenStack, BGL, Thunderbird jaise alag alag real-world systems
ke error patterns cover ho jaate hain.

Future mein naya dataset add karna ho, bas CSV file data/ folder mein
daal do aur ye script dobara chala do - code change nahi karna padega.
"""

import glob
import os
import pandas as pd
import faiss
import numpy as np
import pickle
from sentence_transformers import SentenceTransformer

print("[BUILD INDEX] data/ folder mein saari *_2k.log_structured.csv files dhoondh rahe hain...")

csv_files = glob.glob("data/*_2k.log_structured.csv")
print(f"[BUILD INDEX] {len(csv_files)} dataset files mile: {[os.path.basename(f) for f in csv_files]}")

all_templates = []

for csv_path in csv_files:
    # Dataset ka naam file se nikaalte hain, jaise "Apache_2k.log_structured.csv" -> "Apache"
    dataset_name = os.path.basename(csv_path).split("_2k")[0]

    df = pd.read_csv(csv_path)

    if "EventTemplate" not in df.columns:
        print(f"[BUILD INDEX] SKIP: {dataset_name} mein EventTemplate column nahi hai")
        continue

    # Duplicate templates hata do, sirf unique patterns chahiye
    unique = df.drop_duplicates(subset=["EventTemplate"]).copy()

    # Kuch datasets mein 'Level' ya 'Component' column nahi hoti - agar
    # nahi hai toh "Unknown" daal dete hain, taaki code crash na ho
    unique["Level"] = unique["Level"] if "Level" in unique.columns else "Unknown"
    unique["Component"] = unique["Component"] if "Component" in unique.columns else "Unknown"
    unique["Dataset"] = dataset_name  # batata hai ye pattern kis system se aaya

    subset = unique[["EventTemplate", "Level", "Component", "Dataset"]]
    all_templates.append(subset)

    print(f"[BUILD INDEX] {dataset_name}: {len(df)} log lines -> {len(subset)} unique patterns")

# Sabko ek combined DataFrame mein jodo
combined = pd.concat(all_templates, ignore_index=True)
combined = combined.drop_duplicates(subset=["EventTemplate"]).reset_index(drop=True)

print(f"\n[BUILD INDEX] TOTAL unique patterns across all datasets: {len(combined)}")

# Embedding model load karo
print("[BUILD INDEX] Embedding model load kar rahe hain...")
model = SentenceTransformer("all-MiniLM-L6-v2")

texts_to_embed = combined["EventTemplate"].tolist()
print(f"[BUILD INDEX] {len(texts_to_embed)} templates ko embed kar rahe hain...")
embeddings = model.encode(texts_to_embed, show_progress_bar=True)

# FAISS index banao
dimension = embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(np.array(embeddings).astype("float32"))

# Save karo
faiss.write_index(index, "vectorstore/hdfs_index.faiss")

with open("vectorstore/hdfs_metadata.pkl", "wb") as f:
    pickle.dump(combined, f)

print(f"[BUILD INDEX] Done! {len(combined)} patterns, {len(csv_files)} datasets se, index mein save ho gaye.")