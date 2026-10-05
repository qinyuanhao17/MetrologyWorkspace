"""Shared widgets for interactive plot workspaces."""

from .grid import PanelGrid, PlotPanel
from .interactive import InteractivePlotWidget, place_legend_above_frame

__all__ = ["InteractivePlotWidget", "PanelGrid", "PlotPanel",
           "place_legend_above_frame"]
