import math
import re
from collections.abc import Mapping

Embedding = dict[str, float]

_TOKEN_PATTERN = re.compile(r"\w+")


def embed_text(text: str) -> Embedding:
    embedding: Embedding = {}

    for token in _TOKEN_PATTERN.findall(text.casefold()):
        embedding[token] = embedding.get(token, 0.0) + 1.0

    return embedding


def cosine_similarity(
    left: Mapping[str, float],
    right: Mapping[str, float],
) -> float:
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))

    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0

    dot_product = sum(value * right.get(token, 0.0) for token, value in left.items())
    similarity = dot_product / (
        left_norm * right_norm
        )
    return max(
        -1.0,
        min(1.0, similarity),
        )
