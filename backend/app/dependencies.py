from typing import Annotated

from fastapi import Depends, Query


def pagination_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, int]:
    return {"page": page, "page_size": page_size}


PaginationParams = Annotated[dict[str, int], Depends(pagination_params)]
