"""Plugin architecture for custom strategy development.

Enables users to write custom strategies as Python modules that are
dynamically discovered, validated, and loaded at runtime. Follows the
Strategy pattern (Gamma et al. 1994) with hot-reload capability.

Architecture references
-----------------------
- Gamma, Helm, Johnson, Vlissides 1994, "Design Patterns" (GoF)
  — Strategy Pattern: define a family of algorithms (strategies),
  encapsulate each one, and make them interchangeable. The plugin
  system extends this with runtime discovery and loading.

- Fowler 2002, "Patterns of Enterprise Application Architecture"
  — Plugin pattern: locate and load modules at runtime via a registry
  that maps names to concrete implementations.

- Python importlib documentation
  — Dynamic module loading via importlib.import_module() and
  importlib.util.spec_from_file_location() for file-based plugins.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from dataclasses import dataclass
from pathlib import Path

from app.agents.front_office.strategy.base_strategy import BaseStrategy
from app.core.logging import get_logger

logger = get_logger("plugins.manager")

# Default plugin directory
_DEFAULT_PLUGIN_DIR = Path("plugins")


@dataclass
class PluginInfo:
    """Metadata about a loaded plugin."""

    name: str
    module_path: str
    strategy_class: str
    version: str
    author: str
    description: str
    active_regimes: list[str]
    is_loaded: bool = False
    error: str = ""


class PluginManager:
    """Discovers, validates, and manages custom strategy plugins.

    Plugin Discovery (Fowler 2002):
    1. Scan plugin directory for Python files.
    2. Each file must contain a class that extends BaseStrategy.
    3. Optional plugin_info() function for metadata.
    4. Validated plugins are registered and can be instantiated.

    Plugin File Format::

        # my_strategy.py
        from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal

        def plugin_info():
            return {
                "name": "my_custom_strategy",
                "version": "1.0.0",
                "author": "Your Name",
                "description": "My custom trading strategy",
            }

        class MyCustomStrategy(BaseStrategy):
            @property
            def name(self) -> str:
                return "my_custom"

            @property
            def active_regimes(self) -> list[str]:
                return ["BULL", "NEUTRAL"]

            def generate_signal(self, symbol, features, regime):
                # Your logic here
                ...
    """

    def __init__(self, plugin_dir: str | Path = _DEFAULT_PLUGIN_DIR) -> None:
        self.plugin_dir = Path(plugin_dir)
        self._plugins: dict[str, PluginInfo] = {}
        self._instances: dict[str, BaseStrategy] = {}

    def discover(self) -> list[PluginInfo]:
        """Scan plugin directory and discover valid strategy plugins.

        Fowler 2002 plugin discovery pattern:
        1. Enumerate .py files in plugin directory.
        2. Load each module dynamically.
        3. Find classes extending BaseStrategy.
        4. Extract metadata from plugin_info() if available.
        5. Validate and register.
        """
        if not self.plugin_dir.exists():
            logger.info("plugin_dir_not_found", path=str(self.plugin_dir))
            self.plugin_dir.mkdir(parents=True, exist_ok=True)
            self._create_example_plugin()
            return []

        discovered: list[PluginInfo] = []

        for py_file in sorted(self.plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue

            try:
                info = self._load_plugin_file(py_file)
                if info:
                    discovered.append(info)
                    self._plugins[info.name] = info
            except Exception as exc:
                logger.error("plugin_load_error", file=py_file.name, error=str(exc))
                discovered.append(PluginInfo(
                    name=py_file.stem,
                    module_path=str(py_file),
                    strategy_class="",
                    version="",
                    author="",
                    description="",
                    active_regimes=[],
                    is_loaded=False,
                    error=str(exc),
                ))

        logger.info("plugins_discovered", count=len(discovered))
        return discovered

    def _load_plugin_file(self, py_file: Path) -> PluginInfo | None:
        """Load a single plugin file and validate it.

        Gamma et al. 1994 Strategy Pattern validation:
        - Must contain at least one BaseStrategy subclass.
        - Must implement required abstract methods (name, active_regimes, generate_signal).
        """
        module_name = f"horizon_plugin_{py_file.stem}"

        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            return None

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        # Find BaseStrategy subclasses
        strategy_cls = None
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, BaseStrategy)
                and attr is not BaseStrategy
            ):
                strategy_cls = attr
                break

        if strategy_cls is None:
            logger.debug("no_strategy_class", file=py_file.name)
            del sys.modules[module_name]
            return None

        # Extract metadata
        meta = {}
        if hasattr(module, "plugin_info") and callable(module.plugin_info):
            meta = module.plugin_info()

        # Instantiate to validate (Gamma et al. 1994 — verify interface)
        try:
            instance = strategy_cls()
            strategy_name = instance.name
            regimes = instance.active_regimes
        except Exception as exc:
            del sys.modules[module_name]
            raise ValueError(f"Plugin instantiation failed: {exc}") from exc

        info = PluginInfo(
            name=meta.get("name", strategy_name),
            module_path=str(py_file),
            strategy_class=strategy_cls.__name__,
            version=meta.get("version", "0.0.0"),
            author=meta.get("author", "unknown"),
            description=meta.get("description", ""),
            active_regimes=regimes,
            is_loaded=True,
        )

        # Store instance
        self._instances[info.name] = instance

        logger.info(
            "plugin_loaded",
            name=info.name,
            cls=info.strategy_class,
            regimes=regimes,
            version=info.version,
        )

        return info

    def get_strategy(self, name: str) -> BaseStrategy | None:
        """Get an instantiated plugin strategy by name."""
        return self._instances.get(name)

    def list_plugins(self) -> list[PluginInfo]:
        """List all registered plugins."""
        return list(self._plugins.values())

    def get_all_strategies(self) -> dict[str, BaseStrategy]:
        """Get all loaded strategy instances."""
        return dict(self._instances)

    def reload_plugin(self, name: str) -> PluginInfo | None:
        """Hot-reload a specific plugin.

        Removes old module from sys.modules, re-loads from disk.
        Supports development workflow: edit → save → reload.
        """
        info = self._plugins.get(name)
        if not info:
            logger.warning("plugin_not_found", name=name)
            return None

        # Remove old module
        module_name = f"horizon_plugin_{Path(info.module_path).stem}"
        if module_name in sys.modules:
            del sys.modules[module_name]
        if name in self._instances:
            del self._instances[name]

        # Re-load
        try:
            new_info = self._load_plugin_file(Path(info.module_path))
            if new_info:
                self._plugins[name] = new_info
                logger.info("plugin_reloaded", name=name)
            return new_info
        except Exception as exc:
            logger.error("plugin_reload_error", name=name, error=str(exc))
            return None

    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        if name not in self._plugins:
            return False

        info = self._plugins[name]
        module_name = f"horizon_plugin_{Path(info.module_path).stem}"

        if module_name in sys.modules:
            del sys.modules[module_name]
        self._plugins.pop(name, None)
        self._instances.pop(name, None)

        logger.info("plugin_unloaded", name=name)
        return True

    def _create_example_plugin(self) -> None:
        """Create an example plugin file for users to reference."""
        example = self.plugin_dir / "_example_strategy.py"
        if example.exists():
            return

        example.write_text('''\
"""Example custom strategy plugin for Horizon Capital.

Copy this file, rename it, and implement your strategy logic.
The plugin system will automatically discover and load it.

Your strategy must:
1. Extend BaseStrategy
2. Implement name, active_regimes, and generate_signal
3. Optionally provide a plugin_info() function for metadata
"""

from app.agents.front_office.strategy.base_strategy import BaseStrategy, Signal


def plugin_info():
    """Optional metadata for the plugin manager."""
    return {
        "name": "example_strategy",
        "version": "1.0.0",
        "author": "Horizon Capital",
        "description": "Example strategy showing plugin structure",
    }


class ExampleStrategy(BaseStrategy):
    """Example strategy — do NOT use in production."""

    @property
    def name(self) -> str:
        return "example"

    @property
    def active_regimes(self) -> list[str]:
        return ["BULL", "NEUTRAL"]

    def generate_signal(self, symbol, features, regime):
        """Simple RSI-based example."""
        rsi = features.get("rsi", 50)
        if rsi < 30:
            return Signal(
                symbol=symbol,
                direction=1,
                strength=0.6,
                strategy_name=self.name,
                regime=regime,
                reasoning=f"RSI oversold ({rsi:.1f} < 30)",
            )
        elif rsi > 70:
            return Signal(
                symbol=symbol,
                direction=-1,
                strength=0.6,
                strategy_name=self.name,
                regime=regime,
                reasoning=f"RSI overbought ({rsi:.1f} > 70)",
            )
        return None
''', encoding="utf-8")
        logger.info("example_plugin_created", path=str(example))
