"""`GET /eval/results`: the latest `scripts/eval.py` output, or 404 if it has not run."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException

from api import deps

router = APIRouter(tags=["eval"])


@router.get("/eval/results")
def results() -> dict[str, Any]:
    path = deps.get_settings().eval_results_path
    if not path.is_file():
        raise HTTPException(status_code=404, detail="eval has not run; see scripts/eval.py")
    try:
        loaded = json.loads(path.read_text("utf-8"))
    except ValueError as e:
        raise HTTPException(status_code=500, detail="eval/latest.json is not valid JSON") from e
    if not isinstance(loaded, dict):
        raise HTTPException(status_code=500, detail="eval/latest.json is not an object")
    return loaded
