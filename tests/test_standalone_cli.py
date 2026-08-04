# SPDX-License-Identifier: CPAL-1.0
import builtins

import pytest

from remember_me.standalone.cli import build_parser, main


def test_version_and_about_include_project_identity(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["--version"])
    assert raised.value.code == 0
    version = capsys.readouterr().out
    assert "Remember-Me" in version
    assert "0.1.0.dev7" in version
    assert "originally created by Ting (peanutsuee)" in version

    assert main(["about"]) == 0
    about = capsys.readouterr().out
    for expected in [
        "Remember-Me",
        "0.1.0.dev7",
        "Ting (peanutsuee)",
        "v1alpha1",
        "MCP API",
        "ombre-brain-assets-v1",
        "CPAL-1.0",
    ]:
        assert expected in about


def test_serve_help_has_no_command_line_token(capsys):
    with pytest.raises(SystemExit) as raised:
        main(["serve", "--help"])
    assert raised.value.code == 0
    output = capsys.readouterr().out
    assert "--auth-token-file" in output
    assert "--auth-token " not in output
    assert "--allow-network" in output
    assert "--enable-docs" in output
    assert "--public-base-url" in output


def test_parser_rejects_command_line_token():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["serve", "--auth-token", "not-accepted"])


def test_missing_optional_dependencies_have_clear_message(
    monkeypatch,
    capsys,
):
    original_import = builtins.__import__

    def fail_uvicorn(name, *args, **kwargs):
        if name == "uvicorn":
            raise ImportError("simulated")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_uvicorn)
    assert main(["serve"]) == 2
    assert "remember-me[standalone]" in capsys.readouterr().err
