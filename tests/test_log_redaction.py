"""Unit tests for open_terminal.utils.log's redaction wiring (homelab#720)."""

import json

from open_terminal.utils.log import _redact_line


def test_line_without_secret_returned_unchanged():
    line = json.dumps({"type": "output", "data": "hello\n", "ts": 1.0}) + "\n"
    assert _redact_line(line) == line


def test_output_record_data_field_redacted():
    secret = "ghp_" + "a" * 36
    line = json.dumps({"type": "output", "data": secret, "ts": 1.0}) + "\n"
    out = _redact_line(line)
    assert secret not in out
    record = json.loads(out)
    assert "[REDACTED:github-token]" in record["data"]
    # non-secret fields untouched
    assert record["type"] == "output"
    assert record["ts"] == 1.0


def test_start_record_command_field_redacted():
    secret = "AKIAABCDEFGHIJKLMNOP"
    line = json.dumps({"type": "start", "command": f"echo {secret}", "pid": 123, "ts": 1.0}) + "\n"
    out = _redact_line(line)
    record = json.loads(out)
    assert secret not in record["command"]
    assert record["pid"] == 123


def test_end_record_has_no_redactable_fields_unchanged():
    line = json.dumps({"type": "end", "exit_code": 0, "log_rotated": False, "ts": 1.0}) + "\n"
    assert _redact_line(line) == line


def test_malformed_json_returned_unchanged_not_raised():
    line = "not valid json at all\n"
    assert _redact_line(line) == line


def test_non_dict_json_returned_unchanged():
    line = json.dumps([1, 2, 3]) + "\n"
    assert _redact_line(line) == line


def test_preserves_trailing_newline_when_redacting():
    secret = "ghp_" + "b" * 36
    line = json.dumps({"type": "output", "data": secret}) + "\n"
    out = _redact_line(line)
    assert out.endswith("\n")
