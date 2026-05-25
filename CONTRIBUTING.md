# Contributing

Thanks for contributing.

## Local setup

1. Install Studio 5000 Logix Designer (with SDK files present).
2. Use Python 3.12.x.
3. From repo root run:

```bat
install.bat
```

## Development workflow

- Main server entrypoint is `l5x_acd_server.py` (shim).
- Real implementation lives in `logix_mcp/`.
- Add tools in `logix_mcp/tools/*.py` and register with `@mcp.tool()` from `logix_mcp._common import mcp`.
- Use shared helpers from `_common.py`:
  - `_run(...)` for consistent `[FAIL]` blocks
  - `preflight_*` for validation
  - `_opened(...)` for safe project open/close

## Code style

- Keep changes small and explicit.
- Prefer clear docstrings for all MCP tools (these become model-visible descriptions).
- Return `[OK] ...` on success and rely on `_run(...)` for structured failures.

## Manual validation checklist

- `py -3.12 -c "import logix_mcp.server; print('imports ok')"`
- `py -3.12 -c "import asyncio; import logix_mcp.server; from logix_mcp._common import mcp; print(len(asyncio.run(mcp.list_tools())))"`
- `py -3.12 l5x_acd_server.py` (ensure startup, no traceback)

Do not run destructive online operations against production controllers during tests.
