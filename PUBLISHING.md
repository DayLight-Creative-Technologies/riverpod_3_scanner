# Publishing to PyPI - Guide for Maintainers

This guide explains how to publish new versions of `riverpod-3-scanner` to PyPI.

---

## 📋 Prerequisites

### 0. Locate PyPI Credentials (Check First)

**This project stores credentials in `.env` file in project root.**

Check for existing credentials in this order:

```bash
# 1. Check for .env file in project root (RECOMMENDED for this project)
cd /Users/stevencday/dev/riverpod_3_scanner
cat .env
# Should contain: PYPI_TOKEN=pypi-...

# 2. Check for ~/.pypirc file (system-wide)
cat ~/.pypirc

# 3. Check for environment variables
echo $TWINE_PASSWORD
```

**If using `.env` file** (recommended for this project):
```bash
# Source the .env file and upload
cd /Users/stevencday/dev/riverpod_3_scanner
source .env
python3 -m twine upload dist/* --username __token__ --password $PYPI_TOKEN
```

**If credentials are missing**, proceed to setup below.

---

### 1. PyPI Account Setup

1. **Create PyPI account**: https://pypi.org/account/register/
2. **Create API token**:
   - Go to: https://pypi.org/manage/account/token/
   - Create token with scope: "Entire account" (for first publish) or "Project: riverpod-3-scanner"
   - Save token securely (starts with `pypi-`)

### 2. Configure Credentials

**Option A: Using .pypirc** (Recommended)
```bash
cat > ~/.pypirc <<EOF
[pypi]
username = __token__
password = pypi-YOUR_TOKEN_HERE
EOF

chmod 600 ~/.pypirc
```

**Option B: Environment Variable**
```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-YOUR_TOKEN_HERE
```

### 3. Install Publishing Tools

```bash
pip install --upgrade build twine
```

---

## 🚀 Publishing New Version

### Step 1: Update Version

Update version in **3 files**:

1. **pyproject.toml**:
   ```toml
   version = "1.0.1"  # Update this
   ```

2. **setup.py**:
   ```python
   version="1.0.1",  # Update this
   ```

3. **riverpod_3_scanner/__init__.py**:
   ```python
   __version__ = "1.0.1"  # Update this
   ```

### Step 2: Update CHANGELOG.md

Add new version section:
```markdown
## [1.0.1] - 2025-12-XX

### Added
- New feature description

### Fixed
- Bug fix description

### Changed
- Change description
```

### Step 3: Clean Previous Builds

```bash
cd /Users/stevencday/dev/riverpod_3_scanner
rm -rf dist/ build/ *.egg-info
```

### Step 4: Build Package

```bash
python3 -m build
```

**Expected output**:
```
Successfully built riverpod_3_scanner-1.0.1.tar.gz and riverpod_3_scanner-1.0.1-py3-none-any.whl
```

### Step 5: Validate Package

```bash
python3 -m twine check dist/*
```

**Expected output**:
```
Checking dist/riverpod_3_scanner-1.0.1-py3-none-any.whl: PASSED
Checking dist/riverpod_3_scanner-1.0.1.tar.gz: PASSED
```

### Step 6: Test on TestPyPI (RECOMMENDED)

Upload to TestPyPI first to verify everything works:

```bash
python3 -m twine upload --repository testpypi dist/*
```

Test installation from TestPyPI:
```bash
pip install --index-url https://test.pypi.org/simple/ riverpod-3-scanner
```

### Step 7: Publish to PyPI

**Method 1: Using .env file** (Recommended for this project):
```bash
# Source .env and upload with token
source .env
python3 -m twine upload dist/* --username __token__ --password $PYPI_TOKEN
```

**Method 2: Using .pypirc**:
```bash
# Credentials loaded automatically from ~/.pypirc
python3 -m twine upload dist/*
```

**Method 3: Interactive prompt**:
```bash
# Enter credentials when prompted
python3 -m twine upload dist/*
# Username: __token__
# Password: pypi-YOUR_TOKEN_HERE
```

### Step 8: Verify Publication

Check package page: https://pypi.org/project/riverpod-3-scanner/

Test installation:
```bash
pip install riverpod-3-scanner
riverpod-3-scanner --help
```

### Step 9: Tag Release in Git

```bash
git tag -a v1.0.1 -m "Release version 1.0.1"
git push origin v1.0.1
```

### Step 10: Create GitHub Release

1. Go to: https://github.com/DayLight-Creative-Technologies/riverpod_3_scanner/releases/new
2. Choose tag: `v1.0.1`
3. Title: `Release v1.0.1`
4. Description: Copy from CHANGELOG.md
5. Attach files: `dist/riverpod_3_scanner-1.0.1.tar.gz` and `.whl`
6. Publish release

---

## 🔄 Version Numbering

Follow Semantic Versioning (https://semver.org):

- **MAJOR** (1.x.x): Breaking changes
- **MINOR** (x.1.x): New features (backward compatible)
- **PATCH** (x.x.1): Bug fixes (backward compatible)

Examples:
- `1.0.0` → `1.0.1` - Bug fix
- `1.0.1` → `1.1.0` - New violation type detection
- `1.1.0` → `2.0.0` - Breaking CLI changes

---

## 🧪 Testing Checklist

Before publishing, verify:

- ✅ Version updated in 3 files (pyproject.toml, setup.py, __init__.py)
- ✅ CHANGELOG.md updated with release notes
- ✅ `python3 -m build` succeeds
- ✅ `python3 -m twine check dist/*` passes
- ✅ Local installation works: `pip install -e .`
- ✅ Command works: `riverpod-3-scanner --help`
- ✅ Module works: `python3 -m riverpod_3_scanner --help`
- ✅ All tests pass (if you have tests)
- ✅ Documentation updated (README.md references correct version)

---

## 🚨 First-Time Publishing (v1.0.0)

For the initial v1.0.0 release:

### Step 1: Create PyPI Account & Token

1. Register at https://pypi.org/account/register/
2. Verify email address
3. Create API token (entire account scope)
4. Save token securely

### Step 2: Build and Upload

```bash
cd /Users/stevencday/dev/riverpod_3_scanner

# Clean
rm -rf dist/ build/ *.egg-info

# Build
python3 -m build

# Validate
python3 -m twine check dist/*

# Upload to PyPI
python3 -m twine upload dist/*
# Enter: __token__
# Password: pypi-YOUR_TOKEN_HERE
```

### Step 3: Verify

```bash
# Wait 1-2 minutes for PyPI to process
pip install riverpod-3-scanner

# Test
riverpod-3-scanner --help
python3 -m riverpod_3_scanner --help
```

### Step 4: Update README.md

Add installation instructions:
```markdown
## Installation

### Via pip (Recommended)
```bash
pip install riverpod-3-scanner
```

### Via GitHub
```bash
curl -O https://raw.githubusercontent.com/DayLight-Creative-Technologies/riverpod_3_scanner/main/riverpod_3_scanner/scanner.py
```
\`\`\`
```

### Step 5: Tag and Release on GitHub

```bash
git tag -a v1.0.0 -m "Initial PyPI release v1.0.0"
git push origin v1.0.0
```

Create GitHub release with dist files attached.

---

## 📦 Package Structure

```
riverpod_3_scanner/
├── pyproject.toml              # Modern package config
├── setup.py                    # Backward compatibility
├── MANIFEST.in                 # Include non-Python files
├── README.md                   # PyPI landing page
├── LICENSE                     # MIT License
├── CHANGELOG.md                # Version history
├── riverpod_3_scanner/         # Package directory
│   ├── __init__.py            # Package exports
│   ├── __main__.py            # python -m support
│   └── scanner.py             # Main scanner code
└── docs/                       # Additional docs
    ├── GUIDE.md
    ├── EXAMPLES.md
    └── PACKAGE_INFO.md
```

---

## 🔧 Troubleshooting

### "Invalid distribution" error

Check pyproject.toml syntax:
```bash
python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"
```

### "Package not found" after upload

Wait 1-2 minutes for PyPI CDN to propagate, then try again.

### "File already exists" error

You cannot overwrite a version on PyPI. Increment version number and republish.

### twine upload fails with authentication error

1. Verify API token is correct
2. Check ~/.pypirc format
3. Try environment variable method instead

---

## 📊 Post-Publication Checklist

After successful PyPI publication:

- ✅ Verify package page: https://pypi.org/project/riverpod-3-scanner/
- ✅ Test `pip install riverpod-3-scanner`
- ✅ Test `riverpod-3-scanner --help`
- ✅ Update README.md with pip install instructions
- ✅ Create GitHub release with tag
- ✅ Announce on social media/forums
- ✅ Update documentation with PyPI badge

---

## 🎯 Quick Commands Reference

```bash
# Clean build artifacts
rm -rf dist/ build/ *.egg-info

# Build package
python3 -m build

# Validate package
python3 -m twine check dist/*

# Upload to TestPyPI (testing)
python3 -m twine upload --repository testpypi dist/*

# Upload to PyPI (production)
python3 -m twine upload dist/*

# Install locally for testing
pip install -e .

# Uninstall
pip uninstall riverpod-3-scanner
```

---

**Maintainer**: Steven Day (support@daylightcreative.tech)
**Company**: DayLight Creative Technologies
