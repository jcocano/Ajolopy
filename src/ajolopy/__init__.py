"""Ajolopy — the Python framework for building AI-native applications in production."""

from .agent import Agent, Tool
from .di import Injectable
from .factory import AjolopyApp, AjolopyFactory, run
from .modules import Module, compile_module, forwardRef
from .routes import Controller, Delete, Get, Patch, Post, Put
from .stream import Stream

__version__ = "0.0.1"

__all__ = [
    "Agent",
    "AjolopyApp",
    "AjolopyFactory",
    "Controller",
    "Delete",
    "Get",
    "Injectable",
    "Module",
    "Patch",
    "Post",
    "Put",
    "Stream",
    "Tool",
    "__version__",
    "compile_module",
    "forwardRef",
    "run",
]
