"""Shared fixtures for the AJ-7 @MCP test suite.

The autouse :func:`reset_mcp_registry_autouse` fixture and the
:func:`patch_client_builder` fixture live in the repo-wide
``tests/conftest.py`` so the agent + workflow cross-cut tests can use
them too. This module currently has no MCP-specific fixtures beyond
what the root conftest already provides.
"""
