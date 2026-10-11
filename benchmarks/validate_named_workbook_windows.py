"""Read-only desktop WKB GUI acceptance; save only under the explicit scratch.

python -m benchmarks.validate_named_workbook_windows --workbooks DIR --scratch DIR
Native Qt widgets/dialogs are driven offscreen; captures are actual widget grabs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbooks", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--fixture", help="One filename for isolated failure diagnosis")
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    assert args.scratch.resolve() != args.workbooks.resolve()
    os.environ["METROLOGY_SETTINGS_PATH"] = str(args.scratch / "settings.yaml")
    os.environ["METROLOGY_RECOVERY_DIR"] = str(args.scratch / "recovery")
    os.environ["MPLCONFIGDIR"] = str(args.scratch / "mpl")
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    import pandas as pd
    from PyQt6.QtCore import QPoint, QTimer, Qt
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QApplication, QInputDialog
    from metrology_app.matching_window import MatchingWindow
    from metrology_app.appearance import configure_fonts
    from metrology_app.settings import apply_theme
    from metrology_app.workspace_document import same_snapshot
    from metrology_app.workspace_store import load_workspace

    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    configure_fonts(app)
    protected = Path(__file__).resolve().parents[1] / "config/settings.yaml"
    original_settings = digest(protected)
    paths = sorted(args.workbooks.glob("*.wkb"))
    if args.fixture:
        paths = [path for path in paths if path.name == args.fixture]
    hashes = {path: digest(path) for path in paths}
    assert paths, "No fixtures found"

    def close_all():
        for widget in tuple(app.topLevelWidgets()):
            document = getattr(widget, "document", None)
            if document is not None:
                document.force_close = True
                document.timer.stop()
                document.identity_timer.stop()
                widget.close()
                widget.deleteLater()
        app.processEvents()

    def choices(button):
        menu = button.menu()
        menu.popup(button.mapToGlobal(QPoint(0, button.height())))
        app.processEvents()
        result = {action.text(): action for action in menu.actions() if action.isCheckable()}
        menu.hide()
        return result

    def create(button, name):
        old = set(app.topLevelWidgets())
        choices(button)
        failures = []

        def accept():
            dialog = app.activeModalWidget()
            if not isinstance(dialog, QInputDialog):
                failures.append("Naming dialog did not open")
                return
            dialog.setTextValue(name)
            dialog.accept()

        QTimer.singleShot(0, accept)
        next(action for action in button.menu().actions() if action.text() == "New window…").trigger()
        assert not failures, failures
        app.processEvents()
        return next(widget for widget in app.topLevelWidgets()
                    if widget not in old and getattr(widget, "_analysis_window_name", None) == name)

    def plot_page(child):
        return (child.correlation_page if child.workspace_type == "correlation_trend" else
                child.dynamic_trend if child.workspace_type == "dynamic" else child.plot_page)

    try:
        for path in paths:
            root = MatchingWindow()
            root.load_workbook(path)
            root.resize(1500, 950)
            root.show()
            app.processEvents()
            root.document.timer.stop()
            raw = root.raw_model.document_frame().copy()
            reference = root.reference_model.document_frame().copy()
            initial = root.workspace_snapshot()
            target = args.scratch / (path.stem + "-accepted.wkb")
            assert target.resolve() != path.resolve()
            root.save_workbook(target)
            assert same_snapshot(initial, load_workspace(target)), path.name
            expected = {}
            buttons = ((root.correlation_button, "Correlation"),
                       (root.preview_dynamic_button, "Dynamic"),
                       (root.preview_open_button, "Map"))
            for button, label in buttons:
                assert button.isEnabled()
                for number in (1, 2):
                    name = f"{label} {number} acceptance"
                    child = create(button, name)
                    child.document.timer.stop()
                    # Separate manual input from Workbook-derived data; original
                    # tables remain untouched. Dynamic normalizes only its own input.
                    if hasattr(child, "copy_from_wkb_action") and child.copy_from_wkb_action.isChecked():
                        child.copy_from_wkb_action.trigger()
                    source = raw.head(3).copy()
                    source["Acceptance CD"] = [f"{number}.123456789010000"] * len(source)
                    child.set_table(source, "Isolated acceptance data")
                    child.tabs.setCurrentIndex(number - 1)
                    plot_page(child).font_size.setCurrentText("8" if number == 1 else "14")
                    expected[name] = child.workspace_snapshot()
                choices(button)[f"{label} 1 acceptance"].trigger()
            root.save_workbook(target)
            close_all()
            root = MatchingWindow()
            root.load_workbook(target)
            root.show()
            app.processEvents()
            for button, label in ((root.correlation_button, "Correlation"),
                                  (root.preview_dynamic_button, "Dynamic"),
                                  (root.preview_open_button, "Map")):
                selected = choices(button)
                assert not selected[f"{label} 1 acceptance"].isChecked()
                assert selected[f"{label} 2 acceptance"].isChecked()
                button.click()
                assert not any(widget.isVisible() and getattr(widget, "_analysis_window_name", None) == f"{label} 1 acceptance"
                               for widget in app.topLevelWidgets())
                selected[f"{label} 1 acceptance"].trigger()
                button.click()
                for number in (1, 2):
                    name = f"{label} {number} acceptance"
                    child = next(widget for widget in app.topLevelWidgets()
                                 if getattr(widget, "_analysis_window_name", None) == name and widget.isVisible())
                    actual = child.workspace_snapshot()
                    for key, frame in expected[name].frames.items():
                        pd.testing.assert_frame_equal(frame, actual.frames[key])
                    differences = [key for key in expected[name].states.keys() | actual.states.keys()
                                   if expected[name].states.get(key) != actual.states.get(key)]
                    assert same_snapshot(expected[name], actual), (path.name, name, differences)
            pd.testing.assert_frame_equal(root.raw_model.document_frame(), raw)
            pd.testing.assert_frame_equal(root.reference_model.document_frame(), reference)
            # Final has a separate catalog. Its three legacy left-side actions
            # remain usable, including fixtures with no Final Raw table.
            root.result_mode.setCurrentText("Final")
            for button in (root.correlation_button, root.final_dynamic_button, root.final_open_button):
                assert button.isEnabled()
                button.click()
            root.result_mode.setCurrentText("Preview")
            if path.name == "matching-analysis_nova_testfilter1.wkb":
                for child in (root.open_stage_workspace("preview"), root.open_correlation_workspace()):
                    child.full_data_action.trigger()
                    assert child.full_data_action.isChecked()
                    assert not child.workbook_selection_action.isChecked()
                    assert len(child.model.document_frame()) == len(raw) == 7731
                    child.workbook_selection_action.trigger()
                    assert child.workbook_selection_action.isChecked()
                    assert len(child.model.document_frame()) == 6958
                for theme in ("light", "dark"):
                    apply_theme(root, theme)
                    root.raise_()
                    root.preview_open_button.menu().popup(root.preview_open_button.mapToGlobal(QPoint(0, root.preview_open_button.height())))
                    app.processEvents()
                    root.grab().save(str(args.scratch / f"named-windows-{theme}.png"))
                    root.preview_open_button.menu().grab().save(str(args.scratch / f"named-window-menu-{theme}.png"))
                    root.preview_open_button.menu().hide()
                map_child = root.open_stage_workspace("preview")
                map_child.data_menu.popup(map_child.mapToGlobal(QPoint(30, 65)))
                app.processEvents()
                map_child.data_menu.grab().save(str(args.scratch / "data-menu.png"))
                map_child.data_menu.hide()
                # Verify keyboard cut/Undo on a literal source cell from the real fixture.
                model, view = map_child.model, map_child.sheet
                column = next(i for i, name in enumerate(model.document_frame().columns) if name == "Wafer ID")
                model.set_clipboard_locks(["Wafer ID"])
                before = model.document_frame().copy()
                view.setCurrentIndex(model.index(1, column))
                QTest.keyClick(view, Qt.Key.Key_X, Qt.KeyboardModifier.ControlModifier)
                assert app.clipboard().text().strip() == before.iloc[0, column]
                pd.testing.assert_frame_equal(before, model.document_frame())
            print(json.dumps({"file": path.name, "rows": len(raw), "gui_roundtrip": "pass",
                              "named_windows": 6, "independent_sources_and_plot_settings": "pass",
                              "preview_final_buttons": "pass", "sha256": hashes[path]}), flush=True)
            close_all()
    finally:
        close_all()
        for path, before in hashes.items():
            assert digest(path) == before, f"Original modified: {path}"
        assert digest(protected) == original_settings, "User settings modified"


if __name__ == "__main__":
    main()
