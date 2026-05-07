# claude-tdd-loop 🧪

**Test-Driven Autonomy for Claude Code** — give it a test file, it writes the implementation, runs the tests, reads the failures, and fixes until green.

You write the *contract* (tests). Claude writes the *code* that fulfills it. Automatically.

---

## The Loop

```
┌─────────────────────────────────────────┐
│  You provide: test_auth.py              │
└──────────────────┬──────────────────────┘
                   │
                   ▼
         ┌─────────────────┐
         │  Claude writes  │  ← reads test file, infers module, writes implementation
         │  implementation │
         └────────┬────────┘
                  │
                  ▼
         ┌─────────────────┐
         │   pytest runs   │  ← deterministic feedback, no interpretation needed
         └────────┬────────┘
                  │
           ┌──────┴──────┐
           │             │
         GREEN           RED
           │             │
           ▼             ▼
         Done ✅    Stack trace →
                    Claude fixes →
                    pytest runs →
                    loop...
```

The loop exits on **100% pass** or `--max-iterations` reached.

---

## Why this works better than just asking Claude to write code

When you ask Claude to "write an auth module", you get something that *looks* right. When you run it, you find out. Then you copy the error, paste it back, ask for a fix, repeat manually.

`claude-tdd-loop` closes that cycle automatically. The test runner is an oracle — no ambiguity, no "does this look right?" — just green or red.

---

## Requirements

- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- Python 3.8+
- `pytest` (`pip install pytest`)

---

## Installation

```bash
git https://github.com/Mariglend/claude-tdd-loop.git
cd claude-tdd-loop
pip install pytest
```

---

## Usage

### Basic
```bash
python tdd_loop.py tests/test_auth.py
```

### With source directory
```bash
python tdd_loop.py tests/test_auth.py --src src/
```

### With extra requirements
```bash
python tdd_loop.py tests/test_parser.py --task "use only stdlib, no third-party libraries"
```

### Control iterations and save log
```bash
python tdd_loop.py tests/test_api.py --max-iterations 15 --log session.log
```

### All options
```
positional:
  test_file              Path to the test file

options:
  --src DIR              Where Claude should write the implementation
  --task HINT            Extra requirements (e.g. "no external dependencies")
  --max-iterations N     Give up after N attempts (default: 10)
  --stuck-threshold N    Force strategy change after same error N times (default: 3)
  --model MODEL          Claude model to use
  --log FILE             Save session log to file
```

---

## Live output

```
╔══════════════════════════════════════════╗
║      claude-tdd-loop  🧪  v1.0.0         ║
╚══════════════════════════════════════════╝

[14:32:01] ℹ  Test file: tests/test_auth.py
[14:32:01] ℹ  Max iterations: 10  |  Model: claude-sonnet-4-20250514

[14:32:01] ℹ  Iteration 1/10 — Writing initial implementation...
[14:32:14] ℹ  Claude responded in 13.2s
[14:32:14] 🧪  Running pytest...

  [████████░░░░░░░░░░░░░░░░░░░░░░] 2/8
  AssertionError: expected 'Bearer' prefix in token
  FAILED tests/test_auth.py::test_generate_token

[14:32:14] 🔧  Iteration 2/10 — Fixing...
[14:32:26] ℹ  Claude responded in 12.1s
[14:32:26] 🧪  Running pytest...

  [████████████████████████████░░] 7/8
  FAILED tests/test_auth.py::test_expired_token

[14:32:26] 🔧  Iteration 3/10 — Fixing...
[14:32:38] ℹ  Claude responded in 11.8s
[14:32:38] 🧪  Running pytest...

  ────────────────────────────────────────
  ✅ ALL TESTS PASS  (8 passed)
  ────────────────────────────────────────

[14:32:38] ✓  All tests pass! ✅  (3 iterations, 37.4s total)
```

---

## Stuck detection

If Claude fails with the **same error fingerprint** 3 times in a row, the next prompt explicitly tells it to abandon its current approach and try something fundamentally different. This prevents infinite loops where Claude keeps patching the same wrong assumption.

Error fingerprints are computed from the error type and message, stripping line numbers — so the same logical error is recognized even if it moves around the file.

---

## Writing good tests for this tool

The cleaner your tests, the better Claude performs. A few tips:

```python
# ✅ Good — explicit about what module to import
from auth import generate_token, verify_token

# ✅ Good — tests one thing clearly
def test_token_has_bearer_prefix():
    token = generate_token(user_id=1)
    assert token.startswith("Bearer ")

# ❌ Avoid — too vague, Claude won't know what to name the function
def test_it_works():
    result = do_something()
    assert result
```

The import statement is the most important part — Claude infers the filename and module structure from it.

---

## Pair with

- [claude-warmup](https://github.com/Mariglend/claude-warmup.git) — run warmup first if you're implementing inside an existing codebase
- [claude-swarm](https://github.com/Mariglend/claude-swarm.git) — use swarm to write N test files in parallel, then tdd-loop to implement each
- [claude-resume](https://github.com/Mariglend/claude-resume.git) — auto-resume if rate limit hits mid-loop

---

## Roadmap

- [ ] JS/Jest support
- [ ] Go `testing` package support  
- [ ] Coverage threshold flag (`--coverage 80`)
- [ ] Auto-generate stub test file from a description (`--scaffold`)

---

## License

MIT
