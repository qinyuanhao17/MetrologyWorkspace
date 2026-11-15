Feature: Optional Groups and wafer captions in Correlation and Trend
  Engineers can reuse Workbook classification rules without making every
  independent analysis follow one Workbook's presentation choices.

  Scenario: Use the same Mark vocabulary and explicit one-time copy
    Given a new independent Correlation or Wafer Map workspace
    Then the Mark vocabulary starts with POR as fallback followed by POR+ and POR-
    And the compact Group table identifies Wafer, Lot, PAD and Die
    When the engineer appends POR to an existing Old assignment
    Then Old/POR becomes a real named Mark used by Groups
    When the engineer copies WKB Groups once
    Then later Workbook edits do not overwrite local classification
    And saved custom Mark names survive reopening

  Scenario: Protect Correlation input metadata while replacing measurements
    Given Reference and Raw Data tables have original source identity strings
    When the engineer locks an identity column and pastes measurements
    Then its header, values and row positions remain unchanged
    And unlocked measurement cells can change and be undone
    And locks remain visible and usable after saving and reopening

  Scenario: Show Wafer classification without changing plotted populations
    Given a Wafer Map has prepared data and configured Groups
    When the engineer toggles Groups or changes its Mark labels
    Then the second title line shows Group, Wafer, Lot and PAD in that order
    And original wafer keys, participating rows and prepared surfaces remain
    And no wafer is split into multiple maps
    And the third line includes measured point Sigma using population standard deviation

  Scenario: Plot all selected parameters within the per-page map budget
    Given 89 participating wafers and 24 selected parameters
    When the engineer draws all selected map boxes
    Then pages contain at most 5 wafers and retain all 24 parameters
    And all 89 wafers remain reachable once across 18 pages

  # Executable parity/locking/caption/pagination checks: tests.test_workspace_group_parity.

  Scenario: Configure Groups in an independent analysis
    Given row-aligned Reference and Raw Data tables
    When the engineer assigns TestFlags and applies Head or Mark settings
    Then Trend uses the shared Group and wafer ordering rules
    When the engineer disables Groups
    Then ordinary measurement ordering and captions are used
    And participation and source strings are unchanged
    When the engineer enables Groups again
    Then the saved classification becomes visible again

  Scenario: Change wafer captions without replacing curves
    Given a Trend has been drawn and zoomed
    When the engineer hides PAD or Lot ID in Plot labels
    Then wafer captions change in place and the curves and view ranges remain
    And Group names, identities and participation remain unchanged

  # Executable checks: tests.test_plot_labels and tests.test_workspace_group_parity.
  Scenario: Hide map and radius metadata independently
    Given Wafer Map and Radius plots show Group, Wafer, Lot and PAD captions
    When the engineer hides PAD in maps and Lot in radius plots
    Then each view and its export omit only the requested identity fields
    And literal Group and Wafer names containing metadata prefixes or separators remain intact
    And prepared surfaces, plotted values, selected boxes and source strings remain unchanged

  Scenario: Keep copied Group settings independent of the clean document
    Given a Wafer child follows accepted Workbook Groups
    When a consumer modifies an exported workspace snapshot
    Then the live Group settings and accepted clean baseline retain their original values
    And the clean document does not acquire an edit from that external copy

  Scenario: Choose whether a child follows Workbook settings
    Given Correlation and Trend belongs to a Match Workbook
    When the engineer disables Use WKB Group settings and applies local names
    Then the child uses its local Group configuration without changing its parent
    When the engineer enables Use WKB Group settings
    Then the current Workbook classification is used again
    And the child can choose Plot Label following independently

  Scenario: Restore saved options and protect source ownership
    Given local classification and disabled display switches have been saved
    When the independent workspace or owning Workbook is reopened
    Then the switches, TestFlags and classification settings are restored
    When different source identities replace Raw Data with the same row count
    Then old TestFlags are not silently assigned to the replacement records
