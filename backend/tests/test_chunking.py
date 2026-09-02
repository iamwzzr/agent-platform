import pytest

from app.rag.chunking import split_text


def test_split_text_creates_overlapping_chunks() -> None:
    chunks = split_text(
        "one two three four five six seven",
        chunk_size_words=4,
        overlap_words=1,
    )

    assert chunks == [
        "one two three four",
        "four five six seven",
    ]


def test_split_text_returns_no_chunks_for_blank_text() -> None:
    chunks = split_text(
        " \n\t ",
        chunk_size_words=4,
        overlap_words=1,
    )

    assert chunks == []


def test_split_text_avoids_overlap_only_tail() -> None:
    chunks = split_text(
        "one two three four five",
        chunk_size_words=4,
        overlap_words=2,
    )

    assert chunks == [
        "one two three four",
        "three four five",
    ]


@pytest.mark.parametrize(
    ("chunk_size_words", "overlap_words"),
    [
        (0, 0),
        (4, -1),
        (4, 4),
        (4, 5),
    ],
)
def test_split_text_rejects_invalid_window(
    chunk_size_words: int,
    overlap_words: int,
) -> None:
    with pytest.raises(ValueError):
        split_text(
            "one two three",
            chunk_size_words=chunk_size_words,
            overlap_words=overlap_words,
        )
