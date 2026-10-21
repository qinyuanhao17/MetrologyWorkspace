Feature: Scoped floating editors and compact editable analysis exports
  Scenario: Compare Workbook changes without covering another application
    Given Raw Data is floating and a Workbook analysis window is active
    When I activate the Raw Data editor
    Then the analysis window remains above its Workbook
    And an unrelated application can cover the Raw Data editor when activated

  Scenario: Float an analysis source without creating a duplicate document
    Given a Wafer Map, Correlation and Trend, or Dynamic window
    When I double-click the measurement panel outside its table
    Then the same editor floats only above its own analysis window
    And double-clicking restores the editor with its data and Undo intact

  Scenario: Export the current composite Map and Radius grids
    Given both software pages have successfully drawn selected panels
    When I export Excel using either renderer
    Then FM contains the complete Copy PNG Wafer Map grid on the left
    And the complete Copy PNG Radius grid is top-aligned on the right
    And source measurements remain intact and unobscured

  Scenario: Export editable Dynamic Sigma without redundant Cycle panels
    Given Dynamic contains parameter Sigma results and live Cycle comparisons
    When I export Excel
    Then parameter Sigma charts are vertically arranged
    And the combined Sigma table and chart are to their right and top-aligned
    And original measurements feed editable pivots, Sigma formulas and native charts
    And Cycle line charts and their extra support tables are not exported
    But Cycle comparisons remain available in the software

  # Executable coverage: test_v411_float_scope.py, test_dynamic_compare_export.py,
  # test_export_template_layout.py, test_excel_report_layout.py; Windows z-order
  # and native Excel recalculation are additionally checked by owned QA scripts.
