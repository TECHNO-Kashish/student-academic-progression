"""DB <-> spreadsheet synchronisation.
push(): DB -> sheet (whole DB + segregated activity tabs). Called after every GUI change.
pull(): sheet -> DB; every row passes the same validation/constraints; bad rows are rejected,
        then the sheet is re-pushed so invalid cells are overwritten with the DB truth.
Backend: Google Sheets if GSHEET_ID + GOOGLE_CREDS (service-account JSON path) are set,
         otherwise a local Excel file (ledger_sync.xlsx) so everything works offline.
"""
import os
import pandas as pd
import db

EXCEL_PATH = os.getenv("SYNC_XLSX", "ledger_sync.xlsx")
VIEW_TABS = {"Internal_Seminars": ("SEMINAR", "INTERNAL"), "External_Seminars": ("SEMINAR", "EXTERNAL"),
             "Technical_CoCurricular": ("CO_CURRICULAR", None), "Extra_Curricular": ("EXTRA_CURRICULAR", None)}


class ExcelBackend:
    name = f"Local Excel ({EXCEL_PATH})"
    def write(self, dfs):
        with pd.ExcelWriter(EXCEL_PATH) as w:
            for n, d in dfs.items(): d.to_excel(w, sheet_name=n, index=False)
    def read(self):
        return pd.read_excel(EXCEL_PATH, sheet_name=None) if os.path.exists(EXCEL_PATH) else {}


class GSheetBackend:
    name = "Google Sheets"
    def __init__(self):
        import gspread
        self.sh = gspread.service_account(filename=os.environ["GOOGLE_CREDS"]).open_by_key(os.environ["GSHEET_ID"])
    def write(self, dfs):
        have = {w.title: w for w in self.sh.worksheets()}
        for n, d in dfs.items():
            ws = have.get(n) or self.sh.add_worksheet(n, rows=max(len(d) + 10, 50), cols=max(len(d.columns), 8))
            d = d.astype(object).where(d.notna(), "").astype(str)
            ws.clear(); ws.update([list(d.columns)] + d.values.tolist())
    def read(self):
        return {w.title: pd.DataFrame(w.get_all_records()) for w in self.sh.worksheets()}


def backend():
    if os.getenv("GSHEET_ID") and os.getenv("GOOGLE_CREDS"): return GSheetBackend()
    return ExcelBackend()

def push():
    dfs = {n: db.table_df(n) for n in db.ORDER}
    act = db.activity_df()
    for tab, (cat, scope) in VIEW_TABS.items():
        v = act[act.category == cat]
        if scope: v = v[v.scope == scope]
        dfs[tab] = v.drop(columns=["category"] + (["scope"] if scope is None else [])).reset_index(drop=True)
    be = backend(); be.write(dfs)
    return be.name

def pull():
    be = backend(); data = be.read(); applied, errors = 0, []
    for n in db.ORDER:                                   # parents first so FKs resolve
        df = data.get(n)
        if df is None or df.empty: continue
        for i, row in df.iterrows():
            err = db.save_row(n, row.to_dict())
            if err: errors.append(f"{n} sheet row {i + 2}: {err}")
            else: applied += 1
    push()                                               # overwrite rejected cells with DB truth
    return applied, errors
