"""Compat: subprocess MCP (python -m services.gemini_mcp). Codigo em thina.llm.gemini_mcp."""

from __future__ import annotations

import logging

from thina.llm.gemini_mcp import *  # noqa: F403
from thina.llm.gemini_mcp import mcp

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    mcp.run()
