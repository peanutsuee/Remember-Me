# SPDX-License-Identifier: CPAL-1.0
from pathlib import Path

import pytest

from remember_me.standalone.config import (
    StandaloneConfig,
    is_loopback_host,
    parse_bool,
)
from remember_me.standalone.errors import ConfigurationError


TEST_TOKEN = "stage7c-" + ("x" * 32)


def test_secure_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    config = StandaloneConfig()
    assert config.host == "127.0.0.1"
    assert config.port == 8787
    assert config.data_root == tmp_path / ".remember-me"
    assert config.allow_network is False
    assert config.enable_docs is False
    assert config.log_level == "INFO"
    assert config.resolved_auth_token is None


def test_cli_values_override_environment_and_environment_overrides_defaults(
    tmp_path,
):
    config = StandaloneConfig.from_sources(
        {
            "data_root": str(tmp_path / "cli"),
            "host": "localhost",
            "port": 9001,
            "log_level": "warning",
        },
        {
            "REMEMBER_ME_DATA_ROOT": str(tmp_path / "env"),
            "REMEMBER_ME_HOST": "127.0.0.1",
            "REMEMBER_ME_PORT": "9000",
            "REMEMBER_ME_LOG_LEVEL": "debug",
        },
    )
    assert config.data_root == tmp_path / "cli"
    assert config.host == "localhost"
    assert config.port == 9001
    assert config.log_level == "WARNING"


def test_public_base_url_cli_overrides_environment(tmp_path):
    config = StandaloneConfig.from_sources(
        {
            "data_root": str(tmp_path),
            "public_base_url": "https://cli.example.invalid/root/",
        },
        {
            "REMEMBER_ME_PUBLIC_BASE_URL": (
                "https://env.example.invalid/root/"
            ),
        },
    )
    assert config.resolved_public_base_url == (
        "https://cli.example.invalid/root"
    )


@pytest.mark.parametrize("value", ["1", " TRUE ", "Yes", "ON"])
def test_true_boolean_values(value):
    assert parse_bool(value, "test") is True


@pytest.mark.parametrize("value", ["0", " false ", "No", "OFF", ""])
def test_false_boolean_values(value):
    assert parse_bool(value, "test") is False


def test_invalid_boolean_is_configuration_error():
    with pytest.raises(ConfigurationError, match="Invalid boolean"):
        parse_bool("sometimes", "test")


@pytest.mark.parametrize("port", [0, 65536, "not-a-port", True])
def test_invalid_port(port):
    with pytest.raises(ConfigurationError):
        StandaloneConfig(port=port)


def test_invalid_log_level():
    with pytest.raises(ConfigurationError, match="log level"):
        StandaloneConfig(log_level="verbose")


def test_token_and_token_file_conflict(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text(TEST_TOKEN, encoding="utf-8")
    with pytest.raises(ConfigurationError, match="either"):
        StandaloneConfig(
            auth_token=TEST_TOKEN,
            auth_token_file=token_file,
        )


def test_token_file_rules(tmp_path):
    missing = tmp_path / "missing.txt"
    with pytest.raises(ConfigurationError, match="unavailable"):
        StandaloneConfig(auth_token_file=missing)

    token_file = tmp_path / "token.txt"
    token_file.write_text(TEST_TOKEN + "\n", encoding="utf-8")
    config = StandaloneConfig(auth_token_file=token_file)
    assert config.resolved_auth_token == TEST_TOKEN

    token_file.write_text(TEST_TOKEN + "\nsecond-line", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="newlines"):
        StandaloneConfig(auth_token_file=token_file)


def test_empty_token_environment_values_are_unset():
    config = StandaloneConfig.from_sources(
        environ={
            "REMEMBER_ME_AUTH_TOKEN": "",
            "REMEMBER_ME_AUTH_TOKEN_FILE": "",
        }
    )
    assert config.resolved_auth_token is None
    assert config.auth_token_file is None


def test_environment_token_is_absent_from_config_representations():
    config = StandaloneConfig.from_sources(
        environ={"REMEMBER_ME_AUTH_TOKEN": TEST_TOKEN}
    )
    assert config.resolved_auth_token == TEST_TOKEN
    assert TEST_TOKEN not in repr(config)
    assert TEST_TOKEN not in str(config)


def test_token_file_value_is_absent_from_config_representations(tmp_path):
    token_file = tmp_path / "token.txt"
    token_file.write_text(TEST_TOKEN, encoding="utf-8")
    config = StandaloneConfig(auth_token_file=token_file)
    assert config.resolved_auth_token == TEST_TOKEN
    assert TEST_TOKEN not in repr(config)
    assert TEST_TOKEN not in str(config)


@pytest.mark.parametrize(
    "token",
    ["short", "changeme", "token", "password", "example", "x" * 20],
)
def test_weak_tokens_are_rejected(token):
    with pytest.raises(ConfigurationError):
        StandaloneConfig(auth_token=token)


def test_direct_token_with_newline_is_rejected():
    with pytest.raises(ConfigurationError, match="newlines"):
        StandaloneConfig(auth_token=TEST_TOKEN + "\n")


def test_repeated_example_token_is_rejected():
    with pytest.raises(ConfigurationError, match="example"):
        StandaloneConfig(auth_token="example" * 5)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_without_token_is_allowed(host):
    assert is_loopback_host(host)
    assert StandaloneConfig(host=host).resolved_auth_token is None


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20"])
def test_non_loopback_requires_both_gates(host):
    assert not is_loopback_host(host)
    with pytest.raises(ConfigurationError, match="Non-loopback"):
        StandaloneConfig(host=host)
    with pytest.raises(ConfigurationError, match="Non-loopback"):
        StandaloneConfig(host=host, auth_token=TEST_TOKEN)
    config = StandaloneConfig(
        host=host,
        auth_token=TEST_TOKEN,
        allow_network=True,
    )
    assert config.allow_network is True
    assert config.resolved_auth_token == TEST_TOKEN
