"""Behavioral regressions for Cookbook's local Ollama download preflight."""

import os
import subprocess

from routes.cookbook_routes import _append_local_ollama_download_command_lines


def _run_preflight(tmp_path, *, docker_fallback_available, docker_fallback_blocked):
    lines = []
    _append_local_ollama_download_command_lines(
        lines,
        "ollama pull qwen2.5-coder:14b",
        docker_fallback_available=docker_fallback_available,
        docker_fallback_blocked=docker_fallback_blocked,
    )
    lines.append('printf "PULL_CMD=%s\\n" "${ODYSSEUS_OLLAMA_PULL_CMD:-}"')
    return subprocess.run(
        ["/bin/bash", "-c", "\n".join(lines)],
        env={**os.environ, "PATH": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )


def test_missing_ollama_reports_missing_cli_before_optional_docker_access(tmp_path):
    # A Docker CLI may exist even though the host socket is deliberately absent.
    docker = tmp_path / "docker"
    docker.write_text("#!/bin/sh\nexit 91\n", encoding="utf-8")
    docker.chmod(0o755)

    result = _run_preflight(
        tmp_path, docker_fallback_available=False, docker_fallback_blocked=True
    )

    assert result.returncode == 127
    assert result.stdout.startswith(
        "ERROR: Ollama is not installed or not on PATH in this environment."
    )
    assert "Install Ollama" in result.stdout
    assert "GGUF for llama.cpp" in result.stdout
    assert "optional Docker container fallback" in result.stdout
    assert "PULL_CMD=" not in result.stdout
    assert result.stderr == ""


def test_missing_ollama_without_docker_uses_generic_missing_cli_error(tmp_path):
    result = _run_preflight(
        tmp_path, docker_fallback_available=False, docker_fallback_blocked=False
    )

    assert result.returncode == 127
    assert result.stdout.startswith("ERROR: Ollama not found on this server.")
    assert "PULL_CMD=" not in result.stdout


def test_native_ollama_still_takes_priority_when_docker_access_is_blocked(tmp_path):
    ollama = tmp_path / "ollama"
    ollama.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    ollama.chmod(0o755)

    result = _run_preflight(
        tmp_path, docker_fallback_available=False, docker_fallback_blocked=True
    )

    assert result.returncode == 0
    assert result.stdout == "PULL_CMD=ollama pull qwen2.5-coder:14b\n"
    assert result.stderr == ""
