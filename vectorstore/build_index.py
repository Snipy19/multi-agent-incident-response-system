"""
BUILD VECTOR INDEX (Multi-Dataset Version)
---------------------------------------------
Purpose: discover all *_2k.log_structured.csv files, combine their unique
event patterns, generate embeddings, and save a FAISS index.

This creates a diverse knowledge base covering real-world systems including
HDFS, Apache, Hadoop, Linux, OpenStack, BGL, and Thunderbird.

To add a dataset, place its CSV file in data/ and run this script again;
no application code changes are required.
"""

import glob
import os
import pandas as pd
import faiss
import numpy as np
import pickle
from sentence_transformers import SentenceTransformer

print("[BUILD INDEX] Discovering *_2k.log_structured.csv files in data/...")

csv_files = glob.glob("data/*_2k.log_structured.csv")
print(f"[BUILD INDEX] {len(csv_files)} dataset files mile: {[os.path.basename(f) for f in csv_files]}")

all_templates = []

for csv_path in csv_files:
    # Extract the dataset name from the filename.
    dataset_name = os.path.basename(csv_path).split("_2k")[0]

    df = pd.read_csv(csv_path)

    if "EventTemplate" not in df.columns:
        print(f"[BUILD INDEX] SKIP: {dataset_name} has no EventTemplate column")
        continue

    # Keep one vector per pattern while preserving occurrence evidence.
    # Keep one vector per pattern to avoid overweighting repeated log lines,
    # but retain useful evidence from all rows that share that pattern.
    grouped = df.groupby("EventTemplate", dropna=False)
    unique = grouped.first().reset_index()
    unique["ExampleCount"] = grouped.size().reindex(unique["EventTemplate"]).to_numpy()

    # Some datasets omit Level or Component; use Unknown when unavailable.
    unique["Level"] = unique["Level"] if "Level" in unique.columns else "Unknown"
    unique["Component"] = unique["Component"] if "Component" in unique.columns else "Unknown"
    unique["SampleContent"] = unique["Content"] if "Content" in unique.columns else unique["EventTemplate"]
    unique["Label"] = unique["Label"] if "Label" in unique.columns else "Unknown"
    unique["Dataset"] = dataset_name  # Source system for this pattern.

    # The embedding includes dataset/component/severity context, while the
    # original fields remain available to the retriever and agent prompts.
    unique["EmbeddingText"] = unique.apply(
        lambda row: (
            f"dataset={row['Dataset']} level={row['Level']} component={row['Component']} "
            f"label={row['Label']} pattern={row['EventTemplate']} "
            f"example={str(row['SampleContent'])[:500]}"
        ),
        axis=1,
    )
    subset = unique[[
        "EventTemplate", "EmbeddingText", "SampleContent", "ExampleCount",
        "Level", "Component", "Label", "Dataset"
    ]]
    all_templates.append(subset)

    print(f"[BUILD INDEX] {dataset_name}: {len(df)} log lines -> {len(subset)} unique patterns")

# Combine all dataset frames.
combined = pd.concat(all_templates, ignore_index=True)

# A template can legitimately occur in more than one dataset. Keep one vector
# for retrieval efficiency, but aggregate its evidence instead of discarding
# the duplicate dataset occurrence.
combined = (
    combined.groupby("EventTemplate", as_index=False)
    .agg({
        "EmbeddingText": "first",
        "SampleContent": "first",
        "ExampleCount": "sum",
        "Level": "first",
        "Component": "first",
        "Label": "first",
        "Dataset": lambda values: ", ".join(sorted(set(values))),
    })
)

combined["EmbeddingText"] = combined.apply(
    lambda row: (
        f"datasets={row['Dataset']} level={row['Level']} component={row['Component']} "
        f"label={row['Label']} occurrences={row['ExampleCount']} "
        f"pattern={row['EventTemplate']} example={str(row['SampleContent'])[:500]}"
    ),
    axis=1,
)

print(f"\n[BUILD INDEX] TOTAL unique patterns across all datasets: {len(combined)}")

# Embedding model load karo
print("[BUILD INDEX] Loading the embedding model...")
model = SentenceTransformer("all-MiniLM-L6-v2")

texts_to_embed = combined["EmbeddingText"].tolist()
print(f"[BUILD INDEX] Embedding {len(texts_to_embed)} templates...")
embeddings = model.encode(texts_to_embed, show_progress_bar=True)

# FAISS index banao
dimension = embeddings.shape[1]
index = faiss.IndexFlatL2(dimension)
index.add(np.array(embeddings).astype("float32"))

# Save karo
faiss.write_index(index, "vectorstore/hdfs_index.faiss")

with open("vectorstore/hdfs_metadata.pkl", "wb") as f:
    pickle.dump(combined, f)

print(f"[BUILD INDEX] Done! Saved {len(combined)} patterns from {len(csv_files)} datasets.")
