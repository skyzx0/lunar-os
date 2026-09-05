"""Static checks on build/entrypoint.sh.

A patch once replaced a block of that file and deleted two function
definitions along with it. The calls remained, so the build failed with
"exit code 127" and no indication of which command was missing. This checks
that every function called is defined, cheaply, before any build runs.
"""

import re
import subprocess
import sys
from pathlib import Path

script = Path(__file__).resolve().parent.parent / "build" / "entrypoint.sh"
text = script.read_text()

# 1. It must at least parse.
r = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
assert r.returncode == 0, f"entrypoint.sh does not parse:\n{r.stderr}"

# 2. Every internal call must resolve to a definition.
defined = set(re.findall(r"^([a-z_]+)\(\) *\{", text, re.M))

# Calls at the start of a line inside a function body, four-space indented.
called = set(re.findall(r"^ {4}([a-z_]+)\s*$", text, re.M))

# Shell keywords and real programs, neither of which are functions here.
external = {
    "true", "false", "shellcheck", "namcap", "exit", "return",
    "done", "fi", "esac", "then", "else", "do", "elif", "in", "shift",
    "break", "continue", "local", "readonly", "unset",
}

undefined = {c for c in called if c not in defined and c not in external}
undefined = {c for c in undefined
             if subprocess.run(["command", "-v", c], shell=False,
                               capture_output=True,
                               executable="/bin/bash").returncode != 0}

assert not undefined, (
    f"entrypoint.sh calls functions that are not defined: {sorted(undefined)}")

# 3. Every command dispatched by the case statement must exist as a function.
for cmd in ("repo", "repo-unsigned", "iso", "check", "shell", "clean"):
    fn = "cmd_" + cmd.replace("-", "_")
    assert fn in defined, f"dispatch target {fn} is missing"

print(f"entrypoint.sh: parses, {len(defined)} functions, all calls resolve")
