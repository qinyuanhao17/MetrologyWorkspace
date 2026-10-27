"""Data-only Correlation worker, with the existing fit/NaN semantics."""
def prepare_correlations(request, cancelled):
    from .correlation_page import pairwise_linear_fits, source_pairwise_linear_fits
    if cancelled():
        return None
    arguments = request["frame"], request["metrics"]
    if request["sources"]:
        fits, errors = source_pairwise_linear_fits(*arguments, request["sources"],
            request["groups"], request["cells"], cancelled=cancelled)
    else:
        fits, errors = pairwise_linear_fits(*arguments, request["groups"], request["cells"],
                                           cancelled=cancelled)
    return fits, errors, request["metrics"], request["cells"]
