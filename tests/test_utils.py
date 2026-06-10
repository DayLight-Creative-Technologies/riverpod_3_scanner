"""Unit tests for the parsing utilities."""

from pathlib import Path

from riverpod_3_scanner.utils import (
    FileCache,
    blank_comments,
    find_matching_brace,
    find_matching_paren,
    is_file_suppressed,
    is_line_suppressed,
    remove_comments,
    strip_comments,
)


class TestBlankComments:
    def test_preserves_length(self):
        src = "final a = 1; // trailing comment\nfinal b = 2;"
        assert len(blank_comments(src)) == len(src)

    def test_blanks_line_comment(self):
        src = "final a = 1; // ref.read(provider)\n"
        out = blank_comments(src)
        assert "ref.read" not in out
        assert "final a = 1;" in out

    def test_blanks_block_comment_preserving_newlines(self):
        src = "a;\n/* one\ntwo\nthree */\nb;"
        out = blank_comments(src)
        assert "one" not in out
        assert out.count("\n") == src.count("\n")
        assert len(out) == len(src)

    def test_slash_slash_inside_string_is_not_a_comment(self):
        # The pre-1.12.0 regex stripper deleted everything after `//` inside
        # the URL, hiding the ref.read on the same line.
        src = "final url = 'https://example.com'; ref.read(provider);"
        out = blank_comments(src)
        assert "ref.read(provider);" in out

    def test_block_marker_inside_string_is_not_a_comment(self):
        src = "final glob = 'a/*.dart'; ref.read(provider);"
        out = blank_comments(src)
        assert "ref.read(provider);" in out

    def test_raw_string_preserved(self):
        src = r"final re = r'//not-a-comment'; b;"
        out = blank_comments(src)
        assert "//not-a-comment" in out
        assert out.endswith("b;")

    def test_triple_quoted_string_preserved(self):
        src = "final s = '''line1 // keep\nline2''';\nref.read(p);"
        out = blank_comments(src)
        assert "// keep" in out
        assert "ref.read(p);" in out

    def test_comment_containing_quote_does_not_break_parsing(self):
        src = "a; // it's a comment\nref.read(p);"
        out = blank_comments(src)
        assert "ref.read(p);" in out
        assert "it's" not in out


class TestWrappers:
    def test_strip_comments_returns_identity_map(self):
        src = "a; // comment\nb;"
        stripped, pos_map = strip_comments(src)
        assert len(stripped) == len(src)
        assert pos_map == {}  # identity via callers' .get(i, i) fallback

    def test_remove_comments_is_string_aware(self):
        src = "final url = 'http://x'; ref.read(p);"
        assert "ref.read(p);" in remove_comments(src)


class TestDelimiterMatching:
    def test_simple_braces(self):
        src = "{ a; { b; } c; } tail"
        # start just after the opening brace at index 0
        assert src[find_matching_brace(src, 1)] == "}"
        assert find_matching_brace(src, 1) == 15

    def test_brace_inside_string_ignored(self):
        src = "{ final s = '}'; }"
        assert find_matching_brace(src, 1) == len(src) - 1

    def test_brace_inside_comment_ignored(self):
        src = "{ // }\n}"
        assert find_matching_brace(src, 1) == len(src) - 1

    def test_brace_inside_block_comment_ignored(self):
        src = "{ /* } */ }"
        assert find_matching_brace(src, 1) == len(src) - 1

    def test_paren_with_nested_call(self):
        src = "(a, compute(x, y), b) rest"
        assert find_matching_paren(src, 1) == 20

    def test_unterminated_returns_length(self):
        src = "{ never closed"
        assert find_matching_brace(src, 1) == len(src)


class TestSuppression:
    def test_same_line_suppression(self):
        lines = ["bad(); // riverpod_scanner:ignore"]
        assert is_line_suppressed(lines, 1)

    def test_line_above_suppression(self):
        lines = ["// riverpod_scanner:ignore", "bad();"]
        assert is_line_suppressed(lines, 2)

    def test_no_suppression(self):
        lines = ["bad();"]
        assert not is_line_suppressed(lines, 1)

    def test_file_suppression_in_header(self):
        content = "// riverpod_scanner:ignore-file\nclass A {}"
        assert is_file_suppressed(content)

    def test_file_suppression_only_scans_first_20_lines(self):
        content = "\n" * 30 + "// riverpod_scanner:ignore-file\n"
        assert not is_file_suppressed(content)


class TestFileCache:
    def test_unreadable_file_returns_none(self, tmp_path, capsys):
        bad = tmp_path / "bad.dart"
        bad.write_bytes(b"\xff\xfe invalid \xc3 utf8 \xff")
        cache = FileCache()
        assert cache.read_text(bad) is None
        assert cache.read_lines(bad) == []
        # Reported once on stderr, not raised.
        assert "Skipping unreadable file" in capsys.readouterr().err

    def test_missing_file_returns_none(self, tmp_path):
        cache = FileCache()
        assert cache.read_text(tmp_path / "nope.dart") is None

    def test_caches_content(self, tmp_path):
        f = tmp_path / "a.dart"
        f.write_text("class A {}")
        cache = FileCache()
        assert cache.read_text(f) == "class A {}"
        f.unlink()  # second read must come from cache
        assert cache.read_text(f) == "class A {}"
