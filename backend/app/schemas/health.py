from typing import Literal

from pydantic import BaseModel


class HealthOut(BaseModel):
    status: Literal["ok"]
    db: Literal["ok", "error"]
