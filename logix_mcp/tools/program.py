"""Program-structure tools: ``list_routines``, ``search_rungs``, ``get_all_executables`` (gated)."""
from __future__ import annotations

from logix_mcp._common import (
    _gated_tool_response,
    _has_method,
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_project_path,
)
from logix_mcp._xml import (
    _fmt_table,
    _l5x_tree_for_path,
    _routine_rows,
    _search_rungs,
)


@mcp.tool()
async def list_routines(path: str) -> str:
    """List Programs / Routines / rung counts via a temp detailed L5X export."""
    pf = preflight_project_path(path)
    if pf:
        return pf

    async def _do() -> str:
        p = _resolve(path)
        tree = await _l5x_tree_for_path(p)
        rows = _routine_rows(tree.getroot())
        str_rows: list[tuple[str, str, str, str]] = [
            (prog, name, rtype, str(rcount)) for prog, name, rtype, rcount in rows
        ]
        table = _fmt_table(
            str_rows, ("Program", "Routine", "Type", "RungCount")
        )
        return f"[OK] Routines for {p}:\n{table}"

    return await _run("list_routines", _do, path=path)


@mcp.tool()
async def search_rungs(path: str, text: str) -> str:
    """Search rung text + comments for ``text`` (case-insensitive) via temp L5X."""
    pf = preflight_project_path(path)
    if pf:
        return pf

    async def _do() -> str:
        if not text or not text.strip():
            raise ValueError("text is empty; provide a search needle")
        p = _resolve(path)
        tree = await _l5x_tree_for_path(p)
        hits = _search_rungs(tree.getroot(), text)
        if not hits:
            return f"[OK] No rungs matched {text!r} in {p}"
        body = "\n".join(hits[:500])
        more = "" if len(hits) <= 500 else f"\n... ({len(hits) - 500} more hits omitted)"
        return f"[OK] {len(hits)} hit(s) for {text!r} in {p}:\n{body}{more}"

    return await _run("search_rungs", _do, path=path, text=text)


@mcp.tool()
async def get_all_executables(path: str) -> str:
    """List every executable element (programs, routines, AOIs) — SDK-gated; needs a newer ``logix_designer_sdk``."""
    if not _has_method("get_all_executables"):
        return _gated_tool_response("get_all_executables")
    pf = preflight_project_path(path)
    if pf:
        return pf

    async def _do() -> str:
        p = _resolve(path)
        async with _opened(p) as proj:
            items = await proj.get_all_executables()
        if not items:
            return f"[OK] get_all_executables({p}) returned 0 entries."
        lines = [f"{i+1:>4}. {item}" for i, item in enumerate(items)]
        return f"[OK] Executables in {p}:\n" + "\n".join(lines)

    return await _run("get_all_executables", _do, path=path)


__all__ = ["list_routines", "search_rungs", "get_all_executables"]
