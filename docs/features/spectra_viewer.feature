Feature: Review spectral measurements by wafer
  Metrology engineers need to load SME spectra from nested folders, compare
  channels, and connect spectra to physical wafer positions without losing
  source identity or blocking the workspace.

  Rule: The spectrum tree preserves declared wafer identity

    Scenario: Load the supplied SME batch
      Given the engineer has the supplied nested SME folders
      When the engineer loads the folders
      Then every readable spectrum appears under its Wafer, Lot and Pad
      And spectra within a Pad are ordered by Die Seq
      And unreadable files are reported without hiding readable spectra

    Scenario: Open a PAD before its spectrum rows are created
      Given the Wafer and Lot branches are open
      And a PAD contains spectra whose rows have not yet been displayed
      When the engineer clicks the PAD expansion arrow
      Then the PAD opens and shows its spectra in Die order
      When the engineer closes and reopens the PAD
      Then the same spectrum rows appear without duplicates

  Rule: Internal SME names preserve business metadata

    Scenario: Reclassify spectra without changing their participation
      Given spectra are checked and selected with a plot zoom in place
      When the engineer chooses Wafer ID, Lot, PAD Name or Die under Filter By
      Then the chosen field becomes the first tree grouping
      And remaining source identities are retained in lower groups
      And checked and selected spectra and plot ranges stay unchanged

    Scenario: Count available angular channels once
      Given several spectra share an instrument and AOI/AZI combination
      When their summary is displayed
      Then that combination counts as one channel across all files and Dies
      And channels without angle metadata use the instrument and Channel ID
      And completed loading statistics are shown only below the tree

    Scenario: Review all source metadata without leaving the tree
      Given the engineer has loaded spectra
      When the engineer expands a Pad
      Then each spectrum row shows its Wafer, SME name, Lot, Tool SN and PAD
      And the row also shows Die Seq, FIELD X/Y, time, folder and channel identity
      And there is no separate file-count column

    Scenario: New naming identifies Tool SN and PAD separately
      Given an SME named "AIT0200.00-01_AIT0200.15_A03-090_CELL-45_Die1_C-1_R5"
      When the engineer loads it
      Then its Wafer is "AIT0200.00-01"
      And its Tool SN is "A03-090"
      And its PAD is "CELL-45"
      And its FIELD coordinates are "-1" and "5"

    Scenario: Legacy naming uses the date as PAD
      Given an SME named "AIT0080.00-22_AIT0080.42_A03-090_2026-8-21-10-53-55_Die1_C-3_R4"
      When the engineer loads it
      Then its Tool SN is "A03-090"
      And its PAD is "2026-8-21-10-53-55"

    Scenario: Keep spectrum rows concise
      Given the engineer has loaded spectra with measurement times
      When the engineer expands a Pad
      Then each spectrum is labelled by its Die number
      And its original measurement time remains available in the Time column

  Rule: Only selected spectra are plotted

    Scenario: Select one measurement from a Pad
      Given a Pad contains multiple spectrum files
      When the engineer checks one spectrum
      Then only that spectrum contributes curves to the display
      And the other files remain available in the tree

  Rule: Plotted channels can be compared or suppressed

    Scenario: Distinguish wafers sharing the same channels
      Given different wafers contain the same instrument channels
      When the engineer checks those spectra
      Then each wafer and channel combination has a distinct curve colour
      And matching legends include the wafer name
      And colours stay stable when checking again or changing classification
      And hiding one legend entry affects only that wafer and channel
      And the physical channel count does not multiply by the number of wafers

    Scenario: Choose plot blocks from the Options menu
      Given the engineer has checked one or more spectra
      When the engineer clears N under Options and Views
      Then the N block is removed from the layout
      And the remaining blocks expand into the available space
      And the view choices stay open for further changes
      And the legend section is hidden when all of its plots are disabled

    Scenario: Hide a channel
      Given several checked spectra contain the same instrument channel
      When the engineer double-clicks its channel legend
      Then all curves for that channel are hidden
      When the engineer double-clicks the legend again
      Then the curves are restored

  Rule: Large selections remain manageable

    Scenario: Delete only selected spectrum branches from the session
      Given one or more spectrum rows or folded classification branches are selected
      When the engineer chooses Delete Tree
      Then only those spectra are removed from the session and linked plots and maps
      And source files on disk remain unchanged
      And Delete Tree is disabled when no spectra are selected

    Scenario: Check and collapse the spectrum collection
      Given several Wafer branches are available
      When the engineer chooses Check All Spectra from the tree menu
      Then every spectrum becomes selected for drawing
      When the engineer folds the tree
      Then every Wafer branch is collapsed
      When the engineer unfolds the tree
      Then the Wafer, Lot and Pad branches are visible again

  Rule: An individual plot can be inspected closely

    Scenario: Edit axes from the native plot menu
      Given spectra are plotted in the main window or a floating copy
      When the engineer right-clicks the plotting area
      Then the native View All, X axis, Y axis and Mouse Mode menu is available
      And manual axis ranges update that plot
      When the engineer chooses View All
      Then the full measured wavelength range is restored without extra X padding

    Scenario: Zoom and enlarge a plot
      Given the engineer has drawn at least one plot
      When the engineer drags a rectangle inside it
      Then the chart zooms to that rectangle
      And the Auto Range button remains available in the corner
      When the engineer double-clicks the plot
      Then an enlarged floating copy opens

    Scenario: Align measurement plot axes
      Given N, C, S, Psi Delta and Reflectance plots are visible
      When the engineer compares their frames
      Then every plot has a complete four-sided axis frame
      And their X axes have the same visible length
      And their horizontal-axis title remains Wavelength (nm)
      And they do not repeat a Y-axis title

    Scenario: Compare channels on white plots with tight wavelength limits
      Given several instrument channels are plotted
      When the engineer compares the plots
      Then plot backgrounds are white
      And channel colours follow the Tableau Category10 palette
      And channel colours agree between the legend and every plot
      And AOI and AZI labels use whole degrees without changing channel identity
      And wavelength limits span the visible data without extra padding

    Scenario: Connect a curve to its wafer position
      Given checked spectra are visible in plots and wafer maps
      When the engineer selects a spectrum curve
      Then that spectrum is highlighted in the plots, tree and wafer map
      When the engineer clicks a blank part of a plot
      Then those highlights are cleared without changing the checked spectra

    Scenario: Clear linked selection from chart whitespace
      Given spectra are selected in the tree, main plots, floating plots and wafer maps
      When the engineer clicks blank space in a wafer map or a chart window
      Then every linked selection and highlight is cleared
      And the same applies to the blank space around the chart panels
      And checked spectra and current plot ranges stay unchanged
      And clicks on measurement points and Ctrl multi-selection still work

    Scenario: Review several spectra together
      Given several spectra are available in the tree and wafer maps
      When the engineer selects spectra with Ctrl and clicks a selected spectrum again
      Then that spectrum leaves the selection while the others remain highlighted
      And the selection agrees between the tree, plots and wafer maps
      When the engineer extends a tree selection with Shift
      Then the intervening spectrum rows are also selected

    Scenario: Change participation for selected spectra
      Given several spectra or Wafer, Lot and PAD branches are selected
      When the engineer chooses Uncheck Selected from a tree or wafer-map menu
      Then only the selected spectra stop contributing curves and wafer points
      And the selection remains available for Check Selected
      When the engineer chooses Check Selected
      Then those spectra contribute again without changing other spectra

    Scenario: Browse channel legends by plot family
      Given several instruments supply different spectral measurements
      When the engineer compares the channel legends
      Then NCS, Psi Delta, Mueller and Reflectance have separate legend sections
      And each section lists only channels that supply its measurements
      And overflowing channel lists can be browsed with the mouse wheel

    Scenario: Identify the selected spectrum clearly
      Given several spectra are drawn together
      When the engineer selects a spectrum
      Then its curves become thicker than the other curves
      And its Psi and Delta curves both use solid lines

    Scenario: Find a selected spectrum in the channel legends
      Given checked spectra have legends grouped by Wafer or SME Name
      When the engineer selects spectra in the tree or on a curve
      Then their corresponding legend entries are highlighted with bold labels and thicker color samples
      And more than one matching legend entry can remain highlighted
      And offscreen matching entries are brought into view
      And checks, hidden channels, colors and plot ranges remain unchanged
      When the engineer clears the spectrum selection
      Then the legend highlights are also cleared

    Scenario: Resize the plot layout
      Given several spectral plots are visible
      When the engineer drags a plot boundary
      Then a boundary preview follows the pointer
      And plot sizes update when the boundary is released
      And neighbouring panes can narrow or collapse so another plot occupies their space
      When the engineer double-clicks any splitter handle
      Then its panes return to their default proportions
      And the main tree occupies approximately one quarter of the initial width

    Scenario: Color spectra by wafer identity or individual SME file
      Given several checked spectra have Wafer, Lot, PAD and channel identities
      When Color By is Wafer
      Then each Wafer ID, Lot and PAD combination has distinct colors for its channels
      When Color By is SME Name
      Then each source file has distinct colors for its channels
      And legends and floating plots use the same colors
      And checks, selection, source values and manual plot ranges remain unchanged
      When spectra are unchecked and checked again
      Then unchanged colors and legend entries are retained

    Scenario: Keep aggregate GRR curves meaningful when coloring individual files
      Given Color By is SME Name
      When the engineer switches to 3-Sigma
      Then statistics remain per wafer and channel
      And Color By shows Wafer without splitting the statistical sample into individual files
      When the engineer returns to Original or Residual
      Then the previous SME Name color choice is restored

    Scenario: Zoom without changing the measured curve
      Given several spectra with missing measurements are plotted together
      When the engineer zooms into a wavelength interval
      Then the visible curves match the full-data rendering
      And missing measurements still create gaps
      And thick selected curves remain complete at the view edges
      When the engineer restores the full wavelength range
      Then every original sample is available again

  Rule: Checked spectra can be compared with a BSL or summarized for GRR

    Scenario: Restore hidden channels from a legend section
      Given some channels have been hidden by double-clicking a legend
      When the engineer right-clicks one legend section and chooses Show All
      Then that section's channels are restored without changing spectrum participation
      And channels in unrelated legend sections remain hidden
      And no Show All buttons occupy the legend headers

    Scenario: Calculate residuals from a single baseline spectrum
      Given exactly one spectrum is selected in the tree
      When the engineer chooses Set as BSL
      Then its identity is shown and its tree row is marked
      And plots switch to Residual without checking the BSL
      And its matching BSL channel is subtracted from each checked spectrum at exactly equal wavelengths
      And the residual is measured minus BSL
      And missing values and unmatched wavelengths remain gaps without interpolation
      And ambiguous or unmatched channels are reported
      When the engineer deletes the BSL from the session
      Then Residual is disabled and plots return to Original

    Scenario: Cancel a baseline without removing source spectra
      Given a baseline is set and Residual is active
      When the engineer chooses Clear BSL in the spectrum tree menu
      Then the baseline identity and bold row marker are cleared
      And plots return to Original and Residual is disabled
      And spectrum participation, selection and source records remain unchanged

    Scenario: Display GRR three-sigma curves independently for each wafer and channel
      Given several spectra are checked for one or more wafers and channels
      When the engineer chooses Options Plot Mode 3-Sigma
      Then each wafer and channel has one curve of three times the sample standard deviation
      And the sample divisor is n minus one at each exact wavelength
      And wavelengths with fewer than two finite observations remain gaps
      And no baseline is required and no mean plus or minus band is drawn
      And clicking a summary curve selects all its contributing spectra
      And legend visibility does not change the statistical sample

    Scenario: Inspect and leave a calculation mode
      Given residual or three-sigma results are displayed
      When the engineer opens a floating copy or chooses Original
      Then main and floating plot titles and data agree with the chosen mode
      And original measurement arrays and source files remain unchanged

  Rule: Wafer maps reflect checked spectra

    Scenario: Inspect checked spectra on a wafer
      Given checked spectra have valid millimetre coordinates
      When the engineer opens the wafer map
      Then each Wafer, Lot and PAD combination appears on one point map
      And the map title contains its Wafer, Lot and PAD
      And the map shows the wafer outline, measurement points and Die numbers
      And no interpolated surface is drawn
      And each spectrum file contributes at most one point
      When the engineer selects a point
      Then its spectrum and tree entry are highlighted

    Scenario: Select wafer points by dragging a rectangle
      Given checked spectra appear as measurement points on wafer maps
      When the engineer drags a rectangle with the left mouse button
      Then points inside the rectangle are selected without changing the wafer view range
      And every spectrum at a selected coincident point is selected
      And the spectrum tree and curve highlights follow that selection
      When the engineer holds Ctrl or Shift while dragging another rectangle
      Then those points are added to the selection
      When the engineer draws an empty rectangle without a modifier
      Then the selection is cleared

  Rule: Loading keeps the workspace responsive

    Scenario: Work while folders are being read
      Given the engineer starts loading a large nested folder
      When the engineer continues using the workspace
      Then progress remains visible
      And the load can be cancelled without replacing existing data

    Scenario: Read a folder containing encrypted files
      Given a folder contains readable SME files and TSD encrypted files
      When the engineer loads the folder
      Then the readable spectra remain available
      And encrypted files are reported separately with their source paths
      And the report asks for decrypted SME copies from an authorized environment
      When the engineer adds the same folder again
      Then each unchanged encrypted file is still reported only once

    Scenario: Keep existing plots stable while loading and selecting
      Given the engineer has zoomed into checked spectra
      When a long loading filename is displayed
      Then the plot sizes remain unchanged
      When the engineer adds the same unchanged spectra or highlights a curve
      Then the existing plot ranges remain unchanged

    Scenario: View all preserves the current selection and colors
      Given differently colored wafers are drawn and one spectrum is highlighted
      When the engineer clicks the A button to view all wavelengths
      Then the axes return to the complete wavelength range
      And the tree selection, curve highlight and assigned colors remain unchanged
      And this applies to main, Mueller, dual-axis and floating plots

    Scenario: Update checked spectra without rebuilding unrelated wafer curves
      Given checked spectra from multiple wafers are drawn with manually chosen axes
      When the engineer unchecks or rechecks one spectrum
      Then only its wafer and channel groups need updated curve data
      And unrelated curves and their screen caches remain available
      And the manual axes remain unchanged in main and floating plots
      And rechecking restores the original curve overlap order

    Scenario: Hide and restore a legend group without rebuilding curves
      Given checked wafer and channel groups are drawn
      When the engineer hides or restores one legend group
      Then the existing curves and screen caches are reused
      And hidden curves cannot appear in screen images or exports
      And manually chosen axes remain unchanged
      And enabled automatic axes follow the visible data

    Scenario: Draw a dense collection in steps
      Given a large collection of spectra is checked
      When the charts need to be drawn
      Then drawing progress advances between charts
      And the engineer can uncheck the collection before drawing finishes
      And repeated repaints preserve the measured curves

    Scenario: Resize a dense plot collection without blocking input
      Given the engineer has drawn a dense collection of spectra
      When the engineer changes fullscreen or drags a plot boundary
      Then controls remain responsive while the charts update
      And the final curves preserve the complete native curve shapes at the new size

    Scenario: Inspect smooth dense curves without changing measured samples
      Given many colored spectra contain narrow peaks and missing observations
      When the engineer views the complete wavelength range
      Then curve edges are antialiased
      And dense screen geometry may be simplified with a quarter physical pixel tolerance
      And missing observations still appear as gaps
      And source samples and native export geometry remain unchanged
      When the engineer zooms into a peak
      Then screen geometry is regenerated for the new scale with complete local detail

    Scenario: Keep only the latest dense selection
      Given a dense collection is still being drawn
      When the engineer unchecks selected spectra before drawing finishes
      Then the plots and floating copies eventually show only the remaining checked spectra
      And obsolete background images cannot replace those results
      When the engineer closes the viewer
      Then its queued drawing work is cancelled

  Rule: Spectra can belong to a Match Workbook

    Scenario: Use the same Viewer appearance from either entry point
      Given a Spectra Viewer is opened from the main window and another from a Match Workbook
      Then their controls and layout use the same application theme
      When the engineer switches between the light and dark themes
      Then both Viewers update their appearance
      And the Workbook child's save shortcuts still target its owning Workbook

    Scenario: Keep complete wafers at a fixed readable size
      Given a map page contains twelve wafers with long identity titles
      When the engineer resizes the map window or opens the last page
      Then every wafer outline and measurement point remains inside its plot
      And maps occupy fixed columns and keep the same size during loading and resizing
      And scrollbars expose maps outside the available window area
      And long titles wrap above the plots without clipping the measurement area

    Scenario: Change participation for points outside a selected region
      Given some points are selected within one wafer
      When the engineer chooses Check Unselected or Uncheck Unselected on that wafer
      Then only its unselected points change participation
      And selected points and other wafers keep their participation

    Scenario: Export checked original spectra and recover unavailable files
      Given checked spectra refer to original SME files in source folders
      When the engineer exports checked spectra
      Then a child window shows progress while the original bytes are copied with their folders
      And long folder paths work for batch exports and subsequent reading
      When an original file cannot be copied
      Then the engineer can restore it and Retry or Skip that file
      And the completed report lists every file that remains unavailable and its error
      And existing target files are never overwritten and no SME is generated
      When the engineer cancels or closes the export window
      Then waiting work stops and files created by that export are rolled back

    Scenario: Hide and restore legend groups from the context menu
      Given plotted spectra have checked and selected states and manual axes
      When the engineer chooses Hide All in a legend's context menu
      Then that legend's curve groups are hidden
      And checked states, selected spectra and manual axes remain unchanged
      When the engineer chooses Show All in the same menu
      Then those groups become visible again
      And hidden groups absent from that legend remain hidden

    Scenario: Carry source spectra and choices with the Workbook
      Given a named Spectra Viewer child contains checked spectra and a baseline
      When the engineer saves and reopens the Match Workbook
      Then the child restores source measurements and metadata without reading the original SME paths
      And check states, colors, baseline, analysis mode and manual axes are restored
      And opening an unchanged child does not mark the Workbook modified
      When the engineer unchecks a restored spectrum
      Then the Workbook has unsaved changes

    Scenario: Remove only one Spectra window
      Given two named Spectra children belong to a Match Workbook
      When the engineer confirms deletion of one child
      Then the other child and other analysis tools retain their data and choices
      And original SME files are unchanged

  Rule: Spectra can be saved independently

    Scenario: Save a Workbook child as a portable Spectra file
      Given a Workbook Spectra child has checked spectra and a baseline
      When the engineer chooses Save Spectra As
      Then a .spec file contains the source samples and current settings
      And the parent Workbook is not saved or marked clean
      When the engineer opens the .spec file independently
      Then the spectra and analysis choices are restored without the original SME files

    Scenario: Saving shortcuts prioritize the owning Workbook
      Given a Spectra child belongs to a Match Workbook
      When the engineer presses Ctrl+S or Ctrl+Shift+S
      Then the owning Workbook's Save or Save As action runs
      And the separate Spectra save actions have no conflicting shortcuts
      Given a Spectra Viewer is opened independently
      Then Ctrl+S and Ctrl+Shift+S save or save as a .spec file

    Scenario: Preserve the current session when opening an invalid file
      Given spectra are loaded in the viewer
      When the engineer opens a .spec with unsupported settings
      Then an error is reported before replacing the current spectra

  # Executable Workbook acceptance checks: tests.test_spectra_workbook.
  # Executable acceptance checks: tests.test_sme_spectra,
  # tests.test_spectra_viewer and tests.test_spectra_map.
  # Reproducible resize probe: scripts/benchmark_spectra_splitter.py.
