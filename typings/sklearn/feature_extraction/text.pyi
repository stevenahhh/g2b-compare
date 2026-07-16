from collections.abc import Callable, Iterable, Sequence
from typing import Literal

import numpy as np
from scipy.sparse import csr_matrix

type Document = str | Sequence[str]

class TfidfVectorizer:
    idf_: np.ndarray[tuple[int], np.dtype[np.float64]]
    def __init__(
        self,
        *,
        analyzer: Literal["word", "char_wb"],
        tokenizer: (
            Callable[[list[str] | tuple[str, ...]], tuple[str, ...]] | None
        ) = ...,
        preprocessor: None = ...,
        token_pattern: str | None = ...,
        ngram_range: tuple[int, int] = ...,
        lowercase: bool = ...,
        norm: Literal["l2"] = ...,
        use_idf: bool = ...,
        smooth_idf: bool = ...,
        sublinear_tf: bool = ...,
        binary: bool = ...,
        dtype: type[np.float64] = ...,
        vocabulary: dict[str, int] | None = ...,
    ) -> None: ...
    def build_analyzer(self) -> Callable[[Document], list[str]]: ...
    def fit_transform(self, raw_documents: Iterable[Document]) -> csr_matrix: ...
    def transform(self, raw_documents: Iterable[Document]) -> csr_matrix: ...
