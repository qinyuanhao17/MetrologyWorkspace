"""Presentation-only measurement captions; never use these as grouping keys."""


def plot_label_options(saved=None):
    saved = {} if saved is None else saved
    if not isinstance(saved, dict) or set(saved) - {"trend", "map", "radius"}:
        raise ValueError("Invalid plot label settings.")
    result = {}
    for plot in ("trend", "map", "radius"):
        fields = saved.get(plot, {})
        if (not isinstance(fields, dict) or set(fields) - {"pad", "lot"}
                or any(type(value) is not bool for value in fields.values())):
            raise ValueError("Invalid plot label settings.")
        result[plot] = {field: fields.get(field, True) for field in ("pad", "lot")}
    return result


def measurement_caption(label, options):
    """Omit typed metadata lines, retaining the primary identity and run labels."""
    lines = str(label).splitlines()
    captions = []
    for index, line in enumerate(lines):
        prefix, separator, value = line.partition(":")
        # The first line is the primary identity, even if its literal value
        # resembles a metadata prefix. Old Lot: captions remain compatible.
        field = {"PAD": "pad", "Lot": "lot", "LOT": "lot"}.get(prefix) if index and separator else None
        if field is None:
            captions.append(line)
        elif options.get(field, True):
            captions.append(f"{field.upper()}:{value}")
    return "\n".join(captions)
