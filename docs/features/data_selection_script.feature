Feature: Share source participation between analysis windows
  Engineers can reuse their selection without changing source measurements.

  Rule: A selection script carries the complete selection draft

    Scenario: Transfer a selection to another ordering of the same sources
      Given source records have checked and unchecked participation
      And the selection has filter rows with AND and OR conditions
      And it has search, row visibility and Hide excluded rows settings
      When the engineer copies the Selection Script and applies it in another window
      Then conditions and view settings are retained
      And participation follows source identity rather than the displayed row number
      And identity uses only Wafer ID, Lot ID, PAD Name and Die
      And changed SME names and paths do not affect the transferred selection
      And source values remain unchanged

    Scenario: Keep the copied recipe current
      Given the Selection Script panel is open
      When the engineer changes a filter, participation or a view setting
      Then the script reflects that draft
      And cancelling Data selection leaves the owning window unchanged

    Scenario: Refuse an incompatible script without losing the current selection
      Given a window already has a selection
      When an imported script uses an unavailable column or source record
      Or it has an unsupported version or invalid checkbox values
      Then an explanation is displayed
      And the current selection remains unchanged

  Rule: Workbook selection remains shared until the child accepts a local change

    Scenario: Inspect the parent selection and then change it locally
      Given a child follows Match Workbook selection
      When the engineer opens its Data selection
      Then the filters, checked states and Hide excluded rows match the Workbook
      When the engineer accepts a changed selection in the child
      Then the child switches to Full data and applies its own selection
      And the parent selection and complete source tables remain unchanged

  Rule: Spectra participation controls plotted files and export

    Scenario: Apply participation in Spectra Viewer
      Given multiple channels belong to one SME file
      When the engineer opens Data selection from the Data menu
      Then that SME appears once
      When the engineer changes participation and chooses Apply
      Then the corresponding spectrum tree checks and curves update
      And the selection view survives saving and reopening a Spectra file

    Scenario: Export only checked original SME files
      Given checked and unchecked spectra reside in source folders
      When the engineer chooses Export Checked Spectra
      Then only checked existing SME files are copied into their source folder hierarchy
      And their bytes are unchanged and can be loaded again
      And missing sources or existing destination files are reported before copying
      And no SME file is generated from reconstructed measurements

  Rule: Die Maps retain all sites and share only compatible layouts

    Scenario: Select and toggle unchecked sites without rebuilding the page
      Given checked sites are blue and unchecked sites are light gray
      When the engineer left-drags a rectangle inside one Die Map
      Then every enclosed site is selected including unchecked sites
      When the engineer double-clicks a site
      Then its spectrum check state toggles
      And the existing plots, labels, sizes and axes remain in place

    Scenario: Share participation with matching Die layouts
      Given the current wafer has a consistent checkbox state for each Die
      When the engineer chooses Apply to Similar Wafer
      Then only wafers with the same Die ID set receive that participation
      And every corresponding X and Y difference must be less than 0.4 mm
      And source coordinates and measurement values remain unchanged

  # Executable scenarios: tests.test_selection_script,
  # tests.test_workbook_copy_data and tests.test_spectra_workbook.
