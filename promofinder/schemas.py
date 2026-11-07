from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class EpisodeJudgment(StrictModel):
    candidate_id: str
    hook_score: int = Field(ge=1, le=10)
    cliffhanger_score: int = Field(ge=1, le=10)
    standalone_score: int = Field(ge=1, le=10)
    hook_line: str
    hook_time: str
    cliffhanger_line: str
    hook_type: str
    why: str
    weakness: str


class EpisodeJudgments(StrictModel):
    judgments: list[EpisodeJudgment]


class ColdViewer(StrictModel):
    people: list[str]
    conflict: str
    confusing: list[str]
    keep_watching: bool
    expect_next: str


class Reveal(StrictModel):
    episode: int = Field(ge=1)
    reveal: str


class Bible(StrictModel):
    premise: str
    characters: dict[str, list[str]]
    relationships: list[str]
    reveals: list[Reveal]


class PromoOrder(StrictModel):
    promo_id: str
    reason: str


class ProposedSegment(StrictModel):
    episode: int = Field(ge=1)
    start: float = Field(ge=0)
    end: float = Field(gt=0)


class StitchedProposal(StrictModel):
    segments: list[ProposedSegment]
    hook_line: str
    cliffhanger_line: str
    hook_type: str
    why: str


class GlobalOrder(StrictModel):
    order: list[PromoOrder]
    stitched: list[StitchedProposal]
