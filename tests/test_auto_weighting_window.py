import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from PyQt6.QtCore import QBuffer, QIODevice, Qt
from PyQt6.QtGui import QImage, QColor
from PyQt6.QtWidgets import QApplication, QMessageBox

from metrology_app.auto_weighting import Cell, RecognizedTable
from metrology_app.auto_weighting_window import AutoWeightingWindow
from metrology_app.module_registry import create_default_registry
from metrology_app.workspace_store import load_workspace

APP = QApplication.instance() or QApplication([])


def image_bytes():
    image = QImage(640, 200, QImage.Format.Format_RGB32)
    image.fill(QColor('white'))
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, 'PNG')
    return bytes(buffer.data())


class WriterWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = AutoWeightingWindow()

    def tearDown(self):
        self.window.document.force_close = True
        self.window.close()
        self.window.deleteLater()
        APP.processEvents()

    def seed(self):
        source = self.window.add_image_bytes(image_bytes(), 'clipboard')
        result = RecognizedTable('parameters', ['Name', 'Nominal', 'Min', 'Max'], [
            [Cell(text, source, (0, 0, 40, 40), .99) for text in ['A', '1.0412700', '-1', '2']]])
        self.window.apply_results([result])
        return source

    def test_registered_as_independent_tool(self):
        registry = create_default_registry()
        self.assertEqual(registry.get('auto_weighting_writer').title, 'AutoWeighting Writer')
        self.assertEqual(self.window.tabs.count(), 2)

    def test_guidance_does_not_take_the_table_height(self):
        self.window.show()
        APP.processEvents()
        self.assertGreater(self.window.tabs.height(), self.window.centralWidget().height() * .7)

    def test_inspecting_during_a_model_reset_tolerates_a_stale_index(self):
        self.seed()
        self.window.views['parameters'].setCurrentIndex(self.window.table_models['parameters'].index(0, 1))
        self.window.writer.tables['parameters'] = []
        self.assertIsNone(self.window.current_cell())

    def test_clipboard_paste_keeps_image_as_source_without_recognizing_manually(self):
        image = QImage.fromData(image_bytes())
        APP.clipboard().setImage(image)
        self.window.paste_screenshot()
        self.assertEqual(len(self.window.writer.sources), 1)
        self.assertEqual(len(self.window.writer.tables['parameters']), 0)
        self.assertTrue(self.window.document.is_dirty())

    def test_edit_copy_undo_and_review_preserve_decimal_text(self):
        self.seed()
        model = self.window.table_models['parameters']
        self.assertTrue(model.setData(model.index(0, 1), '1.041270000', Qt.ItemDataRole.EditRole))
        self.window.copy_table()
        self.assertIn('1.041270000', APP.clipboard().text())
        self.window.undo()
        self.assertEqual(self.window.writer.tables['parameters'][0][1].text, '1.0412700')
        self.window.views['parameters'].selectAll()
        self.window.mark_reviewed()
        self.assertTrue(all(cell.reviewed for cell in self.window.writer.tables['parameters'][0]))

    def test_workspace_roundtrip_keeps_screenshot_and_literal_strings(self):
        source = self.seed()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'recipe.waw'
            self.window.document.save(path)
            self.assertFalse(self.window.document.is_dirty())
            snapshot = load_workspace(path)
            self.assertEqual(snapshot.workspace_type, 'auto_weighting')
            other = AutoWeightingWindow()
            try:
                other.load_workspace(path)
                self.assertEqual(other.writer.get('parameters', 'A', 'Nominal').text, '1.0412700')
                self.assertEqual(other.writer.sources[source], self.window.writer.sources[source])
                self.assertFalse(other.document.is_dirty())
            finally:
                other.document.force_close = True
                other.close()
                other.deleteLater()

    def test_cancel_close_keeps_edited_table(self):
        self.seed()
        with patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.window.close())
        self.assertEqual(len(self.window.writer.tables['parameters']), 1)

    def test_conflict_resolution_is_explicit_and_undoable(self):
        source = self.seed()
        incoming = RecognizedTable('parameters', ['Name', 'Nominal', 'Min', 'Max'], [
            [Cell(text, source, (0, 0, 40, 40), .99) for text in ['A', '1.4', '-1', '2']]])
        self.window.apply_results([incoming])
        self.window.views['parameters'].setCurrentIndex(self.window.table_models['parameters'].index(0, 1))
        self.window.evidence_choice.setCurrentIndex(1)
        self.window.use_candidate()
        self.assertEqual(self.window.writer.get('parameters', 'A', 'Nominal').text, '1.4')
        self.window.undo()
        self.assertTrue(self.window.writer.get('parameters', 'A', 'Nominal').alternatives)

    def test_failed_batch_merge_does_not_partially_apply(self):
        self.seed()
        before = self.window.writer.to_dict()
        good = RecognizedTable('steps', ['Name', 'Step1 Mode', 'Step1 Value'], [[Cell(t) for t in ['A', 'Fix', '1']]])
        bad = RecognizedTable('parameters', ['Name', 'Nominal', 'Min', 'Max'], [[Cell(t) for t in ['', '1', '0', '2']]])
        with self.assertRaises(ValueError):
            self.window.apply_results([good, bad])
        self.assertEqual(self.window.writer.to_dict(), before)

    def test_background_ocr_applies_only_after_review_dialog_acceptance(self):
        self.window.add_image_bytes(image_bytes(), 'clipboard')
        def recognize(_png, source, *_args, **_kwargs):
            return RecognizedTable('parameters', ['Name', 'Nominal', 'Min', 'Max'], [
                [Cell(text, source, (0, 0, 40, 40)) for text in ['A', '1', '-1', '2']]])
        self.window.recognize_function = recognize
        with patch('metrology_app.auto_weighting_window.CandidateDialog.exec', return_value=1):
            self.window.start_recognition()
            self.assertTrue(self.window.worker.wait(5000))
            APP.processEvents()
        self.assertIsNone(self.window.worker)
        self.assertEqual(self.window.writer.get('parameters', 'A', 'Min').text, '-1')

    def test_cancelling_background_ocr_preserves_sources_and_existing_table(self):
        self.seed()
        before = self.window.writer.to_dict()
        entered = threading.Event()
        def recognize(_png, _source, *_args, cancelled, **_kwargs):
            entered.set()
            while not cancelled():
                threading.Event().wait(.005)
            return None
        self.window.recognize_function = recognize
        self.window.start_recognition()
        self.assertTrue(entered.wait(2))
        self.window.cancel_recognition()
        self.assertTrue(self.window.worker.wait(5000))
        APP.processEvents()
        self.assertIsNone(self.window.worker)
        self.assertEqual(self.window.writer.to_dict(), before)

    def test_close_during_ocr_waits_for_cooperative_cancellation(self):
        self.window.add_image_bytes(image_bytes(), 'clipboard')
        entered = threading.Event()
        def recognize(_png, _source, *_args, cancelled, **_kwargs):
            entered.set()
            while not cancelled():
                threading.Event().wait(.005)
            return None
        self.window.recognize_function = recognize
        self.window.start_recognition()
        self.assertTrue(entered.wait(2))
        self.window.document.force_close = True
        self.assertFalse(self.window.close())
        self.assertTrue(self.window.worker.wait(5000))
        APP.processEvents()
        self.assertIsNone(self.window.worker)


if __name__ == '__main__':
    unittest.main()
