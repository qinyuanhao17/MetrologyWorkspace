"""Workbook-wide plot variants, independent of instrument Match Type.

Type1 uses positional pairs; Type2 uses explicitly selected composite IDs.
"""

WORKBOOK_TYPES = {"type1": "Type1", "type2": "Type2"}


def normalize_workbook_type(value="type1"):
    """Only a missing field defaults to Type1; explicit unknown types fail."""
    if not isinstance(value, str) or value not in WORKBOOK_TYPES:
        raise ValueError("Workbook Type must be Type1 or Type2.")
    return value
