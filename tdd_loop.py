#!/usr/bin/env python3
"""
claude-tdd-loop — Test-Driven Autonomy for Claude Code
=======================================================
Give Claude a test file. It writes the implementation, runs the tests,
reads the failures, fixes the code. Loops until green or gives up.

USAGE:
    python tdd_loop.py tests/test_auth.py
    python tdd_loop.py tests/test_api.py --src src/ --max-iterations 15
    python tdd_loop.py tests/test_utils.py --task "use only stdlib, no dependencies"

HOW IT WORKS:
    1. Claude reads the test file and writes an implementation
    2. pytest runs against the implementation
    3. If red → stack trace is fed back to Claude: "Fix it"
    4. If stuck in same error → strategy changes: "Different approach"
    5. Loop exits on green (100% pass) or max iterations reached

REQUIREMENTS: claude CLI, pytest, Python 3.8+
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── ANSI ──────────────────────────────────────────────────────────────────────
R = "\033[0;31m"; G = "\033[0;32m"; Y = "\033[1;33m"
C = "\033[0;36m"; B = "\033[1m"; DIM = "\033[2m"; RESET = "\033[0m"

# ── Test runners registry (extensible) ───────────────────────────────────────
RUNNERS = {
    "pytest": {
        "detect": lambda files: any(f.name.startswith("test_") or f.name.endswith("_test.py") for f in files),
        "cmd": ["python", "-m", "pytest", "--tb=short", "--no-header", "-q"],
        "success_pattern": r"(\d+) passed",
        "failure_pattern": r"(\d+) failed",
    },
    # Future: jest, go test, cargo test...
}


def log(level: str, msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    icons = {"INFO": f"{C}ℹ{RESET}", "OK": f"{G}✓{RESET}",
             "WARN": f"{Y}⚠{RESET}", "ERROR": f"{R}✗{RESET}",
             "TEST": f"{B}🧪{RESET}", "FIX": f"{Y}🔧{RESET}"}
    print(f"[{ts}] {icons.get(level,'·')} {msg}")


def run_claude(prompt: str, model: str, timeout: int = 180) -> tuple[str, int]:
    try:
        result = subprocess.run(
            ["claude", "--print", "--model", model],
            input=prompt, capture_output=True, text=True, timeout=timeout
        )
        return (result.stdout + result.stderr).strip(), result.returncode
    except subprocess.TimeoutExpired:
        return f"ERROR: claude timeout after {timeout}s", 1
    except FileNotFoundError:
        return "ERROR: 'claude' not found. Install Claude Code CLI.", 127


def run_tests(test_file: Path, src_dir: Optional[Path]) -> tuple[bool, str, int, int]:
    """Run pytest. Returns (passed, output, n_passed, n_failed)."""
    cmd = ["python", "-m", "pytest", str(test_file), "--tb=short", "--no-header", "-q"]
    env_path = str(src_dir) if src_dir else "."

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
            cwd=env_path if src_dir else None
        )
        output = result.stdout + result.stderr

        passed = int(re.search(r"(\d+) passed", output).group(1)) if re.search(r"(\d+) passed", output) else 0
        failed = int(re.search(r"(\d+) failed", output).group(1)) if re.search(r"(\d+) failed", output) else 0
        errors = int(re.search(r"(\d+) error", output).group(1)) if re.search(r"(\d+) error", output) else 0

        total_fail = failed + errors
        success = result.returncode == 0 and total_fail == 0 and passed > 0

        return success, output, passed, total_fail

    except subprocess.TimeoutExpired:
        return False, "ERROR: test runner timed out after 60s", 0, 1
    except FileNotFoundError:
        return False, "ERROR: pytest not found. Install with: pip install pytest", 0, 1


def error_fingerprint(output: str) -> str:
    """Hash the core error type to detect if Claude is stuck in the same failure."""
    # Extract just error types and lines, ignore line numbers (those change)
    lines = []
    for line in output.split("\n"):
        if any(x in line for x in ["Error:", "assert", "FAILED", "ImportError", "TypeError"]):
            # Remove line numbers and memory addresses
            clean = re.sub(r"line \d+", "line N", line)
            clean = re.sub(r"0x[0-9a-f]+", "0xADDR", clean)
            lines.append(clean.strip())
    return hashlib.md5("\n".join(lines[:5]).encode()).hexdigest()[:8]


def build_initial_prompt(test_file: Path, src_dir: Optional[Path],
                          task_hint: Optional[str]) -> str:
    test_content = test_file.read_text(encoding="utf-8")
    output_dir = src_dir or test_file.parent

    hint_block = f"\nAdditional requirements: {task_hint}\n" if task_hint else ""

    return f"""You are a TDD implementation agent. Your job is to write code that makes these tests pass.

TEST FILE: {test_file}
{hint_block}
TEST CONTENT:
```python
{test_content}
```

Instructions:
1. Analyze what the tests expect
2. Infer the module name from the test imports
3. Write a complete implementation file in {output_dir}/
4. Make ALL tests pass
5. Do not modify the test file
6. Write clean, minimal code — only what's needed to pass the tests

Write the implementation now. Create the file directly."""


def build_fix_prompt(test_file: Path, test_output: str, iteration: int,
                     stuck: bool, history: list[str]) -> str:
    # Truncate output to most relevant part
    lines = test_output.split("\n")
    relevant = "\n".join(lines[-60:]) if len(lines) > 60 else test_output

    stuck_block = ""
    if stuck:
        stuck_block = """
⚠️  IMPORTANT: You have failed with the same error multiple times.
Do NOT try the same fix again. Take a completely different approach:
- Rethink your implementation from scratch
- Check if the module name/path is wrong
- Check if you're missing an __init__.py
- Try a simpler implementation strategy
"""

    history_block = ""
    if len(history) >= 2:
        history_block = f"\nPrevious error fingerprints: {', '.join(history[-3:])} (don't repeat these patterns)\n"

    return f"""You are fixing a Python implementation to make failing tests pass.

TEST FILE: {test_file}
ITERATION: {iteration}
{stuck_block}{history_block}
PYTEST OUTPUT:
```
{relevant}
```

Instructions:
1. Read the FULL error carefully
2. Identify the root cause (not just the symptom)
3. Fix the implementation file — do NOT modify the test file
4. Make ALL tests pass

Fix the code now."""


def print_test_result(success: bool, output: str, passed: int, failed: int, iteration: int):
    print()
    if success:
        print(f"  {G}{B}{'─'*40}")
        print(f"  ✅ ALL TESTS PASS  ({passed} passed)")
        print(f"  {'─'*40}{RESET}")
    else:
        total = passed + failed
        bar_len = 30
        p = int((passed / total) * bar_len) if total > 0 else 0
        bar = f"{G}{'█'*p}{RESET}{R}{'░'*(bar_len-p)}{RESET}"
        print(f"  [{bar}] {G}{passed}{RESET}/{total}")

        # Show only the most relevant error lines
        error_lines = []
        capture = False
        for line in output.split("\n"):
            if "FAILED" in line or "ERROR" in line or "assert" in line.lower():
                capture = True
            if capture and line.strip():
                error_lines.append(f"  {DIM}{line}{RESET}")
            if len(error_lines) >= 8:
                break

        if error_lines:
            print("\n".join(error_lines))
    print()


def main():
    parser = argparse.ArgumentParser(
        description="TDD loop: Claude writes code, tests run, failures feed back until green"
    )
    parser.add_argument("test_file", help="Path to the test file (e.g. tests/test_auth.py)")
    parser.add_argument("--src", metavar="DIR",
                        help="Source directory where Claude should write the implementation")
    parser.add_argument("--task", "-t", metavar="HINT",
                        help="Extra requirements for Claude (e.g. 'use only stdlib')")
    parser.add_argument("--max-iterations", "-n", type=int, default=10,
                        help="Max fix attempts before giving up (default: 10)")
    parser.add_argument("--stuck-threshold", type=int, default=3,
                        help="Same error N times in a row = stuck, force strategy change (default: 3)")
    parser.add_argument("--model", default="claude-sonnet-4-20250514",
                        help="Claude model to use")
    parser.add_argument("--log", metavar="FILE",
                        help="Save full session log to file")
    args = parser.parse_args()

    test_file = Path(args.test_file)
    if not test_file.exists():
        print(f"{R}Error: test file '{test_file}' not found.{RESET}")
        sys.exit(1)

    src_dir = Path(args.src) if args.src else None
    if src_dir:
        src_dir.mkdir(parents=True, exist_ok=True)

    log_lines = []

    def logf(level: str, msg: str):
        log(level, msg)
        log_lines.append(f"[{datetime.now().strftime('%H:%M:%S')}] {level} {msg}")

    # ── Banner ────────────────────────────────────────────────────────────────
    print(f"\n{B}{C}╔══════════════════════════════════════════╗")
    print(f"║      claude-tdd-loop  🧪  v1.0.0         ║")
    print(f"║    Test-Driven Autonomy for Claude Code   ║")
    print(f"╚══════════════════════════════════════════╝{RESET}\n")
    logf("INFO", f"Test file:  {B}{test_file}{RESET}")
    if src_dir:
        logf("INFO", f"Source dir: {B}{src_dir}{RESET}")
    if args.task:
        logf("INFO", f"Task hint:  {B}{args.task}{RESET}")
    logf("INFO", f"Max iterations: {args.max_iterations}  |  Model: {args.model}")
    print(f"{DIM}{'─'*46}{RESET}\n")

    # ── Iteration state ───────────────────────────────────────────────────────
    error_history: list[str] = []
    consecutive_same = 0
    last_fingerprint = ""
    start_all = time.time()
    final_status = "failed"

    for iteration in range(1, args.max_iterations + 1):
        is_first = iteration == 1
        is_stuck = consecutive_same >= args.stuck_threshold

        # ── Ask Claude to write/fix ───────────────────────────────────────────
        if is_first:
            logf("INFO", f"{B}Iteration {iteration}/{args.max_iterations}{RESET} — Writing initial implementation...")
            prompt = build_initial_prompt(test_file, src_dir, args.task)
        else:
            action = "Forcing new strategy" if is_stuck else "Fixing"
            logf("FIX", f"{B}Iteration {iteration}/{args.max_iterations}{RESET} — {action}...")
            prompt = build_fix_prompt(test_file, last_test_output, iteration,
                                      is_stuck, error_history)

        t0 = time.time()
        claude_output, claude_code = run_claude(prompt, args.model)
        claude_time = time.time() - t0

        if claude_code != 0 and "rate_limit" in claude_output.lower():
            logf("WARN", f"Rate limit hit. Waiting 90s...")
            time.sleep(90)
            continue

        logf("INFO", f"Claude responded in {claude_time:.1f}s")

        # ── Run tests ─────────────────────────────────────────────────────────
        logf("TEST", "Running pytest...")
        success, test_output, passed, failed = run_tests(test_file, src_dir)
        last_test_output = test_output

        print_test_result(success, test_output, passed, failed, iteration)

        if success:
            elapsed = time.time() - start_all
            logf("OK", f"{B}{G}All tests pass! ✅  ({iteration} iteration{'s' if iteration>1 else ''}, {elapsed:.1f}s total){RESET}")
            final_status = "success"
            break

        # ── Stuck detection ───────────────────────────────────────────────────
        fp = error_fingerprint(test_output)
        if fp == last_fingerprint:
            consecutive_same += 1
            if is_stuck:
                logf("WARN", f"Same error {consecutive_same}x in a row — forcing strategy change next iteration")
        else:
            consecutive_same = 0
            last_fingerprint = fp

        error_history.append(fp)
        logf("INFO", f"Error fingerprint: {DIM}{fp}{RESET}  (consecutive: {consecutive_same})")

    else:
        elapsed = time.time() - start_all
        logf("ERROR", f"Reached max iterations ({args.max_iterations}) without passing all tests.")
        logf("ERROR", f"Last test output saved for inspection.")

    # ── Save log ──────────────────────────────────────────────────────────────
    if args.log:
        Path(args.log).write_text("\n".join(log_lines))
        logf("INFO", f"Log saved → {args.log}")

    # ── Save session manifest ─────────────────────────────────────────────────
    manifest = {
        "test_file": str(test_file),
        "status": final_status,
        "iterations": iteration,
        "model": args.model,
        "timestamp": datetime.now().isoformat(),
    }
    Path("tdd_session.json").write_text(json.dumps(manifest, indent=2))

    sys.exit(0 if final_status == "success" else 1)


if __name__ == "__main__":
    main()
