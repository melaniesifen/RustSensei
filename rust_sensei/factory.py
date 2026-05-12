from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from rust_sensei.logging_config import configure_logging
from rust_sensei.repositories.json_repository import JsonRepositoryFactory, default_state_dir
from rust_sensei.services.assessment_service import AssessmentService
from rust_sensei.services.environment import EnvironmentProbe
from rust_sensei.services.lesson_service import LessonService
from rust_sensei.services.session_service import SessionService
from rust_sensei.services.setup_service import SetupService


class ServiceFactory:
    def __init__(
        self,
        state_dir: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._state_dir = state_dir or default_state_dir()
        self._now = now or self._utc_now
        configure_logging(self._state_dir)
        self._repositories = JsonRepositoryFactory(self._state_dir)

    def session_service(self) -> SessionService:
        return SessionService(
            learner_repository=self._repositories.learner_repository(),
            now=self._now,
        )

    def lesson_service(self) -> LessonService:
        return LessonService(
            learner_repository=self._repositories.learner_repository(),
            assignment_repository=self._repositories.assignment_repository(),
            attempt_repository=self._repositories.attempt_repository(),
            curriculum_repository=self._repositories.curriculum_repository(),
            now=self._now,
        )

    def setup_service(self) -> SetupService:
        return SetupService(EnvironmentProbe(self._state_dir))

    def assessment_service(self) -> AssessmentService:
        return AssessmentService(
            assignment_repository=self._repositories.assignment_repository(),
            attempt_repository=self._repositories.attempt_repository(),
            assessment_repository=self._repositories.assessment_repository(),
            curriculum_repository=self._repositories.curriculum_repository(),
            learner_repository=self._repositories.learner_repository(),
            now=self._now,
        )

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)
