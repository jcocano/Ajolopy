"""Shared fixtures for the AJ-60 @MCPServer test suite.

Most tests speak directly to the framework runtime so they do not need
to drive the optional ``mcp`` SDK through stdio. The few tests that do
exercise the real SDK (the CLI smoke test, the dependency-surface test)
construct fake stdin pipes via :mod:`tests.mcp_server.fakes`.
"""
