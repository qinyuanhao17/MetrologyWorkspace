"""Copy point participation only between unambiguously matching Die layouts."""
from collections import defaultdict
from decimal import Decimal
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
    return _similar_wafer_updates(spectra, wafer, lambda key: key in checked_keys, "checkbox", tolerance_mm)


def similar_wafer_flags(spectra, wafer, flags, tolerance_mm=.4):
    """Copy Test Flags (including fallback zero) without changing participation."""
    return _similar_wafer_updates(spectra, wafer, lambda key: flags.get(key, 0), "Test Flag", tolerance_mm)


def _similar_wafer_updates(spectra, wafer, value_for_key, label, tolerance_mm):
    if not math.isfinite(tolerance_mm) or tolerance_mm <= 0:
        raise ValueError("Coordinate tolerance must be a positive finite number in mm.")
    groups = defaultdict(list)
    for source in spectra:
        groups[(source.identity.wafer, source.identity.lot, source.identity.pad)].append(source)
    reference = _profile(groups[tuple(wafer)])
    uses = {}
    for die, (_point, keys) in reference.items():
        states = {value_for_key(key) for key in keys}
        if len(states) != 1:
            raise ValueError(f"Die {die} has conflicting {label} states. Make its spectra consistent first.")
        uses[die] = states.pop()
    updates, matched, skipped = {}, [], []
    for identity, sources in groups.items():
        if identity == tuple(wafer):
            continue
        try:
            profile = _profile(sources)
            if profile.keys() != reference.keys():
                raise ValueError("Different Die ID set.")
            # Compare the recorded decimal mm values so 1.4 - 1.0 cannot slip
            # below the strict 0.4 mm boundary through binary rounding.
            if any(abs(Decimal(str(profile[die][0][axis])) - Decimal(str(reference[die][0][axis]))) >= Decimal(str(tolerance_mm))
                   for die in reference for axis in (0, 1)):
                raise ValueError("Corresponding X/Y differences reach or exceed the tolerance.")
        except ValueError as error:
            skipped.append((identity, str(error)))
            continue
        matched.append(identity)
        for die, (_point, keys) in profile.items():
            updates.update((key, uses[die]) for key in keys)
    return updates, matched, skipped
