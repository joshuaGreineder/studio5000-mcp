"""Routine / AOI protection MCP tools.

Every tool here calls a ``LogixProject`` method that ships in **newer** Logix
Designer SDK wheels but is **absent in 2.0.1** (the version currently pinned
by this repo). Each body is therefore gated with ``_has_method`` and returns
the friendly ``_gated_tool_response`` message when the underlying method
isn't installed, so the tool surface stays announceable in MCP catalogs and
will light up automatically the moment a user upgrades their SDK wheel — no
code change required.

Per the Rockwell ``ContentProtection`` docs, the lock/unlock/protect/unprotect
methods accept either a single XPath string or a list of them. The MCP
interface keeps the single-string form (``x_path: str``) since list arguments
are awkward to type by hand from Claude / Cursor; callers can loop the tool
to operate on multiple components.
"""
from __future__ import annotations

from logix_mcp._common import (
    _gated_tool_response,
    _has_method,
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_confirm,
    preflight_project_path,
    preflight_xpath,
)


# ---------------------------------------------------------------------------
# Single-component read-only checks (no confirm gate).
# ---------------------------------------------------------------------------


@mcp.tool()
async def is_executable_locked(path: str, x_path: str) -> str:
    """Return whether the routine/AOI at ``x_path`` is currently locked."""
    if not _has_method("is_executable_locked"):
        return _gated_tool_response("is_executable_locked")
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            locked = await proj.is_executable_locked(x_path)
        return f"[OK] is_executable_locked: {bool(locked)}"

    return await _run("is_executable_locked", _do, path=str(p), x_path=x_path)


@mcp.tool()
async def is_executable_protected(path: str, x_path: str) -> str:
    """Return whether the routine/AOI at ``x_path`` is currently protected."""
    if not _has_method("is_executable_protected"):
        return _gated_tool_response("is_executable_protected")
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            protected = await proj.is_executable_protected(x_path)
        return f"[OK] is_executable_protected: {bool(protected)}"

    return await _run("is_executable_protected", _do, path=str(p), x_path=x_path)


# ---------------------------------------------------------------------------
# Single-component mutations (confirm-gated).
# ---------------------------------------------------------------------------


@mcp.tool()
async def lock_executable(path: str, x_path: str, confirm: bool = False) -> str:
    """Lock the (already license-protected) routine/AOI at ``x_path``."""
    if not _has_method("lock_executable"):
        return _gated_tool_response("lock_executable")
    pf = preflight_confirm(confirm, f"lock_executable {x_path!r}")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.lock_executable(x_path)
            await proj.save()
        return f"[OK] lock_executable: {x_path}"

    return await _run("lock_executable", _do, path=str(p), x_path=x_path)


@mcp.tool()
async def unlock_executable(
    path: str, x_path: str, confirm: bool = False
) -> str:
    """Unlock the routine/AOI at ``x_path``."""
    if not _has_method("unlock_executable"):
        return _gated_tool_response("unlock_executable")
    pf = preflight_confirm(confirm, f"unlock_executable {x_path!r}")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.unlock_executable(x_path)
            await proj.save()
        return f"[OK] unlock_executable: {x_path}"

    return await _run("unlock_executable", _do, path=str(p), x_path=x_path)


@mcp.tool()
async def protect_with_password(
    path: str, x_path: str, password: str, confirm: bool = False
) -> str:
    """Protect the routine/AOI at ``x_path`` with ``password``."""
    if not _has_method("protect_with_password"):
        return _gated_tool_response("protect_with_password")
    pf = preflight_confirm(
        confirm, f"protect_with_password {x_path!r}"
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.protect_with_password(x_path, password)
            await proj.save()
        return f"[OK] protect_with_password: {x_path}"

    return await _run(
        "protect_with_password", _do, path=str(p), x_path=x_path
    )


@mcp.tool()
async def protect_with_license(
    path: str,
    x_path: str,
    firm_code: int,
    product_code: int,
    confirm: bool = False,
) -> str:
    """Protect the routine/AOI at ``x_path`` with a firm/product license."""
    if not _has_method("protect_with_license"):
        return _gated_tool_response("protect_with_license")
    pf = preflight_confirm(
        confirm,
        f"protect_with_license {x_path!r} firm={firm_code} product={product_code}",
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)
    fc = int(firm_code)
    pc = int(product_code)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.protect_with_license(x_path, fc, pc)
            await proj.save()
        return (
            f"[OK] protect_with_license: {x_path} "
            f"(firm_code={fc}, product_code={pc})"
        )

    return await _run(
        "protect_with_license",
        _do,
        path=str(p),
        x_path=x_path,
        firm_code=fc,
        product_code=pc,
    )


@mcp.tool()
async def unprotect(path: str, x_path: str, confirm: bool = False) -> str:
    """Remove protection from the routine/AOI at ``x_path``."""
    if not _has_method("unprotect"):
        return _gated_tool_response("unprotect")
    pf = preflight_confirm(confirm, f"unprotect {x_path!r}")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_xpath(x_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.unprotect(x_path)
            await proj.save()
        return f"[OK] unprotect: {x_path}"

    return await _run("unprotect", _do, path=str(p), x_path=x_path)


# ---------------------------------------------------------------------------
# Project-wide mutations (confirm-gated, no per-component XPath).
# ---------------------------------------------------------------------------


@mcp.tool()
async def lock_all(path: str, confirm: bool = False) -> str:
    """Lock every (license-protected) routine and AOI in the project."""
    if not _has_method("lock_all"):
        return _gated_tool_response("lock_all")
    pf = preflight_confirm(confirm, "lock_all routines and AOIs")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.lock_all()
            await proj.save()
        return "[OK] lock_all"

    return await _run("lock_all", _do, path=str(p))


@mcp.tool()
async def unprotect_all(path: str, confirm: bool = False) -> str:
    """Remove protection from every routine and AOI in the project."""
    if not _has_method("unprotect_all"):
        return _gated_tool_response("unprotect_all")
    pf = preflight_confirm(confirm, "unprotect_all routines and AOIs")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.unprotect_all()
            await proj.save()
        return "[OK] unprotect_all"

    return await _run("unprotect_all", _do, path=str(p))


@mcp.tool()
async def protect_all_with_password(
    path: str, password: str, confirm: bool = False
) -> str:
    """Protect every routine and AOI in the project with ``password``."""
    if not _has_method("protect_all_with_password"):
        return _gated_tool_response("protect_all_with_password")
    pf = preflight_confirm(
        confirm, "protect_all_with_password (every routine and AOI)"
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.protect_all_with_password(password)
            await proj.save()
        return "[OK] protect_all_with_password"

    return await _run("protect_all_with_password", _do, path=str(p))


@mcp.tool()
async def protect_all_with_license(
    path: str,
    firm_code: int,
    product_code: int,
    confirm: bool = False,
) -> str:
    """Protect every routine and AOI in the project with a firm/product license."""
    if not _has_method("protect_all_with_license"):
        return _gated_tool_response("protect_all_with_license")
    pf = preflight_confirm(
        confirm,
        f"protect_all_with_license firm={firm_code} product={product_code}",
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)
    fc = int(firm_code)
    pc = int(product_code)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.protect_all_with_license(fc, pc)
            await proj.save()
        return (
            f"[OK] protect_all_with_license "
            f"(firm_code={fc}, product_code={pc})"
        )

    return await _run(
        "protect_all_with_license",
        _do,
        path=str(p),
        firm_code=fc,
        product_code=pc,
    )
