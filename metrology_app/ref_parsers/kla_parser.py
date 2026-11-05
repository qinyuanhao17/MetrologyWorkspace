import pandas as pd
import io
import re

def parse_kla_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()

    summary_kw = {'RESULT TYPE', 'MEAN', 'MIN', 'MAX', 'STDDEV', '3 SIGMA', 'RANGE'}

    site_indices = []
    for i, line in enumerate(lines):
        if line.strip().startswith('Site #,'):
            site_indices.append(i)

    if not site_indices:
        raise ValueError(f'No Site # anchor found in KLA file: {filepath}')

    pad_sections = {}

    for site_pos, site_idx in enumerate(site_indices):
        wafer_id = lot_id = recipe = pad_name = slot = ''
        for j in range(site_idx - 1, -1, -1):
            l = lines[j].strip()
            if not l:
                continue
            fc = l.split(',')[0].strip()
            if fc in summary_kw:
                continue
            if l.startswith('WAFER ID,'):
                wafer_id = l.split(',')[1].strip()
            elif l.startswith('LOT ID,'):
                lot_id = l.split(',')[1].strip()
            elif l.startswith('RECIPE,'):
                recipe = l.split(',')[1].strip()
            elif l.startswith('SLOT,'):
                slot = l.split(',')[1].strip()
            elif l.startswith('TEST LABEL,'):
                pad_name = l.split(',')[1].strip()
                # Continue up for more metadata but stop at data/cross-section boundary
                for j2 in range(j - 1, -1, -1):
                    l2 = lines[j2].strip()
                    if not l2:
                        continue
                    fc2 = l2.split(',')[0].strip()
                    if fc2 in summary_kw:
                        continue
                    # Stop at data lines or another Site #
                    if fc2.isdigit() or l2.startswith('Site #,'):
                        break
                    if l2.startswith('WAFER ID,'):
                        wafer_id = l2.split(',')[1].strip()
                    elif l2.startswith('LOT ID,'):
                        lot_id = l2.split(',')[1].strip()
                    elif l2.startswith('RECIPE,'):
                        recipe = l2.split(',')[1].strip()
                    elif l2.startswith('SLOT,'):
                        slot = l2.split(',')[1].strip()
                break

        if slot.isdigit() and len(slot) == 1:
            slot = slot.zfill(2)

        if wafer_id.strip().lower() == 'nowaferid':
            wafer_id = f'{lot_id}#{slot}'

        next_site_idx = site_indices[site_pos + 1] if site_pos + 1 < len(site_indices) else len(lines)
        data_end = next_site_idx
        for j in range(site_idx + 1, next_site_idx):
            if not lines[j].strip().replace(',', '').strip():
                data_end = j
                break

        text = ''.join(lines[site_idx:data_end])
        df = pd.read_csv(io.StringIO(text), encoding='utf-8', index_col=False,
                         dtype=str, keep_default_na=False, on_bad_lines='skip')
        if len(df) == 0:
            continue

        df.columns = [re.sub(r'\([^)]*\)', '', str(c)).strip() for c in df.columns]
        df.insert(0, 'PadName', pad_name)
        df.insert(0, 'Recipe', recipe)
        df.insert(0, 'LotID', lot_id)
        df.insert(0, 'WaferID', wafer_id)

        if pad_name not in pad_sections:
            pad_sections[pad_name] = []
        pad_sections[pad_name].append(df)

    if not pad_sections:
        raise ValueError(f'No valid data sections found in KLA file: {filepath}')

    result = {}
    for pad, dfs in pad_sections.items():
        result[pad] = pd.concat(dfs, ignore_index=True)
    return result
