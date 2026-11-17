"""Portable selected dies, independent of source paths and checkbox participation."""
import json

from .selection_script import IDENTITY_FIELDS, canonical_die


def _identity(source):
    identity = source.identity
    return (identity.wafer.strip(), identity.lot.strip(), identity.pad.strip(),
            canonical_die(identity.die_seq if identity.die_seq is not None else ''))


def export_selected_dies(sources, selected_keys):
    identities = sorted({_identity(source) for source in sources
                         if source.has_map_point and source.key in selected_keys})
    return json.dumps({'format': 'metrology-die-selection', 'version': 1,
                       'records': [dict(zip(IDENTITY_FIELDS, identity)) for identity in identities]},
                      ensure_ascii=False, indent=2)


def import_selected_dies(sources, text):
    """Validate before returning keys; one die may match several SME channels."""
    try:
        payload = json.loads(text)
    except (TypeError, ValueError, RecursionError) as error:
        raise ValueError('Paste a selection copied with Copy Select.') from error
    if (not isinstance(payload, dict) or payload.get('format') != 'metrology-die-selection'
            or type(payload.get('version')) is not int or payload['version'] != 1
            or not isinstance(payload.get('records'), list)):
        raise ValueError('Unsupported Die Map selection format.')
    wanted = set()
    for record in payload['records']:
        if (not isinstance(record, dict) or set(record) != set(IDENTITY_FIELDS)
                or any(not isinstance(record[field], str) for field in IDENTITY_FIELDS)):
            raise ValueError('Die selection needs Wafer ID, Lot ID, PAD Name and Die.')
        wanted.add(tuple(record[field].strip() if field != 'die' else canonical_die(record[field])
                         for field in IDENTITY_FIELDS))
    matched, keys = set(), set()
    for source in sources:
        identity = _identity(source)
        if source.has_map_point and identity in wanted:
            matched.add(identity)
            keys.add(source.key)
    if wanted and not matched:
        raise ValueError('No matching Wafer / Lot / PAD / Die in this Die Map; selection unchanged.')
    return keys, len(wanted - matched)
