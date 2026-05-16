from __future__ import annotations

from pydantic import Field

from rust_sensei.constants import ACTIVE_LEARNER_ID
from rust_sensei.domain.enums import AssignmentStatus, WorkspaceArtifactPolicy
from rust_sensei.dto.common import StrictDTO


class LessonCommandDTO(StrictDTO):
    command: str
    purpose: str
    risk_level: str
    required: bool = True
    allowed_for_agent_verification: bool = False


class LessonPlanDTO(StrictDTO):
    lesson_id: str
    concept_id: str
    prompt: str
    success_criteria: list[str]
    learner_command: str | None = None
    lesson_commands: list[LessonCommandDTO] = Field(default_factory=list)
    hints: list[str] = Field(default_factory=list)
    rubric_ids: list[str]
    workspace_artifact_policy: WorkspaceArtifactPolicy


class AssignmentWorkspaceSuggestionDTO(StrictDTO):
    assignment_id: str
    workspace_dir: str
    package_root: str | None = None
    lesson_file_path: str | None = None
    report_file_path: str
    open_path: str
    create_cargo_package: bool


class CurriculumConceptDTO(StrictDTO):
    concept_id: str
    title: str
    order: int
    default_difficulty: str
    learner_command: str | None = None
    rubric_ids: list[str]
    variant_ids: list[str]
    branch_target_ids: list[str] = Field(default_factory=list)


class ListCurriculumConceptsResponse(StrictDTO):
    curriculum_version: str
    concepts: list[CurriculumConceptDTO]


class LessonAssignmentDTO(StrictDTO):
    assignment_id: str
    learner_id: str
    lesson_id: str
    concept_id: str
    difficulty: str
    variant_id: str
    status: AssignmentStatus
    selection_rationale: str
    curriculum_version: str


class GetNextLessonRequest(StrictDTO):
    learner_id: str = ACTIVE_LEARNER_ID
    force_new_variant: bool = False
    abandon_active_assignment: bool = False
    abandonment_reason: str | None = None


class GetNextLessonResponse(StrictDTO):
    assignment: LessonAssignmentDTO | None
    lesson_plan: LessonPlanDTO | None
    reused_active_assignment: bool
    pending_assessment: bool = False
    pending_attempt_id: str | None = None
    workspace_suggestion: AssignmentWorkspaceSuggestionDTO | None = None
