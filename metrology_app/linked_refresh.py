"""Detached table preparation for automatic Workbook child refreshes."""
from .sheet import prepare_sheet_frame


def prepare_linked_sources(request, cancelled):
    book = request["book"]
    prepared = {}
    for key, kind, stage, follows, locked, options in request["children"]:
        if cancelled():
            return None
        if not follows:
            continue
        if kind == "correlation":
            frame = request["raw"]
        elif kind == "map" and book is not None:
            if book.match_type == "TEM":
                source = book.final_match_raw if stage == "final" and book.final_match_raw is not None else book.raw
                frame = book.participating_frame(source, paired_source=True, apply_selection=False)
            else:
                frame = book.stage_frame(stage, apply_card=False, apply_selection=False, use_snapshot=False)
        else:
            continue
        if locked:
            # Locked metadata is merged and validated against the live child.
            # Its final frame may differ from the parent's prepared table.
            continue
        table = prepared[key] = prepare_sheet_frame(frame)
        analysis = table["analysis"]
        if cancelled():
            return None
        if analysis is not None and not options["carded"]:
            from .input_planning import prepare_measurement_choices
            table["recognition"] = {"frame": analysis,
                "include_fit_quality": options["include_fit_quality"],
                "choices": prepare_measurement_choices(analysis,
                    include_fit_quality=options["include_fit_quality"])}
        if cancelled():
            return None
        if kind == "correlation" and book is not None and analysis is not None:
            from .correlation_groups import prepare_group_result, prepare_trend_parts
            group_result = table["group_result"] = prepare_group_result(book, analysis,
                options["reference"], options["applies"])
            if group_result["plan"] is not None and not cancelled():
                groups, split = options["trend_groups"], len(options["reference"])
                group_result["trend_parts"] = (group_result["plan"], split, groups,
                    prepare_trend_parts(group_result["plan"], split, groups))
    return {"generation": request["generation"], "book": book,
            "inputs": request["inputs"], "tables": prepared}
