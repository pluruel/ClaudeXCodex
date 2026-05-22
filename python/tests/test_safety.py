from __future__ import annotations

from agent_loop.safety import (
    SafetyConfig,
    check_bash_command,
    check_path_sensitive,
    classify_diff_size,
    make_pretool_hook,
)


def _cfg() -> SafetyConfig:
    return SafetyConfig(
        bash_block_patterns=[
            r"^\s*git\s+(commit|push)",
            r"^\s*rm\s+-rf",
        ],
        sensitive_path_patterns=[r"\.env(\..+)?$", r"/migrations/"],
        diff_warn_files=15,
        diff_warn_lines=600,
    )


def test_bash_block_matches() -> None:
    cfg = _cfg()
    assert check_bash_command("git commit -m hi", cfg) is True
    assert check_bash_command("  rm -rf node_modules", cfg) is True
    assert check_bash_command("pytest -x", cfg) is False


def test_path_sensitive() -> None:
    cfg = _cfg()
    assert check_path_sensitive(".env", cfg) is True
    assert check_path_sensitive("app/.env.production", cfg) is True
    assert check_path_sensitive("src/db/migrations/0001.sql", cfg) is True
    assert check_path_sensitive("src/auth.py", cfg) is False


def test_diff_size_warnings() -> None:
    cfg = _cfg()
    flags = classify_diff_size(files=20, lines=300, cfg=cfg)
    assert "diff_too_many_files" in flags
    flags = classify_diff_size(files=2, lines=900, cfg=cfg)
    assert "diff_too_many_lines" in flags
    flags = classify_diff_size(files=2, lines=100, cfg=cfg)
    assert flags == []


def test_pretool_hook_blocks_bash() -> None:
    cfg = _cfg()
    hook = make_pretool_hook(cfg)
    blocked = hook(
        tool_name="Bash",
        tool_input={"command": "git push origin main"},
    )
    assert blocked is not None
    assert "blocked" in blocked.lower()


def test_pretool_hook_blocks_sensitive_write() -> None:
    cfg = _cfg()
    hook = make_pretool_hook(cfg)
    blocked = hook(tool_name="Write", tool_input={"file_path": "/repo/.env"})
    assert blocked is not None
    blocked2 = hook(tool_name="Edit", tool_input={"file_path": "/repo/src/x.py"})
    assert blocked2 is None
