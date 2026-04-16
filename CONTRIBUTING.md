# Contributing to orcai-mcp

## Prerequisites

- Python 3.12+
- Node.js 18+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Local Dev Setup

```bash
git clone https://github.com/quieromas-ai/orcai-mcp.git
cd orcai-mcp

# Python environment
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"

# React UI
cd ui && npm install && npm run build && cd ..

# Configure environment
cp .env.example .env
# Edit .env — set ANTHROPIC_API_KEY or leave blank if using Claude Code CLI auth
```

Start the server:

```bash
python -m src.main
```

## Running Tests

All tests must pass before submitting a PR:

```bash
pytest
```

## Static Analysis

Both tools must be clean before committing:

```bash
ruff check .       # linting
mypy src/ cli/     # type checking
```

Auto-format code with:

```bash
ruff format .
```

Code style rules: line-length 100, Python 3.12 target (configured in `pyproject.toml`).

## Submitting a Pull Request

- One feature or fix per PR — keep changes focused
- Write a clear PR description explaining the problem and your solution
- New functionality requires tests
- All checks (tests + static analysis) must pass

## Reporting Bugs

Open a [GitHub Issue](https://github.com/quieromas-ai/orcai-mcp/issues) with:
- What you expected to happen
- What actually happened
- Steps to reproduce
- Relevant logs or error output

For **security vulnerabilities**, see [SECURITY.md](SECURITY.md) — do not open a public issue.

## Feature Requests

For substantial new features, open a [GitHub Discussion](https://github.com/quieromas-ai/orcai-mcp/discussions) before building to align on scope and approach. Small improvements can go straight to a PR.
