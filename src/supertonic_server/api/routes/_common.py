"""Helpers shared by route modules."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from supertonic_server.api.deps import AppState, get_state

State = Annotated[AppState, Depends(get_state)]
