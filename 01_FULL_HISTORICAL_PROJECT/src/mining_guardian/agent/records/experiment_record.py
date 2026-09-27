from pydantic import BaseModel, Field


class ExperimentRecord(BaseModel):
    hypothesis: str
    baseline: str
    change: str
    controlled_variables: list[str]=Field(default_factory=list)
    metrics: list[str]=Field(default_factory=list)
    acceptance_criteria: list[str]=Field(default_factory=list)
    result: str|None=None
    decision: str|None=None
