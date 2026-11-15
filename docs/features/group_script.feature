Feature: Copy Group settings between analytical workspaces
  Engineers reuse Head, Mark and combined Group definitions without changing
  source measurements or data participation.

  # Executable acceptance checks: tests.test_group_script.
  Scenario: Paste a Group recipe into a differently ordered table
    Given source and target have the same Wafer, Lot, PAD and Die identities in different row orders
    When the engineer copies the Group Script and pastes it into the target Group settings
    Then TestFlags and Marks follow those identities rather than row positions
    And Head names, combined Groups and Group display options are retained
    And source measurement strings and target data participation are unchanged
    And the recipe remains a draft until Apply in Group settings

  Scenario: Reject an ambiguous or incomplete recipe
    Given the target already has accepted Groups
    When a pasted script has conflicting assignments for the same identity or lacks a target identity
    Then an explanation is shown and the existing draft and accepted Groups are unchanged

  Scenario: Apply copied Groups in Spectra Viewer
    Given spectra already have local Mark assignments
    When the engineer pastes a Group Script into the local Group settings and applies
    Then copied definitions and assignments replace the local classification
    And shared TestFlags update while spectral participation is retained
    And Undo restores the previous classification and flags
