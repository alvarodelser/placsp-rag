import subprocess, sys

def test_cli_help_lists_commands():
    out = subprocess.run([sys.executable, "-m", "placsp", "--help"],
                         capture_output=True, text=True, cwd=".",
                         env={**__import__("os").environ, "PYTHONPATH": "src"})
    assert "backfill" in out.stdout and "daily" in out.stdout and "init-schema" in out.stdout

def test_cli_unknown_command_errors():
    out = subprocess.run([sys.executable, "-m", "placsp", "nope"], capture_output=True, text=True,
                         env={**__import__("os").environ, "PYTHONPATH": "src"})
    assert out.returncode != 0
