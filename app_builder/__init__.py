"""
Modern app-builder core.
"""

from .config import load_config
from .schema import AppBuilderConfig

__all__ = ["AppBuilderConfig", "load_config"]
__version__ = "1.2.0"
