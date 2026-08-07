"""Unit tests for open_terminal.utils.redact (homelab#720)."""

from open_terminal.utils.redact import redact_secrets


def test_empty_and_none_like_input_unchanged():
    assert redact_secrets("") == ""


def test_plain_text_without_secrets_unchanged():
    text = "hello world, nothing sensitive here\nexit code 0"
    assert redact_secrets(text) == text


def test_github_installation_token():
    text = "token: ghs_" + "a" * 36
    out = redact_secrets(text)
    assert "ghs_" not in out
    assert "[REDACTED:github-token]" in out


def test_github_personal_access_token_classic():
    text = "export GH_TOKEN=ghp_" + "B" * 36
    out = redact_secrets(text)
    assert "ghp_" not in out
    assert "[REDACTED:github-token]" in out


def test_github_fine_grained_pat():
    text = "github_pat_" + "x" * 30
    out = redact_secrets(text)
    assert "[REDACTED:github-pat-fine-grained]" in out


def test_pem_private_key_block():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEowIBAAKCAQEAversecretkeymaterial\nmoresecretlines\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    out = redact_secrets(text)
    assert "secretkeymaterial" not in out
    assert "[REDACTED:private-key]" in out


def test_pem_private_key_block_no_type_qualifier():
    text = "-----BEGIN PRIVATE KEY-----\nabc123\n-----END PRIVATE KEY-----"
    out = redact_secrets(text)
    assert "abc123" not in out
    assert "[REDACTED:private-key]" in out


def test_aws_access_key_id():
    text = "AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP"
    out = redact_secrets(text)
    assert "AKIAABCDEFGHIJKLMNOP" not in out
    assert "[REDACTED:aws-access-key-id]" in out


def test_slack_token():
    text = "SLACK_WEBHOOK_TOKEN=xoxb-1234567890-abcdefghij"
    out = redact_secrets(text)
    assert "xoxb-" not in out
    assert "[REDACTED:slack-token]" in out


def test_jwt():
    text = "Authorization set to eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
    out = redact_secrets(text)
    assert "[REDACTED:jwt]" in out


def test_bearer_token():
    text = "curl -H 'Authorization: Bearer abcDEF123456789012345'"
    out = redact_secrets(text)
    assert "[REDACTED:bearer-token]" in out


def test_multiple_secrets_in_one_string_all_redacted():
    text = f"first ghp_{'a' * 36} then AKIAABCDEFGHIJKLMNOP"
    out = redact_secrets(text)
    assert "ghp_" not in out
    assert "AKIAABCDEFGHIJKLMNOP" not in out


def test_the_original_env_grep_case_from_the_issue():
    # homelab#720's own discovered case: `env | grep -E '^(GH_|GITHUB_)'`
    # output containing a real App private key.
    text = (
        "GH_TOKEN=ghs_" + "z" * 36 + "\n"
        "GITHUB_APP_PRIVATE_KEY=-----BEGIN RSA PRIVATE KEY-----\n"
        "abcdefghijklmnop\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    out = redact_secrets(text)
    assert "ghs_" not in out
    assert "abcdefghijklmnop" not in out
