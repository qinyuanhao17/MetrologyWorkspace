"""Set up mappings explicitly in tests that exercise downstream matching."""

from metrology_app.matching import MatchWorkbook


def configure_match_fixture(window, *mappings):
    """Configure mappings explicitly for an already loaded test dataset."""
    if not mappings:
        mappings = MatchWorkbook.suggest_mappings(window.reference_frame, window._active_raw_frame())
    window._populate_mappings(mappings)
    window._update_state()
