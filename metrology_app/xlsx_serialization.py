"""Batch scalar rows in authored reports; openpyxl still owns the XLSX format.

No global writer patches: concurrent exports have independent styles, progress
and cancellation. Unusual cell types retain openpyxl's normal row serializer.
"""
# Worksheet orchestration adapts openpyxl's MIT-licensed writers.
# Copyright (c) 2010 openpyxl
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
# of the Software, and to permit persons to whom the Software is furnished to
# do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
from datetime import datetime, timezone
import re
from xml.sax.saxutils import quoteattr
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED

from openpyxl import LXML
from openpyxl.compat import safe_string
from openpyxl.drawing.spreadsheet_drawing import SpreadsheetDrawing
from openpyxl.worksheet._writer import WorksheetWriter
from openpyxl.writer.excel import ExcelWriter
from openpyxl.xml.functions import xmlfile
from openpyxl.xml.constants import SHEET_MAIN_NS

_INVALID_XML = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')


def _text(value):
    # A literal CR must survive XML newline normalization, including in formulas.
    if _INVALID_XML.search(value):
        raise ValueError('Invalid XML character in export text')
    return value.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\r', '&#13;')


class _WorksheetWriter(WorksheetWriter):
    def __init__(self, sheet, checkpoint):
        super().__init__(sheet)
        self.checkpoint, self.style_ids = checkpoint, {}

    def get_stream(self):
        # Share one buffered output with the normal XML writer. Flush its bytes
        # before each scalar row; fallback rows and worksheet metadata still use
        # openpyxl, in exactly the same order. No process-global monkeypatches.
        with open(self.out, 'wb') as output:
            self.output = output
            with xmlfile(output) as stream:
                with stream.element('worksheet', xmlns=SHEET_MAIN_NS):
                    try:
                        while True:
                            element = (yield)
                            if element is True:
                                yield stream
                            elif element is not None:
                                stream.write(element)
                    except GeneratorExit:
                        pass

    def write_row(self, stream, row, row_idx):
        if row_idx % 256 == 0:
            self.checkpoint()
        if any(cell._comment is not None or cell.hyperlink or cell.data_type not in ('s', 'n', 'f', 'b')
               or (cell.data_type in ('s', 'f') and cell._value is not None
                   and not isinstance(cell._value, str)) for cell in row):
            return super().write_row(stream, row, row_idx)
        attributes = {'r': str(row_idx)}
        attributes.update(dict(self.ws.row_dimensions.get(row_idx, {})))
        parts = ['<row' + ''.join(f' {key}={quoteattr(value)}' for key, value in attributes.items()) + '>']
        for cell in row:
            value, kind = cell._value, cell.data_type
            styled = cell.has_style
            if value is None and not styled:
                continue
            attributes = f' r="{cell.coordinate}"'
            if styled:
                key = tuple(cell._style)
                style = self.style_ids.get(key)
                if style is None:
                    style = cell.style_id
                    self.style_ids[key] = style
                attributes += f' s="{style}"'
            if kind != 'f':
                attributes += f' t="{"inlineStr" if kind == "s" else kind}"'
            if value is None or value == '':
                parts.append(f'<c{attributes}></c>')
            elif kind == 's':
                space = ' xml:space="preserve"' if value != value.strip() else ''
                parts.append(f'<c{attributes}><is><t{space}>{_text(value)}</t></is></c>')
            elif kind == 'f':
                parts.append(f'<c{attributes}><f>{_text(value[1:])}</f><v></v></c>')
            else:
                # Retain openpyxl's numeric precision and non-finite handling.
                parts.append(f'<c{attributes}><v>{_text(safe_string(value))}</v></c>')
        parts.append('</row>')
        # Values are validated/escaped above. Write one bounded row, avoiding
        # both per-cell XML contexts and a redundant parse/serialize round trip.
        stream.flush()
        self.output.write(''.join(parts).encode('ascii', 'xmlcharrefreplace'))


class _Archive(ZipFile):
    def writestr(self, name, data, compress_type=None, compresslevel=None):
        path = name if isinstance(name, str) else name.filename
        if compress_type is None and path.startswith('xl/media/') and path.endswith('.png'):
            # Already compressed PNG bytes remain exact, not recompressed by ZIP.
            compress_type = ZIP_STORED
        return super().writestr(name, data, compress_type, compresslevel)


class _ExcelWriter(ExcelWriter):
    def __init__(self, book, archive, checkpoint):
        super().__init__(book, archive)
        self.checkpoint = checkpoint

    def write_worksheet(self, sheet):
        self.checkpoint(f'Writing worksheet {sheet.title}…')
        sheet._drawing = SpreadsheetDrawing()
        sheet._drawing.charts, sheet._drawing.images = sheet._charts, sheet._images
        writer = _WorksheetWriter(sheet, self.checkpoint)
        try:
            writer.write()
            sheet._rels = writer._rels
            self._archive.write(writer.out, sheet.path[1:])
            self.manifest.append(sheet)
        finally:
            try:
                writer.close()
            finally:
                writer.cleanup()


def save_workbook(book, path, checkpoint):
    """Save the same XLSX parts; store PNGs without a second compression pass."""
    if not LXML or book.write_only or sum(len(sheet._cells) for sheet in book) < 10000:
        book.save(path)
        return
    book.properties.modified = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    with _Archive(path, 'w', ZIP_DEFLATED, allowZip64=True) as archive:
        _ExcelWriter(book, archive, checkpoint).save()
