from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypeVar

import fcntl

from rust_sensei.constants import ACTIVE_LEARNER_ID, SCHEMA_VERSION, STATE_LOCK_FILE_NAME
from rust_sensei.errors import StorageError, storage_error

T = TypeVar("T")
StateMutation = Callable[[dict[str, Any]], None]

_REQUIRED_STATE_FIELDS: dict[str, type] = {
    "schema_version": int,
    "state_revision": int,
    "active_learner_id": str,
    "learners": dict,
    "lesson_assignments": list,
    "attempts": list,
    "assessments": list,
}
_OPTIONAL_STATE_FIELDS: dict[str, type] = {
    "progress_events": list,
    "signals": list,
}


class JsonStateStore:
    def __init__(self, state_path: Path) -> None:
        self._state_path = state_path
        self._lock_path = state_path.with_name(STATE_LOCK_FILE_NAME)
        self._backup_path = state_path.with_suffix(f"{state_path.suffix}.bak")

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
            recovered = self._recover_from_backup()
            if recovered is not None:
                return recovered
            state = self._empty_state()
            self._write_state(state)
            return state

        try:
            return self._read_valid_state_file(self._state_path)
        except StorageError as primary_error:
            recovered = self._recover_from_backup()
            if recovered is not None:
                return recovered
            raise primary_error

    def _read_valid_state_file(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as state_file:
                state = json.load(state_file)
        except json.JSONDecodeError as exc:
            raise storage_error(
                "JSON state file is invalid",
                retryable=False,
                path=str(path),
            ) from exc
        except OSError as exc:
            raise storage_error(
                "Failed to read JSON state file",
                path=str(path),
            ) from exc

        if not isinstance(state, dict):
            raise storage_error(
                "JSON state file must contain an object",
                retryable=False,
                path=str(path),
                state_type=type(state).__name__,
            )

        schema_version = state.get("schema_version")
        if schema_version != SCHEMA_VERSION:
            raise storage_error(
                "Unsupported JSON state schema version",
                retryable=False,
                path=str(path),
                schema_version=schema_version,
                supported_schema_version=SCHEMA_VERSION,
            )

        self._validate_state_shape(state, path)
        self._apply_current_schema_defaults(state)
        return state

    def _validate_state_shape(self, state: dict[str, Any], path: Path) -> None:
        for field, expected_type in _REQUIRED_STATE_FIELDS.items():
            if field not in state:
                raise storage_error(
                    "JSON state file is missing a required field",
                    retryable=False,
                    path=str(path),
                    field=field,
                )
            self._validate_state_field_type(state, path, field, expected_type)

        for field, expected_type in _OPTIONAL_STATE_FIELDS.items():
            if field in state:
                self._validate_state_field_type(state, path, field, expected_type)

    @staticmethod
    def _validate_state_field_type(
        state: dict[str, Any],
        path: Path,
        field: str,
        expected_type: type,
    ) -> None:
        if type(state[field]) is not expected_type:
            raise storage_error(
                "JSON state file has an invalid field type",
                retryable=False,
                path=str(path),
                field=field,
                expected_type=expected_type.__name__,
                actual_type=type(state[field]).__name__,
            )

    def _recover_from_backup(self) -> dict[str, Any] | None:
        if not self._backup_path.exists():
            return None

        try:
            state = self._read_valid_state_file(self._backup_path)
        except StorageError:
            return None

        self._write_state_without_backup(state)
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self._write_backup_if_current_state_is_valid()
        self._write_state_without_backup(state)

    def _write_state_without_backup(self, state: dict[str, Any]) -> None:
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

    def _write_backup_if_current_state_is_valid(self) -> None:
        if not self._state_path.exists():
            return

        try:
            self._read_valid_state_file(self._state_path)
        except StorageError:
            return

        try:
            shutil.copy2(self._state_path, self._backup_path)
        except OSError as exc:
            raise storage_error(
                "Failed to back up JSON state file",
                path=str(self._state_path),
                backup_path=str(self._backup_path),
            ) from exc

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

    @staticmethod
    def _apply_current_schema_defaults(state: dict[str, Any]) -> None:
        state.setdefault("progress_events", [])
        state.setdefault("signals", [])
