"""Local Group editing for Correlation and Wafer Map, reusing Workbook rules."""
from copy import deepcopy

import pandas as pd
from PyQt6.QtCore import QObject, QSignalBlocker
from PyQt6.QtWidgets import QDialog, QMessageBox
from .match_group_ui import CombinedGroupDialog, GroupControls
from .match_groups import row_ids, participation_source_keys, copy_group_state
from .group_settings_ui import GroupSettingsDialog


class CorrelationOptions(QObject):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.is_wafer = owner.workspace_type == 'wafer_map'
        self.workbook_context = None
        self.has_workbook = False
        self.local_applied = False
        self.local_identities = None
        self._follow_disabled_without_data = False
        self._follow_user_choice = False
        self._context_cache = None
        self.dialog = None
        self.controls = GroupControls(owner)
        self.controls.restore({'mark_values':[{'id':n,'name':n} for n in ('POR','POR+','POR-')],
                               'mark_enabled':False})
        self.controls.hide()
        self.controls.apply_requested.connect(self.apply_groups)
        self.controls.changed.connect(owner.document.refresh_identity)
        menu = self.menu = owner.menuBar().addMenu('Groups')
        self.enabled = menu.addAction('Enable Groups')
        self.enabled.setCheckable(True)
        self.enabled.setChecked(True)
        self.enabled.setToolTip('Use Group captions and Trend order; source tables and Data selection stay unchanged.')
        self.enabled.toggled.connect(lambda _checked:self.refresh(presentation_only=True))
        self.follow_groups = menu.addAction('Use WKB Group settings')
        self.follow_groups.setCheckable(True)
        self.follow_groups.setChecked(True)
        self.follow_groups.setEnabled(False)
        self.follow_groups.toggled.connect(self._follow_groups_changed)
        self.copy_groups_action = menu.addAction('Copy WKB Groups')
        self.copy_groups_action.setEnabled(False)
        self.copy_groups_action.triggered.connect(self.copy_groups)
        self.settings_action = menu.addAction('Group settings…')
        self.settings_action.triggered.connect(self.open_groups)
        if not self.is_wafer:
            owner.manage_groups_action = menu.addAction('Manage groups…')
            owner.manage_groups_action.triggered.connect(self.manage_groups)
        menu.addSeparator()
        from .window import CheckMenu
        labels = CheckMenu(menu)
        labels.setTitle('Plot labels')
        menu.addMenu(labels)
        self.labels_enabled = labels.addAction('Enable Plot Labels')
        self.labels_enabled.setCheckable(True)
        self.labels_enabled.setChecked(True)
        self.labels_enabled.toggled.connect(self.apply_labels)
        self.follow_labels = labels.addAction('Use WKB Plot Labels')
        self.follow_labels.setCheckable(True)
        self.follow_labels.setChecked(True)
        self.follow_labels.setEnabled(False)
        self.follow_labels.toggled.connect(self.apply_labels)
        labels.addSeparator()
        self.label_checks = {}
        for key,text in (('pad','Show PAD'),('lot','Show Lot ID')):
            action = labels.addAction(text)
            action.setCheckable(True)
            action.setChecked(True)
            action.setToolTip('Wafer captions only; Group names and Data selection stay unchanged.')
            action.toggled.connect(self._local_label_changed)
            self.label_checks[key] = action
        self.workbook_labels = {'pad':True,'lot':True}
        # Public actions mirror the Workbook's controls for keyboard/UI callers.
        owner.group_controls = self.controls
        owner.groups_enabled_action = self.enabled
        owner.follow_workbook_groups_action = self.follow_groups
        owner.group_settings_action = self.settings_action
        owner.plot_labels_enabled_action = self.labels_enabled
        owner.follow_workbook_labels_action = self.follow_labels
        owner.plot_label_checks = self.label_checks

    def workbook_data_copied(self):
        return bool(getattr(self.owner, "_copy_from_wkb", False)
                    or getattr(self.owner, "_copy_reference_from_wkb", False))

    def set_workbook_data_copied(self, copied):
        """Keep follow defaults aligned with copied source data."""
        if copied:
            if self._follow_disabled_without_data and not self.local_applied:
                with QSignalBlocker(self.follow_groups):
                    self.follow_groups.setChecked(True)
                self._follow_disabled_without_data = False
                self._follow_user_choice = False
                self.settings_action.setEnabled(False)
                self.refresh()
            return
        if not self.local_applied and self.follow_groups.isChecked():
            with QSignalBlocker(self.follow_groups):
                self.follow_groups.setChecked(False)
            self._follow_disabled_without_data = True
            self._follow_user_choice = False
            self.settings_action.setEnabled(True)
        if not self.local_applied:
            self._context_cache = None
            for name in ("_match_groups", "_group_plan", "_group_result_cache"):
                if hasattr(self.owner, name):
                    setattr(self.owner, name, None)
            self.refresh()

    def set_source_test_flags(self, rows, value):
        """Keep an independent child's local Group settings on chart edits."""
        raw, reference = self.frames()
        if self.has_workbook and not self.local_applied:
            if self.workbook_context is not None:
                self._load_local_groups(self.workbook_context)
            else:
                self.local_applied = True
                self.local_identities = list(row_ids(raw))
            with QSignalBlocker(self.follow_groups):
                self.follow_groups.setChecked(False)
            self.settings_action.setEnabled(True)
            self._follow_user_choice = True
            self._follow_disabled_without_data = False
        self.controls.set_sources(reference, raw)
        self.controls.set_test_flags(rows, value)
        self.controls.accept_changes()
        if self.local_applied:
            self._context_cache = None
            self.refresh()

    def frames(self):
        reference = getattr(self.owner,'reference_model',None)
        return self.owner.model._analysis_view(),reference._analysis_view() if reference is not None else pd.DataFrame()

    def remember_workbook(self, context):
        self.workbook_context = context
        self.has_workbook = True
        if (getattr(self.owner, "_managed_owner", None) is not None
                and not self.workbook_data_copied() and not self.local_applied
                and not self._follow_user_choice and self.follow_groups.isChecked()):
            with QSignalBlocker(self.follow_groups):
                self.follow_groups.setChecked(False)
            self._follow_disabled_without_data = True
        self.follow_groups.setEnabled(True)
        self.copy_groups_action.setEnabled(context is not None)
        self.settings_action.setEnabled(not self.follow_groups.isChecked())
        if self.dialog is not None and self.follow_groups.isChecked():
            self.dialog.hide()

    def context(self, fallback):
        if self.has_workbook and self.follow_groups.isChecked():
            return self.workbook_context
        if not self.local_applied:
            return fallback
        owner = self.owner
        revisions = (owner.model.revision,getattr(getattr(owner,'reference_model',None),'revision',None))
        if self._context_cache is not None and self._context_cache[0] == revisions:
            return self._context_cache[1]
        raw,reference = self.frames()
        identities = list(row_ids(raw))
        if self.local_identities is not None and identities != self.local_identities:
            self.controls.status.setText('Group settings detached: source identities changed. Review TestFlags and Apply again.')
            return None
        self.controls.set_sources(reference,raw)
        state = deepcopy(self.controls.state)
        flags = state.get('applied',{}).get('flags',self.controls.flags_frame().iloc[:,0].tolist())
        result = {'grouping':state,'flags':list(flags),'identities':identities,
                  'provenance':list(participation_source_keys(raw))}
        self._context_cache = (revisions,result)
        return result

    def _follow_groups_changed(self, following):
        self._follow_user_choice = True
        if not following and self.has_workbook and not self.local_applied:
            context = self.workbook_context
            if context:
                self._load_local_groups(context)
        self.settings_action.setEnabled(not (following and self.has_workbook))
        if self.dialog is not None:
            self.controls.setEnabled(not (following and self.has_workbook))
            if following and self.has_workbook:
                self.dialog.hide()
        self._context_cache = None
        self.refresh()

    def _load_local_groups(self, context):
        state = deepcopy(context['grouping'])
        for config in (state, state.get('applied', {})):
            config['data_selection'] = {'records': [], 'excluded': []}
        self.controls.restore(state, pd.DataFrame({'TestFlag': context['flags']}))
        self.local_applied = True
        self.local_identities = list(context['identities'])

    def manage_groups(self):
        owner = self.owner
        plan = owner._group_plan
        if plan is None or not plan.enabled:
            QMessageBox.warning(owner, 'Groups unavailable',
                                'Enable Head groups or Mark in Group settings first.')
            return

        dialog = CombinedGroupDialog(plan, owner)
        try:
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            if not self.local_applied or self.follow_groups.isChecked():
                self._load_local_groups(owner._match_groups)
                with QSignalBlocker(self.follow_groups):
                    self.follow_groups.setChecked(False)
                self.settings_action.setEnabled(True)
            self.controls.set_display_groups(dialog.groups, sorted(dialog.show_wafer_groups))
            self._context_cache = None
            self.refresh()
        finally:
            dialog.deleteLater()

    def open_groups(self):
        if not self.settings_action.isEnabled():
            return
        owner = self.owner
        if owner.model.duplicate_header_count() or (hasattr(owner,'reference_model') and owner.reference_model.duplicate_header_count()):
            owner.statusBar().showMessage('Rename duplicate table headers before editing Groups.')
            return
        raw,reference = self.frames()
        self.controls.set_sources(reference,raw)
        if self.dialog is None:
            title = 'Wafer Map' if self.is_wafer else 'Correlation and Trend'
            self.dialog = GroupSettingsDialog(owner,self.controls,f'Group settings — {title}',trend=not self.is_wafer)
            self.order_view = self.dialog.table
        self.dialog.set_rows(raw)
        self.controls.show()
        self.dialog.showNormal()
        self.dialog.raise_()
        return self.dialog

    def apply_groups(self):
        owner = self.owner
        try:
            raw,reference = self.frames()
        except ValueError as error:
            self.controls.status.setText(str(error))
            return False
        if not reference.empty and len(reference)!=len(raw):
            self.controls.status.setText('Group settings require row-aligned Ref and Raw Data with equal row counts.')
            return False
        self.controls.set_sources(reference,raw)
        if self.controls.plan is None:
            return False
        self.controls.accept_changes()
        self.local_applied = True
        self.local_identities = list(row_ids(raw))
        self._follow_disabled_without_data = False
        with QSignalBlocker(self.follow_groups):
            self.follow_groups.setChecked(False)
        self.settings_action.setEnabled(True)
        self._context_cache = None
        if self.is_wafer:
            owner.update_plan()
        else:
            owner._group_result_cache = None
            owner._match_groups = self.context(None)
            owner._rebuild_source_analysis()
        owner.document.refresh_identity()
        if self.dialog is not None and self.dialog.isVisible():
            self.dialog.accept()
        return True

    def copy_groups(self):
        """Detach a fresh, explicit copy without modifying the Workbook."""
        context = self.workbook_context
        if context is None:
            return False
        try:
            raw,_ = self.frames()
        except ValueError as error:
            self.owner.statusBar().showMessage(str(error))
            return False
        if list(row_ids(raw)) != context['identities']:
            self.controls.status.setText('Cannot copy WKB Groups: source record identities differ.')
            self.owner.statusBar().showMessage(self.controls.status.text())
            return False
        state = deepcopy(context['grouping'])
        for config in (state,state.get('applied',{})):
            config['data_selection'] = {'records':[],'excluded':[]}
        self.controls.restore(state,pd.DataFrame({'TestFlag':context['flags']}))
        return self.apply_groups()

    def refresh(self, *, presentation_only=False):
        owner = self.owner
        if self.is_wafer:
            self._context_cache = None
            owner.update_plan()
            owner.document.refresh_identity()
            return
        if presentation_only:
            frame = owner._analysis_frame if owner._workbook_sources else owner._frame
            selection = owner._grouped_trend_selection(owner.selection)
            owner.sequence_page.set_input(frame, selection)
            if hasattr(owner, "wafer_statistics_page"):
                owner.wafer_statistics_page.set_input(frame, selection)
            owner.document.refresh_identity()
            return
        owner._group_result_cache = None
        owner._match_groups = self.context(owner._match_groups)
        owner._refresh_group_results()
        owner.update_plan()
        owner.document.refresh_identity()

    def set_workbook_labels(self, options):
        self.workbook_labels = dict(options)
        self.follow_labels.setEnabled(True)
        self.apply_labels()

    def _local_label_changed(self):
        with QSignalBlocker(self.follow_labels):
            self.follow_labels.setChecked(False)
        self.apply_labels()

    def apply_labels(self):
        values = (self.workbook_labels if self.follow_labels.isChecked()
                  else {key:action.isChecked() for key,action in self.label_checks.items()})
        if self.is_wafer:
            self.owner.update_plan()
        else:
            values = values if self.labels_enabled.isChecked() else {'pad':False,'lot':False}
            self.owner.sequence_page.set_identity_labels(values)
            self.owner.wafer_statistics_page.set_identity_labels(values)
        self.owner.document.refresh_identity()

    def snapshot(self, *, readonly=False):
        configured = self.local_applied or self.controls.pending
        saved = {'enabled':self.enabled.isChecked(),'follow_groups':self.follow_groups.isChecked(),
                'labels_enabled':self.labels_enabled.isChecked(),'follow_labels':self.follow_labels.isChecked(),
                'labels':{key:a.isChecked() for key,a in self.label_checks.items()},
                'workbook_labels':dict(self.workbook_labels),
                'local_applied':self.local_applied,'local_identities':deepcopy(self.local_identities),
                'grouping':deepcopy(self.controls.state) if configured else None,
                'flags':self.controls.flags_frame().iloc[:,0].tolist() if configured else []}
        if self.is_wafer:
            saved['workbook_context'] = (self.workbook_context if readonly else
                copy_group_state(self.workbook_context) if self.workbook_context is not None else None)
        return saved

    def restore(self, saved):
        if self.is_wafer and not self.has_workbook and saved.get('workbook_context'):
            self.remember_workbook(deepcopy(saved['workbook_context']))
        for key,action in (('enabled',self.enabled),('follow_groups',self.follow_groups),
                           ('labels_enabled',self.labels_enabled),('follow_labels',self.follow_labels)):
            with QSignalBlocker(action):
                action.setChecked(saved.get(key,True))
        for key,action in self.label_checks.items():
            with QSignalBlocker(action):
                action.setChecked(saved.get('labels',{}).get(key,True))
        self.local_applied = bool(saved.get('local_applied',False))
        self.local_identities = deepcopy(saved.get('local_identities'))
        if not self.follow_labels.isEnabled():
            self.workbook_labels = dict(saved.get('workbook_labels',{'pad':True,'lot':True}))
        self.controls.restore(saved.get('grouping') or {'mark_values':[{'id':n,'name':n} for n in ('POR','POR+','POR-')],
                              'mark_enabled':False},pd.DataFrame({'TestFlag':saved.get('flags',[])}))
        self._context_cache = None
        self.settings_action.setEnabled(not (self.has_workbook and self.follow_groups.isChecked()))
        self.apply_labels()

    def decorate_wafer_selection(self, selection):
        """Group captions only: leave every wafer key, row and plot cell intact."""
        from .match_groups import GroupPlan, normalized
        if self.owner.model.duplicate_header_count():
            return  # Preserve the editable draft and its last valid plot plan.
        raw,_ = self.frames()
        context = self.context(None)
        plan = None
        if self.enabled.isChecked() and context is not None:
            try:
                plan = GroupPlan(raw,pd.DataFrame({'TestFlag':context['flags']}),context['grouping'])
            except ValueError as error:
                self.controls.status.setText(str(error))
        names = {normalized(c):c for c in raw}
        for target,aliases in (('waferid',('wafer','waferno')),('lotid',('lot','lotno')),('padname',('pad','slot'))):
            if target not in names:
                alias = next((name for name in aliases if name in names),None)
                if alias is not None:
                    names[target] = names[alias]
        options = self.workbook_labels if self.follow_labels.isChecked() else {k:a.isChecked() for k,a in self.label_checks.items()}
        columns = {field:raw[names[field]].astype(str).str.strip().tolist()
                   for field in ('waferid','lotid','padname') if field in names}
        labels, caption_fields = {}, {}
        for key,rows in selection['groups'].items():
            if not rows:
                continue
            groups = list(dict.fromkeys(plan.labels[i] for i in rows if plan.enabled and plan.labels[i])) if plan else []
            fields = {'group':', '.join(groups)} if groups else {}
            for field in ('waferid','lotid','padname'):
                if field != 'waferid' and (not self.labels_enabled.isChecked() or not options.get('lot' if field=='lotid' else 'pad',True)):
                    continue
                if field in names:
                    fields[{'waferid':'wafer','lotid':'lot','padname':'pad'}[field]] = ', '.join(dict.fromkeys(
                        columns[field][row] for row in rows if columns[field][row]))
            labels[key] = ' · '.join(p for p in fields.values() if p) or selection['labels'].get(key,key)
            caption_fields[key] = fields if any(fields.values()) else {'wafer':labels[key]}
        selection['labels'] = labels
        selection['caption_fields'] = caption_fields
        from PyQt6.QtCore import Qt
        with QSignalBlocker(self.owner.wafer_list):
            for i in range(self.owner.wafer_list.topLevelItemCount()):
                item = self.owner.wafer_list.topLevelItem(i)
                item.setText(0,labels.get(item.data(0,Qt.ItemDataRole.UserRole),item.text(0)))
