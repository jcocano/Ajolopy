"""Ajolopy — the Python framework for building AI-native applications in production."""

from . import providers as _providers  # noqa: F401  # pyright: ignore[reportUnusedImport]
from .agent import Agent, Tool
from .di import Injectable
from .eval import Eval, Metric
from .factory import AjolopyApp, AjolopyFactory, run
from .guards import UseGuards
from .mcp import MCP
from .mcp_server import MCPServer
from .modules import Module, compile_module, forwardRef
from .observability import get_logger
from .routes import Controller, Delete, Get, Patch, Post, Put
from .stream import Stream
from .workflow import Workflow

__version__ = "0.1.7"

__all__ = [
    "MCP",
    "Agent",
    "AjolopyApp",
    "AjolopyFactory",
    "Controller",
    "Delete",
    "Eval",
    "Get",
    "Injectable",
    "MCPServer",
    "Metric",
    "Module",
    "Patch",
    "Post",
    "Put",
    "Stream",
    "Tool",
    "UseGuards",
    "Workflow",
    "__version__",
    "compile_module",
    "forwardRef",
    "get_logger",
    "run",
]
