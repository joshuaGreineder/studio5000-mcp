# Troubleshooting

## Python / dependency issues

### `ModuleNotFoundError: logix_designer_sdk`
- Ensure Python 3.12.x is used.
- Run `install.bat` from repo root.

### `py -3.12` not found
- Install Python 3.12 and ensure launcher is available.

## SDK/Logix issues

### `Required Logix Designer version ... is not installed`
- Install that major revision in Studio 5000.

### `RxE_DATA_TOO_NEW`
- Project was saved by a newer Logix Designer revision.

### `XMLSrv_E_IMPORT_ABORTED_NO_CHANGES`
- L5X fragment rejected. Export a known-good target from destination project and compare structure.

### `XMLSrv_E_INCOMPATIBLE_IMPORT_TARGET`
- `x_path` target type does not match fragment root node.

### `XMLSrv_E_TARGET_NOT_FOUND`
- Target object/path does not exist yet in destination project.

## Online operation issues

### `CONFIRM_REQUIRED`
- Pass `confirm=true` for controller-mutating tools.

### Communication path failures
- Use RSWho format, e.g. `AB_ETH-1\\10.88.45.25\\Backplane\\0`.

### File locked / permission denied
- Close Studio 5000 file handles and verify write permissions.
