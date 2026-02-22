# Encoding Policy (Internal)

## Rule
- All repository text files must be UTF-8 without BOM.
- Windows scripts keep CRLF line endings (`*.ps1`, `*.cmd`, `*.bat`).

## Enforcement
- Editor baseline: `.editorconfig`
- Git line-ending baseline: `.gitattributes`
- Validation command:
  - `python tools/quality/check_utf8.py`
- CI/unit gate:
  - `pytest -q tests/test_encoding_policy.py`

## Scope
- Included: `modules/`, `tests/`, `tools/`, `plan/`, and root-level text/config files.
- Excluded: runtime/data artifacts (`data/`, `verify/`, `test_files/`).
