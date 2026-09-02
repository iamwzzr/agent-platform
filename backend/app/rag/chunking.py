def split_text(
    text: str,
    *,
    chunk_size_words: int = 120,
    overlap_words: int = 20,
) -> list[str]:
    if chunk_size_words <= 0:
        raise ValueError("chunk_size_words must be greater than 0")

    if overlap_words < 0:
        raise ValueError("overlap_words must be greater than or equal to 0")

    if overlap_words >= chunk_size_words:
        raise ValueError("overlap_words must be smaller than chunk_size_words")

    words = text.split()
    chunks: list[str] = []
    start = 0

    while start < len(words):
        end = min(start + chunk_size_words, len(words))
        chunks.append(" ".join(words[start:end]))

        if end == len(words):
            break

        start = end - overlap_words

    return chunks
