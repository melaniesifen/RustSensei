from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from rust_sensei.domain.enums import RustLevel


class StrictDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
