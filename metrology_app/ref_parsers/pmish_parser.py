import pandas as pd
import io
import re

def parse_pmish_file(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        lines = f.readlines()
    metadata = {}
    for line in lines[:6]:
        parts = line.strip().split(',')
        for i in range(0, len(parts)-1, 2):
            key = parts[i].rstrip(':').strip()
            val = parts[i+1].strip()
            if key: metadata[key] = val
    wafer_id = metadata.get('WaferID', '')
    lot_id = metadata.get('LotID', '')
    tool_sn = metadata.get('ToolSN', '')
    summary_kw = {'MAX', 'MIN', 'AVERAGE', 'Standard Deviation', 'Range', 'Uniformity', '%Std'}
    sections = []
    for i, line in enumerate(lines):
        if line.strip().startswith('Seq,'):
            end = len(lines)
            for j in range(i+1, len(lines)):
                fc = lines[j].strip().split(',')[0].strip()
                if fc in summary_kw or fc == 'Seq':
                    end = j; break
            if end > i+1:
                sections.append((i, end))
    dfs = []
    for hdr_idx, end_idx in sections:
        text = ''.join(lines[hdr_idx:end_idx])
        df = pd.read_csv(io.StringIO(text), encoding='utf-8', index_col=False,
                         dtype=str, keep_default_na=False)
        if len(df) > 0:
            df.columns = [re.sub(r'\([^)]*\)', '', str(c)).strip() for c in df.columns]
            dfs.append(df)
    if not dfs: raise ValueError('No data found in PMISH file: ' + filepath)
    result = pd.concat(dfs, ignore_index=True)
    result.insert(0, 'ToolSN', tool_sn)
    result.insert(0, 'LotID', lot_id)
    result.insert(0, 'WaferID', wafer_id)
    return result
