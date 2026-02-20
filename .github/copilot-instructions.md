
# Copilot instructions for TIGAS

## Repository reality (read first)

- This repo is currently a minimal scaffold: only `README.md`, `LICENSE`, and `.gitignore` are tracked.

-`README.md` defines the project intent: **Thin-Client Interactive Gaussian Adaptive Streaming over HTTP/3**.

- There is no implemented runtime architecture yet (no `src/`, no modules, no scripts, no tests) and there is no `environment.yaml` or `requirements.txt` present.

## What this means for AI coding agents

- Treat changes as **foundational setup work** unless the user provides additional files or requirements.
- Do not reference nonexistent components, services, or pipelines.
- Prefer small, explicit structure additions over broad scaffolding (create only what the task asks for).
- Keep documentation synchronized with any new code because `README.md` is currently the main project context.

## Project rules you must follow (authoritative)

- Environment changes: whenever you install, update, or remove packages, update or create `environment.yaml` (preferred) or `requirements.txt` at the repository root. Also add the exact environment creation / install command to `README.md`.
- Documentation lockstep: every change that introduces runtime behaviour (new CLI, module, or service) must include a short `README.md` snippet with how to run it.
- Style preference: prefer functional programming style (small, pure functions, explicit data flow). Use OOP only when it clarifies stateful responsibilities (e.g., streaming client/server state holders).
- Reviews: after producing code, provide a structured review with headings — Summary, What to change, Why, and Concrete examples from the code — and do not include direct code patches in the review; explain the required changes and rationale.
- Clarify when unsure: ask targeted questions about design decisions rather than guessing.

## Analysis & review focus (what to check in PRs / reviews)

- Code quality & structure: modularity, single responsibility, testability.
- Correctness & bugs: boundary conditions, input validation, error handling.
- Security: secrets, unsafe dependency usage, unsafe deserialization, input sanitization.
- Performance: streaming / I/O patterns, memory allocation, expensive synchronous loops.
- Accessibility & UX: CLI/UX messages, error clarity, usability of examples.

## Practical workflow guidance

- If you add dependencies, update `environment.yaml` (or `requirements.txt`) and include the exact `conda`/`pip` commands in `README.md`.
- When adding tests, include the runnable test command in `README.md` and keep tests small and deterministic.
- Keep commits focused and include environment + README updates in the same PR when relevant.
- Avoid large speculative refactors — prefer incremental, reviewable changes.

## Key files to anchor decisions

-`README.md` — must always show how to run, test, and reproduce the environment for any new code.

-`.gitignore` — indicates a Python-focused workflow; follow its signals.

-`environment.yaml` / `requirements.txt` — required whenever dependencies change; create if missing.
