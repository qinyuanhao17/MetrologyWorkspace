"""Portable classification recipes; imports never change data participation."""
from copy import deepcopy
import json

import pandas as pd

from .match_groups import GroupPlan, flag_value, group_state, normalized, row_ids
from .selection_script import canonical_die

FIELDS = ('waferid', 'lotid', 'padname', 'dieseq')
OPTIONS = ('enabled', 'mark_enabled', 'head_names', 'mark_values', 'combined_groups',
           'group_order', 'show_wafer_groups', 'trend_order', 'use_group_card')


def _identities(raw):
    columns = {normalized(c):c for c in raw}
    if 'waferid' not in columns or 'dieseq' not in columns:
        raise ValueError('Group Script requires Wafer ID and Die Seq columns.')
    result = []
    for row in raw.to_dict('records'):
        values = [row.get(columns.get(c), '') for c in FIELDS]
        values = ['' if pd.isna(v) else str(v).strip() for v in values]
        values[-1] = canonical_die(values[-1])
        if not values[0] or not values[-1]:
            raise ValueError('Group Script requires non-empty Wafer ID and Die Seq.')
        result.append(tuple(values))
    return result


def export_group_script(raw, flags, state):
    state = group_state({k:v for k,v in state.items() if k not in ('applied','flags')})
    plan = GroupPlan(raw, flags, state)
    records = {}
    for identity, mark, flag in zip(_identities(raw), plan.marks, plan.flags):
        value = {'identity':list(identity), 'mark':mark, 'flag':flag}
        if identity in records and records[identity] != value:
            raise ValueError('Conflicting Groups for the same Wafer / Lot / PAD / Die.')
        records[identity] = value
    return json.dumps({'format':'metrology-group-script', 'version':1,
                       'definition':{k:state[k] for k in OPTIONS},
                       'records':list(records.values())}, ensure_ascii=False, indent=2)


def import_group_script(text, raw, current):
    try:
        script = json.loads(text)
        if (not isinstance(script, dict) or script.get('format') != 'metrology-group-script'
                or script.get('version') != 1 or not isinstance(script.get('definition'), dict)
                or set(script['definition']) != set(OPTIONS) or not isinstance(script.get('records'), list)):
            raise ValueError('Invalid Group Script format or version.')
        state = deepcopy(current)
        state.update(script['definition'])
        state['mark_rows'] = {}
        state = group_state(state)
        if any(type(state[k]) is not bool for k in ('enabled','mark_enabled','use_group_card')):
            raise ValueError('Invalid Group Script options.')
        known = {s['id'] for s in state['mark_values']}
        records = {}
        for record in script['records']:
            identity = record['identity']
            if (not isinstance(identity,list) or len(identity) != 4
                    or any(not isinstance(v,str) for v in identity) or record['mark'] not in known
                    or not isinstance(record['flag'],str)):
                raise ValueError('Invalid Group Script assignment.')
            identity = tuple(identity[:3]) + (canonical_die(identity[3]),)
            value = record['mark'], flag_value(record['flag'])
            if identity in records and records[identity] != value:
                raise ValueError('Conflicting Groups for the same Wafer / Lot / PAD / Die.')
            records[identity] = value
        identities = _identities(raw)
        missing = sum(identity not in records for identity in identities)
        if missing:
            raise ValueError(f'Group Script has no assignment for {missing} target rows; no changes applied.')
        state['mark_rows'] = {}
        flags = []
        for identity, identifier in zip(identities, row_ids(raw)):
            mark, flag = records[identity]
            state['mark_rows'].setdefault(mark, []).append(identifier)
            flags.append(flag)
        state.pop('flags', None)
        GroupPlan(raw, pd.DataFrame({'TestFlag':flags}), {k:v for k,v in state.items() if k != 'applied'})
        return state, pd.DataFrame({'TestFlag':flags})
    except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid Group Script. Paste a complete exported script.') from error


def open_group_script(controls):
    from PyQt6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
                                QPlainTextEdit, QPushButton, QVBoxLayout)
    class GroupScriptDialog(QDialog):
        def __init__(self):
            super().__init__(controls, objectName='groupScriptDialog')
            self.setWindowTitle('Group Script')
            self.resize(760,560)
            layout = QVBoxLayout(self)
            layout.addWidget(QLabel('Copy Groups to another window, or paste a script. Match by Wafer / Lot / PAD / Die.'))
            self.editor = QPlainTextEdit(objectName='groupScriptText')
            self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
            layout.addWidget(self.editor,1)
            self.message = QLabel(objectName='hint')
            self.message.setWordWrap(True)
            layout.addWidget(self.message)
            row = QHBoxLayout()
            for attr, label, slot in (
                ('copy_button','Copy Group Script',self.copy_script),
                ('paste_button','Paste from Clipboard',lambda:self.editor.setPlainText(QApplication.clipboard().text())),
                ('apply_button','Apply Script',self.apply_script),
                ('close_button','Close',self.hide)):
                button = QPushButton(label)
                if attr == 'apply_button':
                    button.setStyleSheet('QPushButton { background-color: #000000; color: #ffffff; '
                                        'border: 1px solid #000000; border-radius: 4px; padding: 6px 12px; } '
                                        'QPushButton:hover { background-color: #242424; } '
                                        'QPushButton:pressed { background-color: #404040; } '
                                        'QPushButton:focus { border: 2px solid #5b9bd5; } '
                                        'QPushButton:disabled { background-color: #767676; border-color: #767676; }')
                setattr(self,attr,button)
                button.clicked.connect(slot)
                row.addWidget(button)
            layout.addLayout(row)

        def refresh_script(self):
            try:
                self.editor.setPlainText(controls.group_script())
                self.message.clear()
                return True
            except ValueError as error:
                self.message.setText(str(error))
                return False

        def copy_script(self):
            if self.refresh_script():
                QApplication.clipboard().setText(self.editor.toPlainText())
                self.message.setText('Group script copied.')

        def apply_script(self):
            try:
                controls.apply_group_script(self.editor.toPlainText())
            except ValueError as error:
                self.message.setText(str(error))
            else:
                self.accept()

    if getattr(controls,'script_dialog',None) is None:
        controls.script_dialog = GroupScriptDialog()
    controls.script_dialog.refresh_script()
    controls.script_dialog.showNormal()
    controls.script_dialog.raise_()
    return controls.script_dialog
