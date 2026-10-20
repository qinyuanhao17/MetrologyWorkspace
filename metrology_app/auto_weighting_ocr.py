"""Two grid templates and a pinned, CPU-only, local RapidOCR adapter.

No screenshot is transmitted; absent/corrupt models fail instead of downloading.
The GUI imports this module only inside its recognition worker.
"""
import hashlib
from pathlib import Path
import re

import cv2
import numpy as np

from .auto_weighting import BASE_COLUMNS, MODES, Cell, RecognizedTable, step_columns

MODEL_NAME = 'PP-OCRv6_rec_small.onnx'
MODEL_SHA256 = '6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884'


def normalize_mode(text):
    lowered = text.casefold()
    exact = next((mode for mode in MODES if mode.casefold() == lowered), None)
    if exact:
        return exact
    # A mode is a closed, three-word vocabulary, not a numeric/parameter field.
    # Suggest only a unique single-character edit; retain raw OCR and require review.
    matches = []
    for mode in MODES:
        target = mode.casefold()
        previous = list(range(len(target)+1))
        for index, char in enumerate(lowered, 1):
            current = [index]
            for col, other in enumerate(target, 1):
                current.append(min(current[-1]+1, previous[col]+1, previous[col-1]+(char != other)))
            previous = current
        if previous[-1] <= 1:
            matches.append(mode)
    return matches[0] if len(matches) == 1 and len(text) >= 3 else text


class RecognitionCancelled(Exception):
    pass


def local_self_test():
    image = np.full((42, 200, 3), 255, np.uint8)
    cv2.putText(image, '123.45', (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    return LocalRecognizer()([image])[0][0] == '123.45'


def _peaks(values, threshold):
    indices = np.flatnonzero(values >= threshold)
    groups = np.split(indices, np.flatnonzero(np.diff(indices) > 2)+1)
    # A gray header becomes a broad horizontal band. Its bottom, not its
    # centre, is the first body-row boundary.
    return [int(group[-1]) if len(group) > 5 else int(np.mean(group)) for group in groups if len(group)]


def find_grid(image):
    height, width = image.shape[:2]
    if not 60 <= height <= 8000 or not 200 <= width <= 8000 or height*width > 16000000:
        raise ValueError('Screenshot size unsupported; crop the table grid (up to 16 megapixels).')
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = (gray < 190).astype(np.uint8)*255
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((1, max(30, width//3)), np.uint8))
    ys = _peaks(np.count_nonzero(horizontal, axis=1), width*.65)
    if len(ys) < 3:
        raise ValueError('No complete table grid found. Copy a tightly cropped screenshot including column headers.')
    vertical = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((max(20, (ys[-1]-ys[0])//3), 1), np.uint8))
    xs = _peaks(np.count_nonzero(vertical[ys[0]:ys[-1]], axis=0), (ys[-1]-ys[0])*.6)
    indices = np.flatnonzero(horizontal[ys[len(ys)//2]])
    xs = [x for x in xs if indices[0]-2 <= x <= indices[-1]+2]
    if len(xs) < 5 or len(xs) > 44 or len(ys) > 1000:
        raise ValueError('Unsupported table grid. Include the Name column and all Step/parameter headers.')
    return xs, ys


def prepare_cell(image, bbox, *, dropdown=False):
    left, top, right, bottom = bbox
    crop = image[top+2:bottom-2, left+2:right-2]
    if dropdown and crop.shape[1] > 20:
        crop = crop[:, :-7]  # Exclude the combo arrow, not any field value.
    if not crop.size:
        return None
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    mask = gray < min(190, float(np.percentile(gray, 85))-35)
    if np.count_nonzero(mask) < 3:
        return None
    yy, xx = np.nonzero(mask)
    clean = np.where(mask, gray, 255).astype(np.uint8)
    # Tight text crops make short numbers and leading minus signs visible to
    # the recognizer; do not rescale a mostly-empty, wide table cell.
    clean = clean[yy.min():yy.max()+1, xx.min():xx.max()+1]
    clean = cv2.copyMakeBorder(clean, 4, 4, 4, 4, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(clean, cv2.COLOR_GRAY2BGR)


class LocalRecognizer:
    def __init__(self, model_path=None):
        if model_path is not None and not Path(model_path).is_file():
            raise FileNotFoundError('Local OCR model is missing; reinstall the complete offline application.')
        try:
            import rapidocr
            from importlib.metadata import version
            if version('rapidocr') != '3.10.0':
                raise RuntimeError('AutoWeighting Writer requires the tested RapidOCR 3.10.0 package.')
        except ImportError as error:
            raise RuntimeError('Offline OCR dependencies are missing; install the complete application package.') from error
        model = Path(model_path) if model_path else Path(rapidocr.__file__).parent / 'models' / MODEL_NAME
        if not model.is_file():
            raise FileNotFoundError('Local OCR model is missing; reinstall the complete offline application.')
        if hashlib.sha256(model.read_bytes()).hexdigest() != MODEL_SHA256:
            raise ValueError('Local OCR model checksum mismatch; no model was downloaded or used.')
        self.engine = rapidocr.RapidOCR(params={
            'Global.use_det': False, 'Global.use_cls': False, 'Rec.model_path': str(model),
            'EngineConfig.onnxruntime.intra_op_num_threads': 2,
            'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        })

    def __call__(self, crops):
        # This public batch helper is covered by the pinned-version/offline
        # contract test; no detection, direction model or font is needed.
        output = self.engine.recognize_txt(crops)
        if output.txts is None or len(output.txts) != len(crops):
            raise RuntimeError('Local OCR returned an incomplete cell batch.')
        return list(zip(output.txts, output.scores))


def recognize_screenshot(png, source, kind='auto', *, recognizer=None, cancelled=lambda: False, progress=lambda _: None):
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Cannot read this image. Use PNG, JPEG or a copied screenshot.')
    xs, ys = find_grid(image)
    count = len(xs)-1
    if kind == 'auto':
        kind = 'parameters' if count in (4, 11) else 'steps'
    if kind == 'parameters' and count not in (4, 11) or kind == 'steps' and (count < 4 or count % 2):
        raise ValueError('Grid columns do not match the selected table type. Include the full table width.')
    if kind not in ('parameters', 'steps'):
        raise ValueError('Choose Parameters or Multiple Step.')
    columns = BASE_COLUMNS if kind == 'parameters' else step_columns((count-2)//2)
    selected = [0, 2, 3, 4] if kind == 'parameters' and count == 11 else (
        list(range(4)) if kind == 'parameters' else [0]+list(range(2, count)))
    engine = recognizer

    def read(rectangles, dropdowns=()):
        nonlocal engine
        cells, active, positions = [], [], []
        for index, rectangle in enumerate(rectangles):
            if cancelled():
                raise RecognitionCancelled()
            crop = prepare_cell(image, rectangle, dropdown=index in dropdowns)
            cells.append(Cell('', source, tuple(rectangle), 1.0))
            if crop is not None:
                active.append(crop)
                positions.append(index)
        for start in range(0, len(active), 12):
            if cancelled():
                raise RecognitionCancelled()
            if engine is None:
                engine = LocalRecognizer()
            results = engine(active[start:start+12])
            for index, (raw, score) in zip(positions[start:start+12], results):
                cells[index] = Cell(str(raw).strip(), source, tuple(rectangles[index]), float(score), raw=str(raw))
            progress(f'Recognized {min(start+12, len(active))}/{len(active)} non-empty cells')
        return cells

    row_height = int(np.median(np.diff(ys)))
    header_top = max(0, ys[0]-max(20, row_height))
    if kind == 'parameters':
        rectangles = [(xs[col], header_top, xs[col+1], ys[0]) for col in selected]
        expected = ['name', 'nominal', 'min', 'max']
    else:
        rectangles = [(xs[0], header_top, xs[1], ys[0])] + [
            (xs[col], header_top, xs[col+2], ys[0]) for col in range(2, count, 2)]
        expected = ['name'] + [f'step{i}' for i in range(1, (count-2)//2+1)]
    headers = read(rectangles)
    actual = [re.sub(r'\s+', '', cell.text).casefold() for cell in headers]
    if actual != expected:
        raise ValueError('Column headers could not be verified (' + ', '.join(cell.text for cell in headers)
                         + '). Include readable Name/Nominal/Min/Max or Step1… headers; no column offset was guessed.')
    rectangles, dropdowns = [], set()
    for top, bottom in zip(ys, ys[1:]):
        for index, col in enumerate(selected):
            if kind == 'steps' and index % 2:
                dropdowns.add(len(rectangles))
            rectangles.append((xs[col], top, xs[col+1], bottom))
    cells = read(rectangles, dropdowns)
    rows, warnings = [], []
    width = len(selected)
    for start in range(0, len(cells), width):
        row = cells[start:start+width]
        if kind == 'steps':
            # Seed/checkbox rows and weighting buttons are not parameter modes.
            # Their pixels stay in the saved screenshot; V1 does not infer them.
            if not any(cell.text for cell in row[1::2]):
                warnings.append('A control/footer row was not imported; V1 reads parameter Mode/Value fields only.')
                continue
            if 'seed' in row[0].text.casefold() or 'weight' in row[0].text.casefold() or 'nextstep' in row[0].text.replace(' ', '').casefold():
                continue
            for cell in row[1::2]:
                cell.text = normalize_mode(cell.text)
        if not row[0].text:
            warnings.append('A row with an unreadable Name was not imported; inspect the source image.')
            continue
        rows.append(row)
    if cancelled():
        raise RecognitionCancelled()
    if not rows:
        raise ValueError('No parameter rows recognized. Try a larger, tightly cropped screenshot.')
    return RecognizedTable(kind, list(columns), rows, list(dict.fromkeys(warnings)))
