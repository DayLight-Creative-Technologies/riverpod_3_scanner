# Publishing to PyPI

## THE COMMAND (copy-paste this)

Every publish follows this exact sequence. No variations, no alternatives.

```bash
# 1. cd into the project (ALL commands run from here)
cd /Users/stevencday/dev/riverpod_3_scanner

# 2. Clean old builds
rm -rf dist/ build/ *.egg-info

# 3. Build
python3 -m build

# 4. Validate
python3 -m twine check dist/*

# 5. Upload (source .env for the token, then upload in the same command)
source .env && python3 -m twine upload dist/* --username __token__ --password $PYPI_TOKEN

# 6. Tag and push (if not already tagged)
git tag -a vX.Y.Z -m "Release version X.Y.Z"
git push origin vX.Y.Z
```

That's it. If every step succeeds, you're done. Read on only if something fails.

---

## Before You Publish: Version Bump Checklist

Version must be updated in **exactly 3 files** (all must match):

| File | Field |
|------|-------|
| `pyproject.toml` | `version = "X.Y.Z"` |
| `setup.py` | `version="X.Y.Z",` |
| `riverpod_3_scanner/__init__.py` | `__version__ = "X.Y.Z"` |

Also update `CHANGELOG.md` with the new version's changes.

Semantic versioning: MAJOR.MINOR.PATCH
- PATCH: bug fixes
- MINOR: new features (backward compatible)
- MAJOR: breaking changes

---

## Troubleshooting

### IMPORTANT: Read This Before Trying Anything Else

**The token is almost certainly fine.** The `.env` file at the project root contains a valid PyPI API token. It has worked for every release from v1.0.0 through v1.4.1. If upload fails, check the causes below IN ORDER before even considering token issues.

### Error: "File already exists" (HTTP 400)

**This is the #1 most common error.** It means the version you're trying to upload already exists on PyPI. PyPI does not allow overwriting published versions — ever.

**Fix:** Bump the version in all 3 files, rebuild, and upload again.

**How to check what's already published:**
```bash
pip3 index versions riverpod-3-scanner
```

### Error: dist/ contains stale or wrong-version artifacts

If you updated the version in the 3 files but didn't rebuild, `dist/` still has the OLD version's `.whl` and `.tar.gz`. The upload will either fail ("file already exists" for the old version) or succeed uploading the wrong version.

**Fix:** Always clean and rebuild before uploading:
```bash
rm -rf dist/ build/ *.egg-info
python3 -m build
```

**How to verify:** Check that the filenames in `dist/` match your intended version:
```bash
ls dist/
# Should show: riverpod_3_scanner-X.Y.Z-py3-none-any.whl
#              riverpod_3_scanner-X.Y.Z.tar.gz
```

### Error: "No module named build" or "No module named twine"

Publishing tools aren't installed.

**Fix:**
```bash
pip3 install --upgrade build twine
```

### Error: twine check fails with "FAILED"

The package metadata is malformed — usually a syntax error in `pyproject.toml` or `setup.py`, or the README has invalid markdown that can't render.

**Fix:** Read the error message. It will tell you exactly what's wrong (usually a field format issue or bad reStructuredText).

### Error: "403 Forbidden" on upload

This actually IS a token issue — but it's rare. Possible causes:
1. The `.env` file was deleted or corrupted
2. The token was revoked on pypi.org
3. The token scope is limited to a different project name

**Diagnosis:**
```bash
# Check that .env exists and has content
cat /Users/stevencday/dev/riverpod_3_scanner/.env
# Should show: PYPI_TOKEN=pypi-...

# Verify the variable loaded
source /Users/stevencday/dev/riverpod_3_scanner/.env
echo $PYPI_TOKEN
# Should print a long string starting with pypi-
```

If the file is missing or empty, create a new token at https://pypi.org/manage/account/token/ with scope "Project: riverpod-3-scanner" and save it:
```bash
echo 'PYPI_TOKEN=pypi-YOUR_NEW_TOKEN' > /Users/stevencday/dev/riverpod_3_scanner/.env
```

### "Package not found" immediately after upload

Normal. PyPI CDN takes 1-2 minutes to propagate. Wait, then try again.

---

## Credentials

This project uses ONE credential method: a `.env` file in the project root.

**Location:** `/Users/stevencday/dev/riverpod_3_scanner/.env`
**Format:** `PYPI_TOKEN=pypi-...`
**Usage:** `source .env` loads the token, then pass it to twine via `--password $PYPI_TOKEN`

Do NOT use `~/.pypirc`, do NOT use `TWINE_PASSWORD` environment variables, do NOT use interactive prompts. Those are alternative methods documented elsewhere on the internet — this project uses `.env` and that is the only method that should be attempted.

---

## Post-Publish Verification

```bash
# Verify version is live (may take 1-2 min after upload)
pip3 index versions riverpod-3-scanner

# Verify package page
# https://pypi.org/project/riverpod-3-scanner/

# Test installation
pip3 install --upgrade riverpod-3-scanner
riverpod-3-scanner --help
```

---

## Package Structure

```
riverpod_3_scanner/
├── pyproject.toml              # Package config (version lives here)
├── setup.py                    # Backward compat (version lives here too)
├── MANIFEST.in                 # Include non-Python files in sdist
├── README.md                   # PyPI landing page
├── LICENSE                     # MIT
├── CHANGELOG.md                # Version history
├── .env                        # PyPI token (not committed to git)
├── riverpod_3_scanner/         # Package source
│   ├── __init__.py            # Version + exports (version lives here too)
│   ├── __main__.py            # python -m support
│   ├── scanner.py             # Orchestrator
│   ├── models.py              # Data models
│   ├── utils.py               # Parsing utilities
│   ├── analysis.py            # Call-graph analysis
│   ├── checkers.py            # Violation detectors
│   └── output.py              # Formatters
└── docs/
    ├── GUIDE.md
    ├── EXAMPLES.md
    └── PACKAGE_INFO.md
```

---

## First-Time Setup (Already Done — Reference Only)

This section documents initial setup that was completed for v1.0.0. You should never need this again unless setting up on a completely new machine.

1. Create PyPI account: https://pypi.org/account/register/
2. Create API token at https://pypi.org/manage/account/token/ (scope: project `riverpod-3-scanner`)
3. Save token to `.env`: `echo 'PYPI_TOKEN=pypi-...' > .env`
4. Install tools: `pip3 install --upgrade build twine`
5. Follow "THE COMMAND" section above

---

**Maintainer**: Steven Day (support@daylightcreative.tech)
**Company**: DayLight Creative Technologies
