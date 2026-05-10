from __future__ import annotations

from typing import Protocol

from rust_sensei.domain.learner import LearnerProfile


class LearnerRepository(Protocol):
    def get_active_profile(self) -> LearnerProfile | None:
        ...

    def get_profile(self, learner_id: str) -> LearnerProfile | None:
        ...

    def save_profile(self, profile: LearnerProfile) -> None:
        ...

    def create_profile_if_absent(self, profile: LearnerProfile) -> LearnerProfile:
        ...
