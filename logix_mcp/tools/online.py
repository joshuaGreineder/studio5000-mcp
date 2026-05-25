"""Live-controller MCP tools (set/get comm path, go online/offline, controller
mode, upload, download, etc.).

Every mutating call here either modifies the project file on disk or pokes the
attached controller over EtherNet/IP, so each one is gated by ``confirm=True``
to make accidental destructive operations impossible for Claude / Cursor.
Read-only inspection tools (``get_communications_path``,
``read_connected_state``, ``read_controller_mode``) do not require ``confirm``.

The long-running operations (``upload_project``, ``upload_to_new_project``,
``download_project``) bypass the shared ``_opened`` context manager because
they need to pass an ``MCPEventLogger()`` instance into
``LogixProject.open_logix_project`` so SDK progress events stream up to the
MCP host instead of going silent for minutes at a time. They still wrap the
real work in ``_run`` so the layered error handler classifies any SDK
exception consistently.
"""
from __future__ import annotations

from logix_designer_sdk import (
    ControllerMode,
    LogixProject,
    RequestedControllerMode,
)

from logix_mcp._common import (
    MCPEventLogger,
    _fmt_err,
    _opened,
    _resolve,
    _run,
    mcp,
    preflight_comm_path,
    preflight_confirm,
    preflight_controller_mode,
    preflight_output_path,
    preflight_project_path,
)


# Map our public string mode names to the SDK's RequestedControllerMode enum.
# preflight_controller_mode already guarantees the input is one of these keys.
_REQUESTED_MODE_MAP = {
    "program": RequestedControllerMode.PROGRAM,
    "run": RequestedControllerMode.RUN,
    "test": RequestedControllerMode.TEST,
}


# ---------------------------------------------------------------------------
# Read-only inspection tools (no confirm gate).
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_communications_path(path: str) -> str:
    """Return the project's currently-configured communications path."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            comm = await proj.get_communications_path()
        return f"[OK] get_communications_path: {comm}"

    return await _run("get_communications_path", _do, path=str(p))


@mcp.tool()
async def read_connected_state(path: str, comm_path: str = "") -> str:
    """Return the controller's connected state (``ONLINE`` / ``OFFLINE`` / ...).

    If ``comm_path`` is provided, the project's comm path is updated first so
    the read targets the requested controller.
    """
    pf = preflight_project_path(path)
    if pf:
        return pf
    if comm_path:
        pf = preflight_comm_path(comm_path)
        if pf:
            return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            if comm_path:
                await proj.set_communications_path(comm_path)
            state = await proj.read_connected_state()
        return f"[OK] read_connected_state: {state.name}"

    return await _run(
        "read_connected_state", _do, path=str(p), comm_path=comm_path or "(unset)"
    )


@mcp.tool()
async def read_controller_mode(path: str, comm_path: str) -> str:
    """Return the controller's current mode (``PROGRAM`` / ``RUN`` / ``TEST`` / ...)."""
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
            mode = await proj.read_controller_mode()
        return f"[OK] read_controller_mode: {mode.name}"

    return await _run(
        "read_controller_mode", _do, path=str(p), comm_path=comm_path
    )


# ---------------------------------------------------------------------------
# Project-file mutating tools (preserved behavior + confirm where appropriate).
# ---------------------------------------------------------------------------


@mcp.tool()
async def set_communications_path(
    path: str, comm_path: str, output: str = ""
) -> str:
    """Set the project's communications path and save (in-place or to ``output``)."""
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_comm_path(comm_path)
    if pf:
        return pf
    if output:
        pf = preflight_output_path(output, {".ACD", ".L5X", ".L5K"})
        if pf:
            return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_communications_path(comm_path)
            if output:
                await proj.save_as(str(_resolve(output)), True)
            else:
                await proj.save()
        target = output or str(p)
        return f"[OK] set_communications_path: comm_path={comm_path} saved={target}"

    return await _run(
        "set_communications_path",
        _do,
        path=str(p),
        comm_path=comm_path,
        output=output or "(in-place)",
    )


@mcp.tool()
async def change_controller_type(
    path: str, processor_type: str, output: str, confirm: bool = False
) -> str:
    """Morph the project to ``processor_type`` and save_as the result to ``output``.

    Discover valid ``processor_type`` values by calling
    ``get_processor_types(major_revision=<rev>)`` first; pass the ``Name``
    column verbatim. Note that not every morph is allowed by Logix Designer
    (e.g. ICE2 -> ICE1 is rejected with ``RxCsE_MORPH_TO_THIS_CONTROLLER_NOT_SUPPORTED``).

    This mutates the on-disk project (writes a new ACD), so it is confirm-gated.
    """
    pf = preflight_confirm(
        confirm,
        f"change_controller_type to {processor_type!r} and save_as {output!r}",
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_output_path(output, {".ACD"})
    if pf:
        return pf
    p = _resolve(path)
    out = _resolve(output)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.change_controller_type(processor_type)
            await proj.save_as(str(out), True)
        return (
            f"[OK] change_controller_type: {p} -> {out} "
            f"(processor_type={processor_type})"
        )

    return await _run(
        "change_controller_type",
        _do,
        path=str(p),
        output=str(out),
        processor_type=processor_type,
    )


# ---------------------------------------------------------------------------
# Live controller mutations (all confirm-gated).
# ---------------------------------------------------------------------------


@mcp.tool()
async def go_online(path: str, comm_path: str, confirm: bool = False) -> str:
    """Set comm path and bring the project online with the controller."""
    pf = preflight_confirm(confirm, "go_online with the attached controller")
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
            await proj.go_online()
            state = await proj.read_connected_state()
        return f"[OK] go_online: connected_state={state.name}"

    return await _run("go_online", _do, path=str(p), comm_path=comm_path)


@mcp.tool()
async def go_offline(path: str, confirm: bool = False) -> str:
    """Take the project offline from the attached controller."""
    pf = preflight_confirm(confirm, "go_offline from the attached controller")
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    p = _resolve(path)

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.go_offline()
        return "[OK] go_offline"

    return await _run("go_offline", _do, path=str(p))


@mcp.tool()
async def change_controller_mode(
    path: str, comm_path: str, mode: str, confirm: bool = False
) -> str:
    """Change the controller's mode to ``program`` / ``run`` / ``test``."""
    pf = preflight_confirm(
        confirm, f"change_controller_mode to {mode!r}"
    )
    if pf:
        return pf
    pf = preflight_project_path(path)
    if pf:
        return pf
    pf = preflight_comm_path(comm_path)
    if pf:
        return pf
    pf = preflight_controller_mode(mode)
    if pf:
        return pf
    p = _resolve(path)
    requested = _REQUESTED_MODE_MAP[mode.strip().lower()]

    async def _do() -> str:
        async with _opened(p) as proj:
            await proj.set_communications_path(comm_path)
            await proj.change_controller_mode(requested)
        return f"[OK] change_controller_mode: requested={mode.lower()}"

    return await _run(
        "change_controller_mode",
        _do,
        path=str(p),
        comm_path=comm_path,
        mode=mode,
    )


@mcp.tool()
async def upload_project(
    path: str, comm_path: str, confirm: bool = False
) -> str:
    """Upload the running controller's program into the project and save.

    Opens with ``MCPEventLogger()`` so SDK progress streams up to the MCP host
    rather than appearing as a silent multi-minute hang on large ACDs.
    """
    pf = preflight_confirm(
        confirm, "upload the controller's program into the local project and save it"
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
        proj = await LogixProject.open_logix_project(str(p), MCPEventLogger())
        try:
            await proj.set_communications_path(comm_path)
            await proj.upload()
            await proj.save()
        finally:
            proj.close()
        return f"[OK] upload_project: {p} (saved)"

    return await _run("upload_project", _do, path=str(p), comm_path=comm_path)


@mcp.tool()
async def upload_to_new_project(
    new_path: str, comm_path: str, confirm: bool = False
) -> str:
    """Upload the controller's program into a brand-new ACD at ``new_path``."""
    pf = preflight_confirm(
        confirm, f"upload to a new project file at {new_path!r}"
    )
    if pf:
        return pf
    pf = preflight_output_path(new_path, {".ACD"})
    if pf:
        return pf
    pf = preflight_comm_path(comm_path)
    if pf:
        return pf
    out = _resolve(new_path)

    async def _do() -> str:
        await LogixProject.upload_to_new_project(
            str(out), comm_path, MCPEventLogger()
        )
        return f"[OK] upload_to_new_project: {out}"

    return await _run(
        "upload_to_new_project",
        _do,
        new_path=str(out),
        comm_path=comm_path,
    )


@mcp.tool()
async def download_project(
    path: str,
    comm_path: str,
    ensure_program_mode: bool = True,
    confirm: bool = False,
) -> str:
    """Download the project into the controller (must be in PROGRAM mode).

    When ``ensure_program_mode=True`` (default) this tool reads the current
    controller mode first and refuses the download if the controller isn't in
    Program — matching the safety check in
    ``download_project.py`` from the SDK Examples folder. Pass
    ``ensure_program_mode=False`` to bypass the check (the SDK itself will
    still reject the download if the controller is in Run/Test).
    """
    pf = preflight_confirm(
        confirm,
        "download the local project into the controller (overwrites running program)",
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
        proj = await LogixProject.open_logix_project(str(p), MCPEventLogger())
        try:
            await proj.set_communications_path(comm_path)
            if ensure_program_mode:
                mode = await proj.read_controller_mode()
                if mode != ControllerMode.PROGRAM:
                    return _fmt_err(
                        "download_project",
                        ValueError(
                            f"controller mode is {mode.name}; expected PROGRAM"
                        ),
                        "CONTROLLER_MODE_WRONG",
                        "Run change_controller_mode(mode='program') first, or "
                        "pass ensure_program_mode=false to bypass.",
                        path=str(p),
                        comm_path=comm_path,
                        mode=mode.name,
                    )
            await proj.download()
            await proj.save()
        finally:
            proj.close()
        return f"[OK] download_project: {p} -> controller"

    return await _run(
        "download_project",
        _do,
        path=str(p),
        comm_path=comm_path,
        ensure_program_mode=ensure_program_mode,
    )
