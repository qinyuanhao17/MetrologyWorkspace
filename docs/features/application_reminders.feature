# Executable examples: tests/test_reminders.py and tests/test_reminder_panel.py
Feature: Keep personal reminders independently of analysis work
  Engineers can track tasks on the home screen without tying them to a Tool or WKB.

  Scenario: Remember a task after restarting the application
    Given a reminder to submit a paper has a date and notes
    When the engineer edits it and restarts the application
    Then the reminder retains its title, date, notes and flag
    And opening an analysis Tool does not replace it

  Scenario: Focus on tasks that need attention today
    Given a report review is overdue and a paper submission is scheduled next week
    When the engineer views Today
    Then the overdue report review is shown
    And the future paper submission remains available in Scheduled

  Scenario: Restore a completed task before deleting it
    Given the report review is complete
    When the engineer marks it incomplete from Completed
    Then it returns to the active reminders
    And deleting it requires confirmation

  Scenario: Protect existing reminders when a file cannot be read
    Given the reminders file was created by a newer application version
    When this application tries to save a reminder
    Then the existing file is not overwritten
    And the engineer is told that a newer version is required
