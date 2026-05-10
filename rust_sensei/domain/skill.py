from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillScore:
    score: float
    confidence: float
    evidence: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkillModel:
    rust_concepts: dict[str, SkillScore] = field(default_factory=dict)
    programming_dimensions: dict[str, SkillScore] = field(default_factory=dict)
