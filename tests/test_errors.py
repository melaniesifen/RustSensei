from rust_sensei.errors import (
    idempotency_conflict_error,
    not_found_error,
    storage_error,
    validation_error,
)


def test_error_factories_create_structured_envelopes():
    validation = validation_error("bad", field="name")
    not_found = not_found_error("missing", id="abc")
    storage = storage_error("locked", retryable=True)
    conflict = idempotency_conflict_error("conflict", client_request_id="req-1")

    assert validation.envelope.to_dict()["error_code"] == "validation_error"
    assert validation.envelope.to_dict()["details"] == {"field": "name"}
    assert not_found.envelope.to_dict()["error_code"] == "not_found"
    assert storage.envelope.to_dict()["retryable"] is True
    assert conflict.envelope.to_dict()["error_code"] == "idempotency_conflict"
