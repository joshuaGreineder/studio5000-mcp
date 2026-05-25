# Development Guide

## Project layout

- `l5x_acd_server.py` - compatibility shim entrypoint
- `logix_mcp/server.py` - MCP runtime entrypoint + eager tool imports
- `logix_mcp/_common.py` - shared runtime, errors, preflights
- `logix_mcp/_xml.py` - L5X parsing/formatting helpers
- `logix_mcp/tools/` - tool modules grouped by capability

## Tool authoring pattern

Use this template:

```python
@mcp.tool()
async def my_tool(...):
    pf = preflight_project_path(path)
    if pf:
        return pf

    async def _do() -> str:
        async with _opened(_resolve(path)) as proj:
            ...
        return "[OK] ..."

    return await _run("my_tool", _do, path=path)
```

## Error model

- Success: `[OK] ...`
- Failure: `_run(...)` converts exceptions to structured `[FAIL]` blocks.
- Add token-to-hint mappings in `_hint_for(...)` for new Rockwell error families.

## Release checklist

- Update `README.md` and `CHANGELOG.md`.
- Verify tools/resources list:
  - `mcp.list_tools()`
  - `mcp.list_resources()`
- Sanity boot:
  - `py -3.12 l5x_acd_server.py`
