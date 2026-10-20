import unittest
import numpy as np
import cv2

from metrology_app.auto_weighting_ocr import find_grid, prepare_cell, recognize_screenshot, LocalRecognizer, normalize_mode


class GridTests(unittest.TestCase):
    def test_gray_headers_do_not_merge_with_first_parameter_row(self):
        image = np.full((142, 403, 3), 242, np.uint8)
        image[10:40, 5:398] = 170
        for x in (5, 100, 200, 300, 398):
            cv2.line(image, (x, 10), (x, 138), (140, 140, 140), 1)
        for y in (40, 72, 104, 138):
            cv2.line(image, (5, y), (398, y), (140, 140, 140), 1)
        xs, ys = find_grid(image)
        self.assertEqual(xs, [5, 100, 200, 300, 398])
        self.assertEqual(ys, [40, 72, 104, 138])

    def test_blank_is_not_ocr_hallucination_and_zero_is_not_blank(self):
        image = np.full((40, 100, 3), 240, np.uint8)
        self.assertIsNone(prepare_cell(image, (0, 0, 100, 40)))
        cv2.putText(image, '0', (45, 25), cv2.FONT_HERSHEY_SIMPLEX, .6, (0, 0, 0), 1)
        self.assertIsNotNone(prepare_cell(image, (0, 0, 100, 40)))

    def test_non_table_and_invalid_image_fail_actionably(self):
        with self.assertRaisesRegex(ValueError, 'grid'):
            find_grid(np.full((200, 300, 3), 255, np.uint8))
        with self.assertRaisesRegex(ValueError, 'image'):
            recognize_screenshot(b'not png', 'a')

    def test_missing_model_does_not_try_download(self):
        from unittest.mock import patch
        with patch('socket.socket.connect', side_effect=AssertionError('network is forbidden')):
            with self.assertRaisesRegex(FileNotFoundError, 'model'):
                LocalRecognizer(model_path='D:/WaferMap/.cache/does-not-exist.onnx')

    def test_only_closed_mode_vocabulary_is_normalized(self):
        self.assertEqual(normalize_mode('Flx'), 'Fix')
        self.assertEqual(normalize_mode('Constraln'), 'Constrain')
        self.assertEqual(normalize_mode('FIx'), 'Fix')
        self.assertEqual(normalize_mode('nonsense'), 'nonsense')
        self.assertEqual(normalize_mode(''), '')

    def test_real_bundled_recognizer_works_with_network_and_downloads_forbidden(self):
        from unittest.mock import patch
        image = np.full((42, 200, 3), 255, np.uint8)
        cv2.putText(image, '123.45', (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
        with patch('socket.socket.connect', side_effect=AssertionError('network forbidden')), \
                patch('rapidocr.utils.download_file.DownloadFile.run', side_effect=AssertionError('download forbidden')):
            engine = LocalRecognizer()
            result = engine([image])
        self.assertEqual(result[0][0], '123.45')


if __name__ == '__main__':
    unittest.main()
