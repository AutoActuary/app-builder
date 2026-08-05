"""
Modern app-builder core.
"""

from .config import load_config
from .schema import AppBuilderConfig
from .versioning import resolve_app_builder_version

__all__ = ["AppBuilderConfig", "load_config"]
__version__ = resolve_app_builder_version()
