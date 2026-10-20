# Metrology Workspace

Language for metrology analysis and screenshot-based parameter preparation.

## Correlation and Trend

**Source-qualified parameter**:
A measured column identified by both its source table (REF or RAW) and its original name. REF DP and RAW DP are distinct parameters even when their names match.
_Avoid_: Merged parameter, shared column

**Cross-source pair**:
Two source-qualified parameters from different tables, paired by their original aligned measurement rows. Missing or excluded observations do not shift the remaining pairs.
_Avoid_: Concatenated populations, independently compacted columns

## AutoWeighting preparation

**Parameter specification**:
A named parameter with its nominal value and permitted minimum and maximum.
_Avoid_: Card, Step value

**Step setting**:
The mode and associated value or constraint assigned to one parameter in one analysis step. Float, Fix and Constrain are distinct modes.
_Avoid_: Measurement, nominal value

**Constraint expression**:
The expression associated with a Constrain setting, potentially referring to other named parameters.
_Avoid_: Executable script, measured value

**Recognition candidate**:
A proposed transcription of a visible screenshot field that has not yet been confirmed by the analyst.
_Avoid_: Ground truth, confirmed value

**Visible weighting control**:
A weight value or control caption visible in a screenshot; a button caption alone does not reveal the weight details behind it.
_Avoid_: Complete weighting configuration
