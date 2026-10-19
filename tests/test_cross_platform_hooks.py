"""Cross-platform hook configuration regressions."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOKS_JSON = REPO_ROOT / "hooks" / "hooks.json"
HOOK_LAUNCHER = REPO_ROOT / "hooks" / "run-python-hook.js"
INSTALL_PS1 = REPO_ROOT / "install.ps1"


def _post_tool_handler() -> dict:
    config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
    return config["hooks"]["PostToolUse"][0]["hooks"][0]


def test_schema_hook_uses_exec_form_args_and_tool_input_placeholder() -> None:
    handler = _post_tool_handler()
    serialized = json.dumps(handler)

    assert handler["type"] == "command"
    assert handler["command"] == "node"
    assert "args" in handler
    assert handler["args"][0] == "${CLAUDE_PLUGIN_ROOT}/hooks/run-python-hook.js"
    assert handler["args"][1] == "${CLAUDE_PLUGIN_ROOT}/hooks/validate-schema.py"
    assert handler["args"][2] == "${tool_input.file_path}"
    assert "$FILE_PATH" not in serialized
    assert "$" not in handler["command"]
    assert handler["command"] != "sh"


def test_hook_launcher_documents_python_probe_order() -> None:
    text = HOOK_LAUNCHER.read_text(encoding="utf-8")
    for marker in ("CLAUDE_SEO_PYTHON", "py", "-3", "python3", "python"):
        assert marker in text


def test_hook_launcher_preserves_blocking_exit_code_two(tmp_path: Path) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available in this test environment")

    script = tmp_path / "block.py"
    script.write_text(
        "import sys\n"
        "assert sys.argv[1] == 'payload'\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["CLAUDE_SEO_PYTHON"] = sys.executable

    proc = subprocess.run(
        [node, str(HOOK_LAUNCHER), str(script), "payload"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 2


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script and chmod")
def test_hook_launcher_does_not_rerun_hook_after_a_spawn_error(tmp_path: Path) -> None:
    """A spawn error after a successful probe must not hand the hook to the
    next interpreter: that ran the hook twice and ended in exit 1, the
    signature of the intermittent Windows CI timeout."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available in this test environment")

    marker = tmp_path / "ran.txt"
    hook = tmp_path / "hook.py"
    hook.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).open('a').write('ran\\n')\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    # Passes the probe, then loses its execute bit, so spawning the hook
    # with it fails with EACCES rather than ENOENT.
    fake = tmp_path / "fake-python"
    fake.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-c" ]; then chmod -x "$0"; fi\n'
        f'exec {sys.executable!r} "$@"\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = os.environ.copy()
    env["CLAUDE_SEO_PYTHON"] = str(fake)

    proc = subprocess.run(
        [node, str(HOOK_LAUNCHER), str(hook)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert not marker.exists(), "hook ran under a fallback interpreter"
    assert proc.returncode == 1
    assert "CLAUDE_SEO_PYTHON" in proc.stderr


@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX path")
def test_hook_launcher_falls_through_when_interpreter_is_missing(tmp_path: Path) -> None:
    """ENOENT means the interpreter is gone: trying the next one is safe
    because the hook never started."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not available in this test environment")
    hook = tmp_path / "hook.py"
    hook.write_text("import sys\nsys.exit(2)\n", encoding="utf-8")
    env = os.environ.copy()
    env["CLAUDE_SEO_PYTHON"] = str(tmp_path / "no-such-python")

    proc = subprocess.run(
        [node, str(HOOK_LAUNCHER), str(hook)],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 2, proc.stderr


def test_windows_installer_prefers_py_launcher_and_rejects_store_stubs() -> None:
    text = INSTALL_PS1.read_text(encoding="utf-8")
    py_pos = text.index("Exe = 'py'; Args = @('-3')")
    python3_pos = text.index("Exe = 'python3'; Args = @()")
    python_pos = text.index("Exe = 'python'; Args = @()")

    assert py_pos < python3_pos < python_pos
    assert "Microsoft Store|WindowsApps|App execution alias|was not found" in text
