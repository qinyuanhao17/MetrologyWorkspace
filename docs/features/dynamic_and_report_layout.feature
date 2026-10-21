Feature: Dynamic comparison and editable reports
  Scenario: Float the live Dynamic measurement editor
    Given a Dynamic window with editable measurement data
    When I double-click empty space in its Measurement table panel
    Then the same editor floats above only that Dynamic window
    And editing and Undo still affect the same measurement document
    When I double-click empty space again
    Then the editor returns to its original location

  Scenario Outline: Compare parameters with different magnitudes
    Given Dynamic Trend is in <mode> mode
    When I add another parameter with Add Compare
    Then each parameter has its own Y axis
    And dies of the same parameter share that axis
    And values are unchanged in the plot, live updates and PNG export
    Examples:
      | mode       |
      | Single Die |
      | All Dies   |

  Scenario: Export every Match view using the supplied example
    Given a workbook with several parameters, wafers and groups
    When I export native Excel or Matplotlib Excel
    Then every Match sheet has horizontal parameter tables at the top
    And each parameter's Match, Trend and Bias panels are below the tables
    And Original holds one unchanged source table to the right
    And the other views link to those original source rows

  Scenario: Export saved Dynamic and FM results without opening child windows
    Given saved Dynamic data and successful Map and Radius selections
    When I export the workbook with those child windows closed
    Then Dynamic source cells, pivots and native charts remain editable in Excel
    And native Dynamic axes refit when edited source values change
    And each FM sheet includes Map and Radius PNGs no higher than 7.5 cm or wider than 18 cm
    And export does not accept drafts or alter the workbook's source data

# Executable coverage: tests/test_dynamic_compare_export.py,
# tests/test_export_template_layout.py, tests/test_excel_export.py and
# tests/test_excel_report_layout.py. Source-fixture and native Excel QA are
# documented in the implementation verification record.
