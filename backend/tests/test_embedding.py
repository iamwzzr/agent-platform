import pytest

from app.rag.embedding import cosine_similarity, embed_text


def test_embed_text_normalizes_case_and_punctuation() -> None:
    first = embed_text("Python, FASTAPI! Python.")
    second = embed_text("python fastapi python")

    assert first == {
        "python": 2.0,
        "fastapi": 1.0,
    }
    assert second == first


def test_cosine_similarity_compares_vector_direction() -> None:
    query = embed_text("python fastapi")
    same_direction = embed_text("python python fastapi fastapi")
    unrelated = embed_text("java database")

    assert cosine_similarity(
        query,
        same_direction,
    ) == pytest.approx(1.0)
    assert cosine_similarity(query, unrelated) == 0.0


@pytest.mark.parametrize(
    ("left_text", "right_text"),
    [
        ("", "python"),
        ("", ""),
    ],
)
def test_cosine_similarity_handles_empty_text(
    left_text: str,
    right_text: str,
) -> None:
    assert (
        cosine_similarity(
            embed_text(left_text),
            embed_text(right_text),
        )
        == 0.0
    )

def test_cosine_similarity_clamps_floating_point_rounding() -> None:
    vector = {
        "a": 1.0,
        "b": 5.0,
    }

    similarity = cosine_similarity(vector, vector)

    assert similarity == 1.0