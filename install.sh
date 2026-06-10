#!/bin/bash
#
# Riverpod 3.0 Safety Scanner - Installation Script
#
# Installs the scanner (from PyPI, or from this checkout when run inside the
# repo) and optionally sets up a pre-commit hook in your Flutter project.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  Riverpod 3.0 Safety Scanner - Installation${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}❌ Error: Python 3 is required but not installed${NC}"
    echo "Please install Python 3.9+ and try again"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✅ Python found: $PYTHON_VERSION${NC}"

# Install the package — from this checkout when the script sits next to
# pyproject.toml, otherwise from PyPI.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    echo -e "${BLUE}Installing from local checkout...${NC}"
    python3 -m pip install --upgrade "$SCRIPT_DIR"
else
    echo -e "${BLUE}Installing from PyPI...${NC}"
    python3 -m pip install --upgrade riverpod-3-scanner
fi

# Test scanner
echo ""
echo -e "${BLUE}Testing scanner...${NC}"
if python3 -m riverpod_3_scanner --version &> /dev/null; then
    echo -e "${GREEN}✅ Scanner test passed ($(python3 -m riverpod_3_scanner --version))${NC}"
else
    echo -e "${RED}❌ Scanner test failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Usage (from your Flutter project root):${NC}"
echo -e "  ${YELLOW}riverpod-3-scanner lib${NC}"
echo -e "  ${YELLOW}riverpod-3-scanner lib --verbose${NC}"
echo -e "  ${YELLOW}riverpod-3-scanner lib --format json${NC}"
echo ""

# Ask about pre-commit hook
echo -e "${BLUE}Would you like to set up a pre-commit hook in the current directory's repo? (y/n)${NC}"
read -r setup_hook

if [ "$setup_hook" = "y" ] || [ "$setup_hook" = "Y" ]; then
    # Check if .git directory exists
    if [ ! -d ".git" ]; then
        echo -e "${RED}❌ Not a git repository${NC}"
        echo "Run this script from the root of your git repository"
        exit 1
    fi

    # Create hooks directory if it doesn't exist
    mkdir -p .git/hooks

    HOOK_FILE=".git/hooks/pre-commit"

    # Check if pre-commit hook already exists
    if [ -f "$HOOK_FILE" ]; then
        echo -e "${YELLOW}⚠️  Pre-commit hook already exists${NC}"
        echo -e "${BLUE}Overwrite? (y/n)${NC}"
        read -r overwrite
        if [ "$overwrite" != "y" ] && [ "$overwrite" != "Y" ]; then
            echo -e "${YELLOW}Skipping pre-commit hook setup${NC}"
            exit 0
        fi
    fi

    # Create pre-commit hook
    cat > "$HOOK_FILE" << 'EOF'
#!/bin/bash
#
# Pre-commit hook for Riverpod 3.0 safety compliance
#

echo "Running Riverpod 3.0 compliance check..."

if command -v riverpod-3-scanner &> /dev/null; then
    SCANNER="riverpod-3-scanner"
else
    SCANNER="python3 -m riverpod_3_scanner"
fi

# Run scanner
$SCANNER lib || {
    echo ""
    echo "❌ Riverpod 3.0 violations found!"
    echo "Fix violations before committing."
    echo "To skip this check, use: git commit --no-verify"
    exit 1
}

# Run dart analyze
echo "Running dart analyze..."
dart analyze lib/ || {
    echo ""
    echo "❌ Dart analyze errors found!"
    echo "Fix errors before committing."
    echo "To skip this check, use: git commit --no-verify"
    exit 1
}

echo "✅ All compliance checks passed!"
exit 0
EOF

    # Make hook executable
    chmod +x "$HOOK_FILE"

    echo -e "${GREEN}✅ Pre-commit hook installed${NC}"
    echo ""
    echo -e "${BLUE}The hook will run automatically before each commit${NC}"
    echo -e "${BLUE}To skip: ${YELLOW}git commit --no-verify${NC}"
fi

echo ""
echo -e "${BLUE}📚 Documentation:${NC}"
echo -e "  README.md        - Quick start and features"
echo -e "  docs/GUIDE.md    - Complete guide with all patterns"
echo -e "  docs/EXAMPLES.md - Real-world crash case studies"
echo ""
echo -e "${GREEN}Happy coding! 🚀${NC}"
