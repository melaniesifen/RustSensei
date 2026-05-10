from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

import fcntl

from rust_sensei.constants import ACTIVE_LEARNER_ID, SCHEMA_VERSION, STATE_LOCK_FILE_NAME
from rust_sensei.errors import storage_error

T = TypeVar("T")
StateMutation = Callable[[dict[str, Any]], None]


class JsonStateStore:
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock_path = state_path.with_name(STATE_LOCK_FILE_NAME)

    @property
    def state_path(self) -> Path:
        return self._state_path

    def read(self) -> dict[str, Any]:
        with self._locked():
            return self._load_state()

    def update(self, mutation: StateMutation) -> dict[str, Any]:
        def transaction(state: dict[str, Any]) -> tuple[dict[str, Any], bool]:
            mutation(state)
            return state, True

        return self.transact(transaction)

    def transact(self, transaction: Callable[[dict[str, Any]], tuple[T, bool]]) -> T:
        with self._locked():
            state = self._load_state()
            result, changed = transaction(state)
            if changed:
                state["state_revision"] += 1
                self._write_state(state)
            return result

    @contextmanager
    def _locked(self):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            state = self._empty_state()
            self._write_state(state)
            return state

        try:
            with self._state_path.open("r", encoding="utf-8") as state_file:
                state = json.load(state_file)
        except json.JSONDecodeError as exc:
            raise storage_error(
                "JSON state file is invalid",
                retryable=False,
                path=str(self._state_path),
            ) from exc

        schema_version = state.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise storage_error(
                "Unsupported JSON state schema version",
                retryable=False,
                schema_version=schema_version,
                supported_schema_version=SCHEMA_VERSION,
            )

        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            dir=self._state_path.parent,
            prefix=f".{self._state_path.name}.",
            suffix=".tmp",
            text=True,
        )
        temp_file_path = Path(temp_path)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(state, temp_file, indent=2, sort_keys=True)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_file_path, self._state_path)
        except OSError as exc:
            raise storage_error(
                "Failed to write JSON state file",
                path=str(self._state_path),
            ) from exc
        finally:
            temp_file_path.unlink(missing_ok=True)

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "state_revision": 1,
            "active_learner_id": ACTIVE_LEARNER_ID,
            "learners": {},
            "lesson_assignments": [],
            "attempts": [],
            "assessments": [],
            "progress_events": [],
            "signals": [],
        }
