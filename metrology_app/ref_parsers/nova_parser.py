import pandas as pd

def parse_nova_file(filepath):
    df = pd.read_csv(filepath, encoding="utf-8", index_col=False, dtype=str, keep_default_na=False)
    # Remove duplicate headers: rows where first cell = column name
    h = str(df.columns[0]).strip()
    dupes = df[df.iloc[:, 0].astype(str).str.strip() == h].index
    if len(dupes) > 0:
        df = df.drop(dupes).reset_index(drop=True)
    return df
