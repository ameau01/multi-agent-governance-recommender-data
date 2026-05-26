"""Shared contract version constant.

Bumped per the semver rules in docs/contract-spec.md §12.5:
  - Patch (1.0.x): additive field with a default, no renames/removals
  - Minor (1.x.0): new required field, new enum value, new file
  - Major (x.0.0): breaking schema change
"""

CONTRACT_VERSION = "1.0.0"
