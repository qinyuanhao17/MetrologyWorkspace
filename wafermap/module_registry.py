"""Registration and creation of independently loadable desktop components."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass

from PyQt6.QtWidgets import QWidget


ComponentFactory = Callable[[], QWidget]


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    component_id: str
    title: str
    description: str
    category: str
    factory: ComponentFactory


class ComponentRegistry:
    """Keep the application shell independent from component implementations."""

    def __init__(self):
        self._components = {}

    def register(self, spec):
        if spec.component_id in self._components:
            raise ValueError(f"Component is already registered: {spec.component_id}")
        self._components[spec.component_id] = spec

    def get(self, component_id):
        try:
            return self._components[component_id]
        except KeyError as error:
            raise ValueError(f"Unknown component: {component_id}") from error

    def create(self, component_id):
        widget = self.get(component_id).factory()
        if not isinstance(widget, QWidget):
            raise TypeError(f"Component {component_id!r} did not create a QWidget")
        return widget

    def __iter__(self) -> Iterator[ComponentSpec]:
        return iter(self._components.values())

    def __len__(self):
        return len(self._components)


def create_default_registry():
    """Register built-in analysis workspaces without importing them at startup."""
    registry = ComponentRegistry()

    def create_wafer_map():
        from .window import MainWindow as WaferMapWindow
        return WaferMapWindow()

    registry.register(ComponentSpec(
        "wafer_map",
        "Wafer Map",
        "Load CSV, XLSX or clipboard data; create wafer-map arrays and signed-radius plots.",
        "Metrology analysis",
        create_wafer_map,
    ))

    def create_correlation_analysis():
        from .correlation_window import CorrelationWindow
        return CorrelationWindow()

    registry.register(ComponentSpec(
        "correlation_analysis",
        "Correlation Analysis",
        "Compare selected numeric columns pairwise with lmfit linear models ranked by R².",
        "Statistical analysis",
        create_correlation_analysis,
    ))
    return registry


__all__ = ["ComponentRegistry", "ComponentSpec", "create_default_registry"]
