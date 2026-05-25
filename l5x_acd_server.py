"""Compatibility shim — real server lives in :mod:`logix_mcp.server`.

Existing Claude Desktop and Cursor MCP configs launch ``python l5x_acd_server.py``
directly; this file keeps that command working by deferring to
``logix_mcp.server.main()``.
"""
from __future__ import annotations

from logix_mcp.server import main

if __name__ == "__main__":
    main()
