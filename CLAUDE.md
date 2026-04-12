# CLAUDE.md — AI Assistant Guide for Polyback

## Project Overview

**Polyback** is a Polymarket strategy reverse tool. Its purpose is to analyze, reverse-engineer, or reconstruct trading/betting strategies used on [Polymarket](https://polymarket.com), a decentralized prediction market platform.

This is an early-stage project. At the time of writing, no implementation has been started — only the project concept exists. This file establishes conventions to follow as the codebase grows.

---

## Repository State

| Item | Status |
|---|---|
| Language / stack | Not yet decided |
| Source code | None yet |
| Tests | None yet |
| CI/CD | None yet |
| Dependencies | None yet |

When implementation begins, update this file to reflect decisions made.

---

## Development Workflow

### Branching

- `master` — stable, production-ready code
- Feature branches should be named `feature/<short-description>`
- Bug fix branches: `fix/<short-description>`
- Never commit directly to `master` without review

### Commit Messages

Use the imperative mood and keep the subject line under 72 characters:

```
Add Polymarket API client module
Fix incorrect odds normalization
Refactor strategy parser for clarity
```

For non-trivial changes, include a body explaining *why*, not just *what*.

### Pull Requests

- Summarize what the PR does and why
- Link any related issues
- Ensure tests pass before requesting review

---

## Codebase Conventions (to adopt when implementation starts)

### General

- Prefer readability over cleverness
- Keep functions small and single-purpose
- Document non-obvious logic with inline comments
- Avoid hardcoding credentials or API keys — use environment variables

### Environment Variables

Store secrets and configuration in a `.env` file (never commit it). Provide a `.env.example` with all required keys documented:

```
POLYMARKET_API_KEY=your_api_key_here
POLYMARKET_API_URL=https://api.polymarket.com
```

### Python (if adopted)

- Target Python 3.11+
- Use `pyproject.toml` for project metadata and dependencies
- Format with `black`, lint with `ruff`
- Type-annotate all public functions and classes
- Tests live in `tests/` and use `pytest`

Commands (once configured):
```bash
pip install -e ".[dev]"   # install in editable mode with dev deps
pytest                    # run tests
ruff check .              # lint
black .                   # format
```

### Node.js / TypeScript (if adopted)

- Target Node 20+ with TypeScript
- Use `pnpm` as the package manager
- Format with `prettier`, lint with `eslint`
- Tests use `vitest` or `jest`

Commands (once configured):
```bash
pnpm install    # install dependencies
pnpm dev        # run in development mode
pnpm test       # run tests
pnpm lint       # lint
pnpm build      # build for production
```

---

## Polymarket Domain Context

When working on this project, keep in mind:

- **Polymarket** is a prediction market platform where users trade on the probability of real-world events
- **Markets** contain two or more outcomes; each outcome has a price representing the implied probability (0–1)
- **CLOB (Central Limit Order Book)** — Polymarket uses a CLOB model for trading
- **USDC** is the settlement currency (Polygon chain)
- **Strategies** typically involve: market selection, position sizing, timing, and exit criteria

Relevant Polymarket resources:
- Polymarket CLOB API: `https://clob.polymarket.com`
- Polymarket Gamma API (market data): `https://gamma-api.polymarket.com`
- Polymarket documentation: `https://docs.polymarket.com`

---

## Project Structure (expected as code is added)

```
Polyback/
├── CLAUDE.md           # this file
├── README.md           # project overview
├── .env.example        # required environment variables (template)
├── .gitignore          # files excluded from version control
├── src/                # main source code
│   ├── api/            # Polymarket API clients
│   ├── strategy/       # strategy parsing and reverse-engineering logic
│   ├── models/         # data models / schemas
│   └── utils/          # shared utility functions
├── tests/              # test suite
├── scripts/            # one-off or utility scripts
└── docs/               # additional documentation
```

Update this section as the actual structure evolves.

---

## Key Implementation Areas

When building this tool, the following components will likely be needed:

1. **API Client** — fetch live and historical market data from Polymarket APIs
2. **Trade History Parser** — ingest trade history (on-chain or API-based) for a given address
3. **Strategy Reconstructor** — infer position-taking patterns, sizing logic, and timing from trade history
4. **Analysis / Reporting** — summarize findings in a human-readable or structured format

---

## AI Assistant Guidelines

- Always read existing files before modifying them
- Do not introduce new dependencies without confirming with the user
- Do not hardcode credentials; always use environment variables
- When adding features, add corresponding tests
- Keep changes focused — avoid refactoring unrelated code in the same PR
- If uncertain about Polymarket-specific behavior, consult the official docs or ask before guessing
- Update this CLAUDE.md whenever significant architectural decisions are made
