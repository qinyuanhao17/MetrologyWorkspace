"""Literal Excel tables shared by source-linked classification exports."""
from pathlib import Path


def write_identity_table(path, title, header, rows):
    from openpyxl import Workbook
    from openpyxl.utils import get_column_letter

    path = Path(path)
    if path.suffix.lower() != ".xlsx":
        path = path.with_suffix(".xlsx")
    book = Workbook()
    try:
        sheet = book.active
        sheet.title = title
        sheet.append(header)
        for row in rows:
            sheet.append(row)
        for row in sheet:
            for cell in row:
                if isinstance(cell.value, str):
                    cell.data_type = "s"
                    cell.number_format = "@"
        sheet.freeze_panes = "A2"
        for index in range(1, len(header) + 1):
            sheet.column_dimensions[get_column_letter(index)].width = 3 if index == 9 else 22
        sheet.column_dimensions["A"].width = 64
        book.save(path)
    finally:
        book.close()
    return path
