import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')

def embed_texts(texts):
    if not texts:
        return []
    embeddings = model.encode(texts).tolist()
    return embeddings
