from pydantic import BaseModel, Field


class FailureRecord(BaseModel):
    symptom: str
    conditions: list[str]=Field(default_factory=list)
    root_cause: str|None=None
    fix: str|None=None
    verification: str|None=None
    remaining_limits: list[str]=Field(default_factory=list)
