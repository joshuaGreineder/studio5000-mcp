"""Safety (GuardLogix) MCP tools.

Covers the SDK's safety surface:

* read state          — ``is_safety_locked``, ``get_safety_signature``,
                        ``get_safety_network_number``;
* safety lock/unlock  — ``safety_lock``, ``safety_unlock`` and the matching
                        password setters;
* signature lifecycle — ``generate_safety_signature``,
                        ``delete_safety_signature``.

The signature generate / delete tools require the project to be online with
the controller (see ``generate_delete_get_safety_signature.py`` in the SDK
Examples folder), so they internally run
``set_communications_path → download → go_online`` before issuing the
signature mutation. All mutating tools are gated by ``confirm=True``.
"""
from __future__ import annotations

from logix_mcp._common import (
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_comm_path,
    preflight_confirm,
    preflight_project_path,
)


# ---------------------------------------------------------------------------
# Read-only inspection tools (no confirm gate).
# ---------------------------------------------------------------------------


@mcp.tool()
async def is_safety_locked(path: str) -> str:
    """Return whether the safety task in the project is currently locked."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            locked = await proj.is_safety_locked()
        return f"[OK] is_safety_locked: {bool(locked)}"

    return await _run("is_safety_locked", _do, path=str(p))


@mcp.tool()
async def get_safety_signature(path: str) -> str:
    """Return the project's current safety signature (or empty if none)."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            sig = await proj.get_safety_signature()
        return f"[OK] get_safety_signature: {sig}"

    return await _run("get_safety_signature", _do, path=str(p))


@mcp.tool()
async def get_safety_network_number(path: str, module_name: str = "Local") -> str:
    """Return the safety network number of ``module_name`` (default ``Local``)."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            snn = await proj.get_safety_network_number(module_name)
        return f"[OK] get_safety_network_number({module_name}): {snn}"

    return await _run(
        "get_safety_network_number", _do, path=str(p), module_name=module_name
    )


# ---------------------------------------------------------------------------
# Safety lock / unlock + password mutations (confirm-gated, offline only).
# ---------------------------------------------------------------------------


@mcp.tool()
async def safety_lock(path: str, password: str, confirm: bool = False) -> str:
    """Apply a safety lock to the project using ``password``."""
    pf = preflight_confirm(confirm, "safety_lock the project")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.safety_lock(password)
            await proj.save()
        return "[OK] safety_lock"

    return await _run("safety_lock", _do, path=str(p))


@mcp.tool()
async def safety_unlock(path: str, password: str, confirm: bool = False) -> str:
    """Remove the project's safety lock using ``password``."""
    pf = preflight_confirm(confirm, "safety_unlock the project")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.safety_unlock(password)
            await proj.save()
        return "[OK] safety_unlock"

    return await _run("safety_unlock", _do, path=str(p))


@mcp.tool()
async def set_safety_lock_password(
    path: str,
    new_password: str,
    old_password: str = "",
    confirm: bool = False,
) -> str:
    """Set / change / erase the safety **lock** password.

    Pass ``new_password=""`` to erase the lock password (matches the SDK
    example ``ERASE_SAFETY_LOCK_PASSWORD`` flow in ``safety_lock_unlock.py``).
    """
    pf = preflight_confirm(confirm, "set_safety_lock_password")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_safety_lock_password(new_password, old_password)
            await proj.save()
        action = "erased" if not new_password else "updated"
        return f"[OK] set_safety_lock_password: password {action}"

    return await _run("set_safety_lock_password", _do, path=str(p))


@mcp.tool()
async def set_safety_unlock_password(
    path: str,
    new_password: str,
    old_password: str = "",
    confirm: bool = False,
) -> str:
    """Set / change / erase the safety **unlock** password.

    Pass ``new_password=""`` to erase the unlock password.
    """
    pf = preflight_confirm(confirm, "set_safety_unlock_password")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_safety_unlock_password(new_password, old_password)
            await proj.save()
        action = "erased" if not new_password else "updated"
        return f"[OK] set_safety_unlock_password: password {action}"

    return await _run("set_safety_unlock_password", _do, path=str(p))


# ---------------------------------------------------------------------------
# Safety signature lifecycle (online; confirm-gated).
# ---------------------------------------------------------------------------


@mcp.tool()
async def generate_safety_signature(
    path: str, comm_path: str, confirm: bool = False
) -> str:
    """Generate a fresh safety signature on the (online) controller.

    Mirrors ``generate_delete_get_safety_signature.py``: opens the project,
    sets the comm path, downloads, goes online, then asks the controller to
    generate a signature, and finally saves the project so the new signature
    is persisted.
    """
    pf = preflight_confirm(
        confirm, "generate_safety_signature on the controller"
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_comm_path(comm_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_communications_path(comm_path)
            await proj.download()
            await proj.go_online()
            await proj.generate_safety_signature()
            await proj.save()
        return "[OK] generate_safety_signature"

    return await _run(
        "generate_safety_signature", _do, path=str(p), comm_path=comm_path
    )


@mcp.tool()
async def delete_safety_signature(
    path: str, comm_path: str, confirm: bool = False
) -> str:
    """Delete the safety signature from the (online) controller.

    Same online sequence as ``generate_safety_signature`` but issues
    ``delete_safety_signature`` instead.
    """
    pf = preflight_confirm(
        confirm, "delete_safety_signature on the controller"
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_comm_path(comm_path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_communications_path(comm_path)
            await proj.download()
            await proj.go_online()
            await proj.delete_safety_signature()
            await proj.save()
        return "[OK] delete_safety_signature"

    return await _run(
        "delete_safety_signature", _do, path=str(p), comm_path=comm_path
    )
