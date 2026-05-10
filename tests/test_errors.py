from rust_sensei.errors import not_found_error, storage_error, validation_error


def test_error_factories_create_structured_envelopes():
    validation = validation_error("bad", field="name")
    not_found = not_found_error("missing", id="abc")
    storage = storage_error("locked", retryable=True)

    assert validation.envelope.to_dict()["error_code"] == "validation_error"
    assert validation.envelope.to_dict()["details"] == {"field": "name"}
    assert not_found.envelope.to_dict()["error_code"] == "not_found"
    assert storage.envelope.to_dict()["retryable"] is True
