"""Copy point participation only between unambiguously matching Die layouts."""
from collections import defaultdict
import math


def _profile(sources):
    profile = {}
    for source in sources:
        die = source.identity.die_seq
        if die is None or not source.has_map_point or not all(math.isfinite(v) for v in (source.x_mm, source.y_mm)):
            raise ValueError("Every Die needs an ID and finite X/Y coordinates in mm.")
        point = source.x_mm, source.y_mm
        if die in profile:
            previous = profile[die][0]
            if any(abs(a-b) > 1e-6 for a, b in zip(previous, point)):
                raise ValueError(f"Die {die} has conflicting coordinates.")
            profile[die][1].append(source.key)
        else:
            profile[die] = (point, [source.key])
    if not profile:
        raise ValueError("The source wafer has no measurement points.")
    return profile


def similar_wafer_selection(spectra, wafer, checked_keys, tolerance_mm=.4):
    """Return file checkbox updates, matched wafers and skipped-wafer reasons."""
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("Coordinate tolerance must be a positive finite number in mm.")
    groups = defaultdict(list)
    for source in spectra:
        groups[(source.identity.wafer, source.identity.lot, source.identity.pad)].append(source)
    reference = _profile(groups[tuple(wafer)])
    uses = {}
    for die, (_point, keys) in reference.items():
        states = {key in checked_keys for key in keys}
        if len(states) != 1:
            raise ValueError(f"Die {die} has conflicting checkbox states. Make its spectra consistent first.")
        uses[die] = states.pop()
    updates, matched, skipped = {}, [], []
    for identity, sources in groups.items():
        if identity == tuple(wafer):
            continue
        try:
            profile = _profile(sources)
            if profile.keys() != reference.keys():
                raise ValueError("Different Die ID set.")
            if any(abs(profile[die][0][axis] - reference[die][0][axis]) >= tolerance_mm
                   for die in reference for axis in (0, 1)):
                raise ValueError("Corresponding X/Y differences reach or exceed the tolerance.")
        except ValueError as error:
            skipped.append((identity, str(error)))
            continue
        matched.append(identity)
        for die, (_point, keys) in profile.items():
            updates.update((key, uses[die]) for key in keys)
    return updates, matched, skipped
