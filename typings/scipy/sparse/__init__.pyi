from typing import Self

import numpy as np

class csr_matrix:  # noqa: N801
    shape: tuple[int, int]
    indptr: np.ndarray[tuple[int], np.dtype[np.int64]]
    indices: np.ndarray[tuple[int], np.dtype[np.int32]]
    data: np.ndarray[tuple[int], np.dtype[np.float64]]
    def __init__(
        self,
        arg1: csr_matrix
        | tuple[
            np.ndarray[tuple[int], np.dtype[np.float64]],
            np.ndarray[tuple[int], np.dtype[np.int32]],
            np.ndarray[tuple[int], np.dtype[np.int64]],
        ],
        shape: tuple[int, int] | None = ...,
        dtype: type[np.float64] | None = ...,
    ) -> None: ...
    @property
    def T(self) -> Self: ...  # noqa: N802
    def sum_duplicates(self) -> None: ...
    def eliminate_zeros(self) -> None: ...
    def sort_indices(self) -> None: ...
    def toarray(self) -> np.ndarray[tuple[int, int], np.dtype[np.float64]]: ...
    def __matmul__(self, other: csr_matrix) -> csr_matrix: ...
