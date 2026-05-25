"""SD card MCP tools.

Mirrors the SDK Examples folder for SD-card workflows:

* ``store_image_on_sd_card.py``       — basic + advanced (load event / load
                                        mode / AFU / image name + note);
* ``load_image_from_sd_card.py``      — load the stored image back into the
                                        controller;
* ``create_deployment_sd_card.py``    — single-card "factory" variant
                                        wrapped here as ``deploy_to_sd_card``.

All three are destructive (they download program + firmware to the
controller and/or write the SD card), so they are confirm-gated and open the
project with ``MCPEventLogger()`` so the SDK's status / progress callbacks
stream up to the MCP host instead of vanishing into a silent multi-minute
wait.
"""
from __future__ import annotations

from logix_designer_sdk import (
    AutomaticFirmwareUpdate,
    LogixProject,
    RequestedControllerMode,
    RequestedLoadEvent,
    RequestedLoadMode,
)

from logix_mcp._common import (
    MCPEventLogger,
    _resolve,
    _run,
    mcp,
    preflight_comm_path,
    preflight_confirm,
    preflight_project_path,
)


# SDK length limits (see ``store_image_on_sd_card.py`` arg docs).
_IMAGE_NAME_MAX = 40
_IMAGE_NOTE_MAX = 87


_LOAD_EVENT_MAP = {
    "on_demand_only": RequestedLoadEvent.ON_DEMAND_ONLY,
    "on_corrupt_ram": RequestedLoadEvent.ON_CORRUPT_RAM,
    "on_power_up": RequestedLoadEvent.ON_POWER_UP,
}

_LOAD_MODE_MAP = {
    "run": RequestedLoadMode.RUN,
    "program": RequestedLoadMode.PROGRAM,
}

_AFU_MAP = {
    "enabled": AutomaticFirmwareUpdate.ENABLED,
    "disabled": AutomaticFirmwareUpdate.DISABLED,
}


@mcp.tool()
async def store_image_on_sd_card(
    path: str,
    comm_path: str,
    load_event: str = "",
    load_mode: str = "",
    afu: str = "",
    image_name: str = "",
    image_note: str = "",
    confirm: bool = False,
) -> str:
    """Download the project and store the running image on the controller's SD card.

    Mirrors ``store_image_on_sd_card.py``: opens the project, sets the comm
    path, downloads, moves the controller to PROGRAM mode, then calls
    ``store_image_on_sd_card`` either with no arguments (basic mode) or with
    the advanced 5-tuple ``(load_event, load_mode, afu, image_name,
    image_note)`` when *any* of the advanced parameters is provided.

    Advanced parameter strings (case-insensitive):

      * ``load_event``: ``on_demand_only`` | ``on_corrupt_ram`` | ``on_power_up``
      * ``load_mode`` : ``run`` | ``program``
      * ``afu``       : ``enabled`` | ``disabled``

    ``image_name`` is capped at 40 characters and ``image_note`` at 87 (SDK
    enforced — we pre-check so callers see a clean ``INVALID_INPUT`` rather
    than a generic SDK rejection).
    """
    pf = preflight_confirm(
        confirm,
        "download the project and store an image on the controller's SD card",
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

    advanced_requested = any([load_event, load_mode, afu, image_name, image_note])

    async def _do() -> str:
        if advanced_requested:
            if not load_event or not load_mode or not afu:
                raise ValueError(
                    "load_event, load_mode and afu are all required for the "
                    "advanced store_image_on_sd_card form"
                )
            event_key = load_event.strip().lower()
            mode_key = load_mode.strip().lower()
            afu_key = afu.strip().lower()
            if event_key not in _LOAD_EVENT_MAP:
                raise ValueError(
                    f"load_event {load_event!r} not in "
                    f"{sorted(_LOAD_EVENT_MAP)}"
                )
            if mode_key not in _LOAD_MODE_MAP:
                raise ValueError(
                    f"load_mode {load_mode!r} not in {sorted(_LOAD_MODE_MAP)}"
                )
            if afu_key not in _AFU_MAP:
                raise ValueError(
                    f"afu {afu!r} not in {sorted(_AFU_MAP)}"
                )
            if len(image_name) > _IMAGE_NAME_MAX:
                raise ValueError(
                    f"image_name longer than {_IMAGE_NAME_MAX} chars "
                    f"(got {len(image_name)})"
                )
            if len(image_note) > _IMAGE_NOTE_MAX:
                raise ValueError(
                    f"image_note longer than {_IMAGE_NOTE_MAX} chars "
                    f"(got {len(image_note)})"
                )
            event_enum = _LOAD_EVENT_MAP[event_key]
            mode_enum = _LOAD_MODE_MAP[mode_key]
            afu_enum = _AFU_MAP[afu_key]
        else:
            event_enum = mode_enum = afu_enum = None

        proj = await LogixProject.open_logix_project(str(p), MCPEventLogger())
        try:
            await proj.set_communications_path(comm_path)
            await proj.download()
            await proj.change_controller_mode(RequestedControllerMode.PROGRAM)
            if advanced_requested:
                await proj.store_image_on_sd_card(
                    event_enum, mode_enum, afu_enum, image_name, image_note
                )
            else:
                await proj.store_image_on_sd_card()
        finally:
            proj.close()

        if advanced_requested:
            return (
                "[OK] store_image_on_sd_card (advanced) "
                f"event={load_event} mode={load_mode} afu={afu} "
                f"name={image_name!r} note_len={len(image_note)}"
            )
        return "[OK] store_image_on_sd_card (basic)"

    return await _run(
        "store_image_on_sd_card",
        _do,
        path=str(p),
        comm_path=comm_path,
        advanced=advanced_requested,
    )


@mcp.tool()
async def load_image_from_sd_card(
    path: str, comm_path: str, confirm: bool = False
) -> str:
    """Load the previously-stored SD-card image into the controller.

    Mirrors ``load_image_from_sd_card.py``: open project + set comm path +
    download + change to PROGRAM mode + ``load_image_from_sd_card``.
    """
    pf = preflight_confirm(
        confirm, "load the SD-card image into the controller"
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
            await proj.download()
            await proj.change_controller_mode(RequestedControllerMode.PROGRAM)
            await proj.load_image_from_sd_card()
        finally:
            proj.close()
        return "[OK] load_image_from_sd_card"

    return await _run(
        "load_image_from_sd_card", _do, path=str(p), comm_path=comm_path
    )


@mcp.tool()
async def deploy_to_sd_card(
    path: str, comm_path: str, confirm: bool = False
) -> str:
    """Convenience: download the project to the controller, then SD-card it.

    Single-card variant of ``create_deployment_sd_card.py``: open project,
    set comm path, switch to PROGRAM mode, download, store image. Useful for
    provisioning a single controller in one call instead of chaining
    ``download_project`` + ``store_image_on_sd_card``.
    """
    pf = preflight_confirm(
        confirm,
        "download the project to the controller and store the image on its SD card",
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
            await proj.change_controller_mode(RequestedControllerMode.PROGRAM)
            await proj.download()
            await proj.store_image_on_sd_card()
        finally:
            proj.close()
        return "[OK] deploy_to_sd_card"

    return await _run(
        "deploy_to_sd_card", _do, path=str(p), comm_path=comm_path
    )
