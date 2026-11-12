"""Spectra-owned classification using Workbook Group/Mark rules, never participation."""
from collections import defaultdict
from copy import deepcopy
import re

import pandas as pd

from .match_groups import GroupPlan, applied_state, group_state, normalized, row_ids
from .selection_script import canonical_die
from .sme_spectra import file_metadata_dataframe


def _identity(source):
    value = source.identity
    return [value.wafer.strip(), value.lot.strip(), value.pad.strip(), canonical_die(value.die_seq)]


def _definition(state):
    state = applied_state(state)
    state.pop('applied', None)
    state['filters'], state['sort'] = [], []
    state['data_selection'] = {'records':[], 'excluded':[]}
    return state


def empty_groups():
    definition = _definition(None)
    definition['mark_values'] = [{'id':name,'name':name} for name in ('POR','POR+','POR-')]
    return {'enabled':True, 'definition':definition, 'records':{}}


def validate_groups(saved):
    if saved is None:
        return empty_groups()
    if (not isinstance(saved, dict) or type(saved.get('enabled')) is not bool
            or not isinstance(saved.get('definition'),dict)):
        raise ValueError('Invalid Spectra Group settings.')
    definition = _definition(saved.get('definition'))
    marks = {spec['id'] for spec in definition['mark_values']}
    records = saved.get('records')
    if not isinstance(records, dict):
        raise ValueError('Invalid Spectra Group assignments.')
    for key, record in records.items():
        if (not isinstance(key,str) or not isinstance(record,dict)
                or not isinstance(record.get('identity'),list) or len(record['identity']) != 4
                or not all(isinstance(v,str) for v in record['identity'])
                or not isinstance(record.get('mark'),str) or record['mark'] not in marks
                or not isinstance(record.get('flag'),str)
                or (record['flag'] and not re.fullmatch(r'[+-]?\d+',record['flag']))):
            raise ValueError('Invalid Spectra Group assignment identity, Mark or TestFlag.')
    return {'enabled':saved['enabled'], 'definition':definition, 'records':deepcopy(records)}


def copied_groups(raw, flags, state, spectra):
    """Copy accepted classification by Wafer/Lot/PAD/Die, rejecting ambiguous identities."""
    names = {normalized(c):c for c in raw}
    required = ('waferid','lotid','padname','dieseq')
    if any(name not in names for name in required):
        raise ValueError('WKB Groups require Wafer ID, Lot ID, PAD Name and Die Seq.')
    definition = _definition(state)
    plan = GroupPlan(raw, flags, definition)
    lookup = {}
    for i, values in enumerate(raw[[names[name] for name in required]].itertuples(index=False,name=None)):
        key = tuple('' if pd.isna(v) else str(v).strip() for v in values[:3]) + (canonical_die(values[3]),)
        value = (plan.marks[i], plan.flags[i])
        if key in lookup and lookup[key] != value:
            raise ValueError('WKB has conflicting Groups for the same Wafer/Lot/PAD/Die: ' + ' / '.join(key))
        lookup[key] = value
    records = {}
    spectra = tuple(spectra)
    for source in spectra:
        identity = _identity(source)
        if tuple(identity) in lookup:
            mark, flag = lookup[tuple(identity)]
            records[source.key] = {'identity':identity, 'mark':mark, 'flag':flag}
    definition['mark_rows'] = {}
    definition.pop('flags',None)
    return {'enabled':True,'definition':definition,'records':records}, {
        'matched':len(records), 'unmatched':len(spectra)-len(records)}


def materialized_groups(spectra, saved, test_flags=None):
    """Adapt durable source-key records to the existing GroupControls/GroupPlan seam."""
    spectra = tuple(spectra)
    frame = file_metadata_dataframe(spectra)
    state = _definition(saved['definition'])
    rows, flags = defaultdict(list), []
    for source, identifier in zip(spectra,row_ids(frame)):
        record = saved['records'].get(source.key)
        record = record if record and record['identity'] == _identity(source) else None
        flags.append(str(test_flags.get(source.key,0)) if test_flags is not None else record['flag'] if record else '0')
        if record:
            rows[record['mark']].append(identifier)
    state['mark_rows'], state['flags'] = dict(rows), flags
    return frame, state, pd.DataFrame({'TestFlag':flags})


def display_groups(spectra, saved, test_flags=None):
    spectra = tuple(spectra)
    if not saved['enabled'] or not saved['records']:
        return {}
    frame, state, flags = materialized_groups(spectra,saved,test_flags)
    plan = GroupPlan(frame,flags,state)
    combined = defaultdict(list)
    for spec in state['combined_groups']:
        for row in plan.rows(spec['id']):
            combined[row].append(spec['name'])
    result = {}
    for i, source in enumerate(spectra):
        record = saved['records'].get(source.key)
        if record and record['identity'] == _identity(source):
            groups = [plan.labels[i]] if plan.enabled else []
            groups.extend(combined[i])
            result[source.key] = {'mark':plan.mark_names[plan.marks[i]] if plan.mark_enabled else '',
                                  'group':' / '.join(dict.fromkeys(groups))}
    return result


class SpectraGroupOptions:
    """One local Group draft; Workbook copying never changes spectral participation."""
    def __init__(self, owner):
        self.owner, self.source = owner, None
        self.saved, self._cache = empty_groups(), None
        self.dialog = None
        menu = owner.menuBar().addMenu('Groups')
        self.enabled_action = menu.addAction('Enable Groups')
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)
        self.enabled_action.toggled.connect(self._enable)
        self.copy_action = menu.addAction('Copy WKB Groups')
        self.copy_action.setEnabled(False)
        self.copy_action.triggered.connect(self.copy_from_workbook)
        self.settings_action = menu.addAction('Group settings…')
        self.settings_action.triggered.connect(self.open_settings)

    def reset(self):
        self.saved, self._cache = empty_groups(), None
        from PyQt6.QtCore import QSignalBlocker
        with QSignalBlocker(self.enabled_action):
            self.enabled_action.setChecked(True)
        if self.dialog is not None:
            self.dialog.close()

    def snapshot(self):
        return deepcopy(self.saved)

    def restore(self, saved):
        from PyQt6.QtCore import QSignalBlocker
        self.saved, self._cache = validate_groups(saved), None
        with QSignalBlocker(self.enabled_action):
            self.enabled_action.setChecked(self.saved['enabled'])
        if self.dialog is not None:
            frame,state,flags = materialized_groups(self.owner.catalog.spectra,self.saved,self.owner.test_flags)
            state.pop('flags',None)  # The editable flag model is the single UI source.
            self.controls.restore(state,flags)
            self.controls.set_sources(pd.DataFrame(),frame)
        self.owner.refresh_group_labels()

    def commit(self, saved, title, flags=None):
        saved = validate_groups(saved)
        before = self.snapshot()
        previous_flags = dict(self.owner.test_flags)
        next_flags = previous_flags if flags is None else {k:int(v) for k,v in flags.items() if int(v)}
        def apply(settings, values):
            self.owner.test_flags = dict(values)
            self.owner.test_flag_values = list(dict.fromkeys((*self.owner.test_flag_values,*values.values())))
            self.restore(settings)
        if before != saved or previous_flags != next_flags:
            self.owner.record_edit(title, lambda:apply(before,previous_flags), lambda:apply(saved,next_flags))

    def flags_changed(self):
        self._cache = None
        if self.dialog is not None:
            self.controls.order_model.load(pd.DataFrame({'TestFlag':[
                str(self.owner.test_flags.get(s.key,0)) for s in self.owner.catalog.spectra]}))
        self.owner.refresh_group_labels()

    def _enable(self, checked):
        saved = self.snapshot()
        saved['enabled'] = checked
        self.commit(saved,'Show Groups')

    def set_source(self, source):
        self.source = source
        self.refresh_enabled()

    def refresh_enabled(self):
        loaded = bool(self.owner.catalog.spectra)
        self.copy_action.setEnabled(self.source is not None and loaded)
        self.settings_action.setEnabled(loaded)

    def copy_from_workbook(self):
        from PyQt6.QtWidgets import QMessageBox
        if self.source is None:
            return False
        try:
            saved, report = copied_groups(*self.source(), self.owner.catalog.spectra)
            flags = dict(self.owner.test_flags)
            flags.update({key:int(record['flag'] or 0) for key,record in saved['records'].items()})
            self.commit(saved,'Copy WKB Groups',flags)
        except ValueError as error:
            QMessageBox.warning(self.owner,'Cannot copy WKB Groups',str(error))
            return False
        self.owner.status.setText(f"Copied WKB Groups to {report['matched']} spectra; {report['unmatched']} unmatched spectra remain unassigned.")
        return True

    def labels(self):
        sources = self.owner.catalog.spectra
        if self._cache is None or self._cache[0] is not sources:
            labels = display_groups(sources,self.saved,self.owner.test_flags)
            members = defaultdict(set)
            for source in sources:
                i = source.identity
                members[(i.wafer,i.lot,i.pad)].add(source.key)
            self._cache = sources, labels, members
        return self._cache[1]

    def mark_caption(self, keys):
        labels = self.labels()
        values = {labels[key]['mark'] for key in keys if key in labels and labels[key]['mark']}
        if not values:
            return ''
        names = [spec['name'] for spec in self.saved['definition']['mark_values'] if spec['name'] in values]
        if any(key not in labels for key in keys):
            names.append('Unassigned')
        return ', '.join(names)

    def legend_label(self, key):
        self.labels()
        keys = {key.spectrum_key} if key.spectrum_key else self._cache[2].get((key.wafer,key.lot,key.pad),())
        prefix = self.mark_caption(keys)
        return f'{prefix} | {key.legend_label}' if prefix else key.legend_label

    def assign_mark(self, keys, mark):
        sources = self.owner.catalog.spectra
        saved = self.snapshot()
        if mark not in {spec['id'] for spec in saved['definition']['mark_values']}:
            raise ValueError('Unknown Mark.')
        if not saved['records']:
            fallback = saved['definition']['mark_values'][0]['id']
            saved['records'] = {s.key:{'identity':_identity(s),'mark':fallback,'flag':'0'} for s in sources}
        for source in sources:
            if source.key in keys:
                previous = saved['records'].get(source.key,{})
                saved['records'][source.key] = {'identity':_identity(source),'mark':mark,'flag':previous.get('flag','0')}
        saved['enabled'], saved['definition']['mark_enabled'] = True, True
        self.commit(saved,'Set Mark')

    def add_named_mark(self, keys, name, *, append=False):
        from uuid import uuid4
        name = name.strip()
        if not name:
            raise ValueError('Use a non-empty Mark name.')
        saved = self.snapshot()
        specs = saved['definition']['mark_values']
        names = {s['id']:s['name'] for s in specs}
        fallback = specs[0]['id']
        for source in self.owner.catalog.spectra:
            record = saved['records'].setdefault(source.key,{'identity':_identity(source),'mark':fallback,'flag':'0'})
            if source.key not in keys:
                continue
            parts = names[record['mark']].split('/') if append else []
            label = '/'.join(dict.fromkeys((*parts,name)))
            spec = next((s for s in specs if s['name'].casefold() == label.casefold()),None)
            if spec is None:
                spec = {'id':uuid4().hex,'name':label}
                specs.append(spec)
                names[spec['id']] = label
            record['mark'] = spec['id']
        saved['enabled'], saved['definition']['mark_enabled'] = True, True
        self.commit(saved,'Append Mark' if append else 'Replace Mark')

    def add_mark(self):
        from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QRadioButton, QHBoxLayout
        dialog = QDialog(self.owner)
        dialog.setWindowTitle('Add Mark')
        form = QFormLayout(dialog)
        name = QLineEdit()
        form.addRow('Mark name',name)
        row = QHBoxLayout()
        replace, append = QRadioButton('Replace'), QRadioButton('Append')
        replace.setChecked(True)
        row.addWidget(replace)
        row.addWidget(append)
        form.addRow('Assignment',row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        name.textChanged.connect(lambda text:buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(text.strip())))
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_named_mark(self.owner._selected_keys,name.text(),append=append.isChecked())
        dialog.deleteLater()

    def mark_menu(self, parent):
        menu = parent.addMenu('Set Mark')
        keys = self.owner._selected_keys
        menu.setEnabled(bool(keys))
        for spec in self.saved['definition']['mark_values']:
            menu.addAction(spec['name'],lambda _=False, mark=spec['id']:self.assign_mark(keys,mark))
        menu.addSeparator()
        menu.addAction('Add Mark…',self.add_mark)
        return menu

    def open_settings(self):
        from .group_settings_ui import GroupSettingsDialog
        from .match_group_ui import GroupControls
        if self.dialog is None:
            self.controls = GroupControls(self.owner)
            self.dialog = GroupSettingsDialog(self.owner,self.controls,'Group settings — Spectra Viewer',
                trend=False,hint='Test Flag is shared with Spectra Info. Edit flags below, then Apply.')
            self.controls.apply_requested.connect(self.apply_settings)
            self.details = self.dialog.table
        frame,state,flags = materialized_groups(self.owner.catalog.spectra,self.saved,self.owner.test_flags)
        state.pop('flags',None)
        self.controls.restore(state,flags)
        self.controls.set_sources(pd.DataFrame(),frame)
        self.details_model = self.dialog.set_rows(frame)
        self.dialog.showNormal()
        self.dialog.raise_()
        return self.dialog

    def apply_settings(self):
        self.controls.accept_changes()
        definition = _definition(self.controls.state)
        frame = file_metadata_dataframe(self.owner.catalog.spectra)
        plan = GroupPlan(frame,self.controls.flags_frame(),definition)
        records = {s.key:{'identity':_identity(s),'mark':plan.marks[i],'flag':plan.flags[i]}
                   for i,s in enumerate(self.owner.catalog.spectra)}
        definition['mark_rows'] = {}
        definition.pop('flags',None)
        self.commit({'enabled':True,'definition':definition,'records':records},'Apply Group settings',
                    {key:int(record['flag'] or 0) for key,record in records.items()})
