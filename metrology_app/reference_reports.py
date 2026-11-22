"""Excel checks for NOVA, PMISH and KLA reference batches."""

from itertools import islice
from pathlib import Path

from .reference_input import check_cancel


REPORT_WORKBOOK = '_reports.xlsx'
DATA_ROWS_PER_SHEET = 1_048_575  # Excel leaves one row for the column headers.


def write_reports(path, reports, cancelled=None):
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter

    def text_cell(sheet, value):
        if len(value) > 32767:
            raise ValueError(f'{sheet.title}: report text exceeds the Excel cell limit')
        cell = WriteOnlyCell(sheet, value=value)
        cell.data_type = 's'  # Vendor metadata and filenames are literal text.
        return cell

    workbook = Workbook(write_only=True)
    try:
        for name, (items, columns) in reports.items():
            for start in range(0, max(1, len(items)), DATA_ROWS_PER_SHEET):
                check_cancel(cancelled)
                stop = min(start + DATA_ROWS_PER_SHEET, len(items))
                title = name if not start else f'{name}_{start // DATA_ROWS_PER_SHEET + 1}'
                sheet = workbook.create_sheet(title)
                sheet.freeze_panes = 'A2'
                sheet.auto_filter.ref = f'A1:{get_column_letter(len(columns))}{stop - start + 1}'
                samples = items[start:min(start + 100, stop)]
                for index, column in enumerate(columns, 1):
                    sample_width = max((len(str(item.get(column, ''))) for item in samples), default=0)
                    width = max(len(column), sample_width)
                    sheet.column_dimensions[get_column_letter(index)].width = min(65, width + 4)
                headers = [text_cell(sheet, column) for column in columns]
                for cell in headers:
                    cell.font = Font(bold=True)
                sheet.append(headers)
                for index, item in enumerate(islice(items, start, stop)):
                    if index % 256 == 0:
                        check_cancel(cancelled)
                    values = (item.get(column) for column in columns)
                    sheet.append([text_cell(sheet, value) if isinstance(value, str) and value else value
                                  for value in values])
                sheet.close()
        check_cancel(cancelled)
        workbook.save(path)
    finally:
        # openpyxl removes the streamed sheet files on save. Release any that
        # it did not reach if a batch was cancelled or the export failed.
        for sheet in workbook:
            writer = sheet._writer
            if writer is not None and Path(writer.out).exists():
                if not sheet.closed:
                    sheet.close()
                writer.cleanup()
