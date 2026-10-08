"""Right-side metadata protection controls; source columns never move."""
from PyQt6.QtWidgets import QCheckBox, QFrame, QLabel, QVBoxLayout


METADATA_NAMES = {
    "waferid", "wafer", "waferno", "lotid", "lot", "lotno", "padname", "pad",
    "dieseq", "dieid", "diesequence", "diesequenceno", "toolsn", "toolid",
    "fieldx", "fieldy", "x", "y", "xmm", "ymm", "diex", "diey",
    "coordx", "coordy", "xcoordinate", "ycoordinate", "testflag", "mark", "head",
    "cursmefile", "cursmefilepath",
}


class MetadataLocksPanel(QFrame):
    def __init__(self, model, parent=None):
        super().__init__(parent, objectName="panel")
        self.model = model
        self.names = ()
        self.checks = {}
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(18, 14, 18, 14)
        self.layout.addWidget(QLabel("Metadata locks", objectName="subtitle"))
        hint = QLabel("Checked fields keep their source values during paste.\n"
                      "Unlock before changing row count; rows stay position-aligned.", objectName="hint")
        hint.setWordWrap(True)
        self.layout.addWidget(hint)
        model.changed.connect(self.refresh)
        model.metadata_locks_changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        names = tuple(name for name in self.model.source_headers()
                      if "".join(ch.lower() for ch in str(name) if ch.isalnum()) in METADATA_NAMES
                      or "path" in str(name).lower())
        if names != self.names:
            for check in self.checks.values():
                self.layout.removeWidget(check)
                check.deleteLater()
            self.names = names
            self.checks = {}
            for name in names:
                check = QCheckBox(str(name))
                check.setToolTip("Protect this source column from paste, cut and direct editing.")
                check.toggled.connect(self._toggle)
                self.layout.addWidget(check)
                self.checks[name] = check
        for name, check in self.checks.items():
            check.blockSignals(True)
            check.setChecked(name in self.model.clipboard_locks)
            check.blockSignals(False)
        self.setVisible(bool(names))

    def _toggle(self):
        self.model.set_clipboard_locks(name for name, check in self.checks.items() if check.isChecked())
