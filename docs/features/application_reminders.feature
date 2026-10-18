# Executable examples: tests/test_reminders.py and tests/test_reminder_panel.py
Feature: Keep personal reminders independently of analysis work
  Engineers can track tasks on the home screen without tying them to a Tool or WKB.

  Scenario: Keep reminders when updating or moving the application
    Given the engineer has active and completed reminders from an earlier version
    When the engineer updates the source application and later opens a portable version
    Then both versions use the same automatically saved reminders for that Windows user
    And the earlier reminders file is kept unchanged

  Scenario: Do not bring deleted reminders back from an old installation
    Given the engineer's reminders have been migrated to the Windows user folder
    When the engineer edits one task and deletes another
    Then reopening either updated version retains those changes
    And old installation copies do not restore deleted tasks

  Scenario: Reach reminders above an expanded diagnostic Log
    Given the engineer has thirty reminders
    When the engineer makes the Log taller or reduces the window height
    Then only the reminder list scrolls above the Log
    And the title, filters, search and footer actions stay fixed and visible
    And the last reminder remains readable inside the list
    And scrolling does not change the tasks or move the Log divider

  Scenario: Keep the empty reminders area compact
    Given the engineer has no reminders or searches for a task with no matches
    When the home screen is shown above the Log
    Then the empty reminder body has no scrollbar
    And no redundant Workspace heading takes space above the Reminders card

  Scenario: Reminder actions stay visually stable
    Given the home screen shows an active reminder
    When the engineer presses New reminder or marks a task complete
    Then the action symbols stay centered without jumping
    And the controls remain readable in light and dark themes

  Scenario: Choose a reminder date from a complete calendar
    Given a reminder is scheduled for October 20, 2026
    When the engineer changes it to November 21 using the calendar
    Then the month, weekday headings and dates remain fully visible in English
    And the chosen date is retained after saving and reopening

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
