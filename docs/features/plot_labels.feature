Feature: Choose measurement labels without changing analysis
  Engineers can simplify plot captions while retaining all measurement identities.
  Executable coverage: tests.test_plot_labels.

  Scenario: Identify visible wafer metadata explicitly
    Given wafer W001 has Lot L001 and PAD ARRAY
    When its Lot ID and PAD are displayed in the plots
    Then the wafer captions contain "LOT: L001" and "PAD: ARRAY"
    And the source identity and Group labels are unchanged

  Scenario: Hide Lot and PAD in original table order
    Given wafer W001 has two separate measurements with Lot L001 and L002
    When Lot ID and PAD are hidden in Trend, Wafer Map and Radius
    Then both measurements remain plotted with the same observations and selections
    And only their wafer identity captions become W001

  Scenario: Groups keep their classification labels
    Given a Group is named Optical A and displays its wafers
    When PAD is hidden from wafer captions
    Then Optical A and its group boundaries remain unchanged
    And only the wafer captions omit PAD

  Scenario: Save plot label choices
    Given a Match Workbook hides Lot ID in Trend only
    When the Workbook is saved and reopened
    Then Trend still hides Lot ID and Wafer Map and Radius still display it

  Scenario: Parameter captions identify the mapped parameter
    Given Parameter Depth maps to source column CD Raw
    When Match and Trend are plotted
    Then the Match title is Depth
    And each Trend Y label matches its title
