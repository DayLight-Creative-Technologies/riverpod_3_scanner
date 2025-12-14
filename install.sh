#!/bin/bash
#
# Riverpod 3.0 Safety Scanner - Installation Script
#
# This script installs the scanner and optionally sets up a pre-commit hook
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCANNER_FILE="riverpod_3_scanner.py"
SCANNER_PATH="$SCRIPT_DIR/$SCANNER_FILE"

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
    echo "Please install Python 3.7+ and try again"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo -e "${GREEN}✅ Python found: $PYTHON_VERSION${NC}"

# Check if scanner file exists
if [ ! -f "$SCANNER_PATH" ]; then
    echo -e "${RED}❌ Error: Scanner file not found at $SCANNER_PATH${NC}"
    exit 1
fi

# Make scanner executable
chmod +x "$SCANNER_PATH"
echo -e "${GREEN}✅ Scanner is executable${NC}"

# Test scanner
echo ""
echo -e "${BLUE}Testing scanner...${NC}"
if python3 "$SCANNER_PATH" --help &> /dev/null; then
    echo -e "${GREEN}✅ Scanner test passed${NC}"
else
    echo -e "${RED}❌ Scanner test failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${BLUE}Usage:${NC}"
echo -e "  ${YELLOW}python3 $SCANNER_PATH lib${NC}"
echo -e "  ${YELLOW}python3 $SCANNER_PATH lib --verbose${NC}"
echo -e "  ${YELLOW}python3 $SCANNER_PATH lib/features${NC}"
echo ""

# Ask about pre-commit hook
echo -e "${BLUE}Would you like to set up a pre-commit hook? (y/n)${NC}"
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

# Find scanner (adjust path if needed)
SCANNER="riverpod_3_scanner.py"

if [ -f "$SCANNER" ]; then
    SCANNER_PATH="$SCANNER"
elif [ -f "docs/packages/riverpod_3_scanner/$SCANNER" ]; then
    SCANNER_PATH="docs/packages/riverpod_3_scanner/$SCANNER"
else
    echo "❌ Scanner not found"
    echo "Please install scanner or update path in .git/hooks/pre-commit"
    exit 1
fi

# Run scanner
python3 "$SCANNER_PATH" lib || {
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
echo -e "  README.md  - Quick start and features"
echo -e "  GUIDE.md   - Complete guide with all patterns"
echo -e "  EXAMPLES.md - Real-world crash case studies"
echo ""
echo -e "${GREEN}Happy coding! 🚀${NC}"
