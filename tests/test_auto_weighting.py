import tempfile
import unittest
from pathlib import Path

from metrology_app.auto_weighting import (
    BASE_COLUMNS, WriterDocument, RecognizedTable, Cell, export_excel,
)


def table(kind, rows, source='image-a'):
    columns = BASE_COLUMNS if kind == 'parameters' else ['Name', 'Step1 Mode', 'Step1 Value']
    return RecognizedTable(kind, columns, [[Cell(text, source, (0, 0, 10, 10), .99) for text in row] for row in rows])


class WriterDataTests(unittest.TestCase):
    def test_preserves_precision_minus_and_visible_blank(self):
        doc = WriterDocument()
        doc.merge(table('parameters', [['A', '1.0000000000000001', '-1', '2']]))
        doc.merge(table('steps', [['A', 'Fix', '']]))
        self.assertEqual(doc.tables['parameters'][0][1].text, '1.0000000000000001')
        self.assertEqual(doc.tables['parameters'][0][2].text, '-1')
        self.assertEqual(doc.tables['steps'][0][2].status, 'visible_blank')
        self.assertEqual(doc.get('steps', 'A', 'Step2 Value').status, 'uncollected')

    def test_merge_overlapping_rows_and_keep_conflicting_candidates(self):
        doc = WriterDocument()
        doc.merge(table('steps', [['A', 'Fix', '10'], ['B', 'Float', '']]))
        doc.merge(table('steps', [['B', 'Float', ''], ['C', 'Constrain', 'A+2']], 'image-b'))
        self.assertEqual([row[0].text for row in doc.tables['steps']], ['A', 'B', 'C'])
        doc.merge(table('steps', [['A', 'Fix', '11']], 'image-c'))
        cell = doc.get('steps', 'A', 'Step1 Value')
        self.assertEqual(cell.text, '10')
        self.assertEqual(cell.alternatives[0]['text'], '11')
        self.assertTrue(any('conflict' in issue.lower() for issue in doc.issues('steps', 0, 2)))
        doc.edit('steps', 0, 2, '11')
        self.assertTrue(doc.get('steps', 'A', 'Step1 Value').reviewed)
        self.assertFalse(doc.get('steps', 'A', 'Step1 Value').alternatives)

    def test_empty_value_does_not_erase_existing_value(self):
        doc = WriterDocument()
        doc.merge(table('steps', [['A', 'Fix', '10']]))
        doc.merge(table('steps', [['A', 'Fix', '']], 'image-b'))
        self.assertEqual(doc.get('steps', 'A', 'Step1 Value').text, '10')
        self.assertEqual(len(doc.get('steps', 'A', 'Step1 Value').alternatives), 1)

    def test_duplicate_in_single_screenshot_is_rejected_atomically(self):
        doc = WriterDocument()
        before = doc.to_dict()
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            doc.merge(table('steps', [['A', 'Fix', '1'], ['A', 'Fix', '2']]))
        self.assertEqual(doc.to_dict(), before)

    def test_reverse_order_overlap_is_not_silently_merged(self):
        doc = WriterDocument()
        doc.merge(table('steps', [['A', 'Fix', '1'], ['B', 'Fix', '2']]))
        with self.assertRaisesRegex(ValueError, 'order'):
            doc.merge(table('steps', [['B', 'Fix', '2'], ['A', 'Fix', '1']], 'b'))

    def test_overlap_anchors_keep_name_ocr_disagreement_as_conflict_not_duplicate_row(self):
        doc = WriterDocument()
        doc.merge(table('steps', [['A', 'Fix', '1'], ['BL_TiN_HT', 'Fix', '2'], ['C', 'Fix', '3']]))
        doc.merge(table('steps', [['A', 'Fix', '1'], ['BL_TIN_HT', 'Fix', '2'], ['C', 'Fix', '3']], 'b'))
        self.assertEqual(len(doc.tables['steps']), 3)
        self.assertEqual(doc.tables['steps'][1][0].text, 'BL_TiN_HT')
        self.assertEqual(doc.tables['steps'][1][0].alternatives[0]['text'], 'BL_TIN_HT')

    def test_validation_never_executes_or_repairs_expression(self):
        doc = WriterDocument()
        expression = '__import__("os").system("anything")'
        doc.merge(table('steps', [['A', 'Constrain', expression], ['B', 'Fix', 'O.4']]))
        self.assertTrue(doc.issues('steps', 0, 2))
        self.assertTrue(doc.issues('steps', 1, 2))
        self.assertEqual(doc.get('steps', 'A', 'Step1 Value').text, expression)
        self.assertEqual(doc.get('steps', 'B', 'Step1 Value').text, 'O.4')

    def test_bounds_and_modes_report_errors_without_changing_source(self):
        doc = WriterDocument()
        doc.merge(table('parameters', [['A', '3', '-1', '2']]))
        doc.merge(table('steps', [['A', 'Flx', '']]))
        self.assertTrue(any('bound' in issue for issue in doc.issues('parameters', 0, 1)))
        self.assertTrue(any('mode' in issue for issue in doc.issues('steps', 0, 1)))
        self.assertEqual(doc.get('steps', 'A', 'Step1 Mode').text, 'Flx')

    def test_roundtrip_keeps_sources_edits_evidence_and_conflicts(self):
        doc = WriterDocument()
        doc.sources['image-a'] = {'name': 'example.png', 'png': 'base64'}
        doc.merge(table('steps', [['A', 'Fix', '1']]))
        doc.merge(table('steps', [['A', 'Fix', '2']], 'b'))
        doc.edit('steps', 0, 1, 'Float')
        restored = WriterDocument.from_dict(doc.to_dict())
        self.assertEqual(restored.to_dict(), doc.to_dict())

    def test_resolving_conflict_uses_chosen_source_and_keeps_history(self):
        doc = WriterDocument()
        doc.merge(table('steps', [['A', 'Fix', '1']], 'first'))
        doc.merge(table('steps', [['A', 'Fix', '2']], 'second'))
        doc.resolve('steps', 0, 2, 1)
        cell = doc.get('steps', 'A', 'Step1 Value')
        self.assertEqual((cell.text, cell.source, cell.raw), ('2', 'second', '2'))
        self.assertEqual(cell.history[-1]['text'], '1')
        self.assertTrue(cell.reviewed)

    def test_excel_preserves_literal_formula_and_marks_missing_collection(self):
        from openpyxl import load_workbook
        doc = WriterDocument()
        doc.merge(table('parameters', [['A', '1.0412700', '-1', '2']]))
        doc.merge(table('steps', [['B', 'Constrain', '=1+2']]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'writer.xlsx'
            export_excel(doc, path)
            book = load_workbook(path, data_only=False)
            self.assertEqual(book['Parameters']['B2'].value, '1.0412700')
            self.assertEqual(book['Multiple Step']['C2'].value, '=1+2')
            self.assertEqual(book['Multiple Step']['C2'].data_type, 's')
            self.assertIn('Collection & Review', book.sheetnames)
            values = list(book['Collection & Review'].values)
            self.assertTrue(any('uncollected' in row for row in values))
            self.assertTrue(any(row[2] == 'Name' and row[3] == 'A' for row in values[1:]))
            book.close()


if __name__ == '__main__':
    unittest.main()
