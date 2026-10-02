# Agent Instructions & Standard Rules

These instructions and rules apply to all AI coding agents working within this repository.

## 1. Documentation & Usage Updates
If usage changes—including command-line options, environment variables, configuration settings, or MCP capabilities/tools:
- Review the design and reference documents under [`./docs`](./docs) (such as software requirements, system design, and verification plans) as well as [`README.md`](./README.md).
- Update and add all relevant details, parameters, descriptions, and examples to keep documentation in sync with codebase behavior.

## 2. Code Quality & Linting Gate
- Do not commit or finalize code that does not pass the Ruff lint and formatting checks.
- Always run and verify:
  ```bash
  uv run ruff check .
  uv run ruff format --check .
  ```
  Ensure all issues are resolved and all checks pass prior to committing or concluding changes.

## 3. Implementation Plans & Walkthroughs as Editor Artifacts
- Always generate implementation plans (`task.md` / `implementation_plan.md`) and walkthroughs (`walkthrough.md`) as user-facing Artifacts in the artifact directory (`write_to_file` to `<appDataDir>/brain/<conversation-id>/...` with `ArtifactMetadata: {UserFacing: true, RequestFeedback: true}`).
- Do not output lengthy implementation plans or walkthroughs inline within chat messages. Present them as clickable, editable editor artifacts in the IDE and provide only a concise summary and clickable markdown link in the chat response.


