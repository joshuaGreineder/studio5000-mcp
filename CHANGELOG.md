# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added
- Modular server package (`logix_mcp/`) with area-based tool modules.
- Full SDK-facing MCP tool surface for project I/O, build, tags, program queries,
  partial import/export, online ops, safety, SD card, and gated protection APIs.
- Creation helpers: `create_udt`, `create_tag`, `create_program`, `add_io_module`.
- Discovery helpers: `get_processor_types`, `list_options`, `logix://sdk/info`.

### Changed
- Replaced monolithic server file with `l5x_acd_server.py` shim that forwards to `logix_mcp.server.main()`.
- Standardized error output to structured `[FAIL]` blocks.
- Improved hint mapping for XML import error tokens.
- Tightened XPath preflight validation.

### Fixed
- Corrected `get_processor_types` parsing to iterate SDK `ProcessorType` values (not dict keys).
- Added safer software revision handling for generated UDT fragments.
