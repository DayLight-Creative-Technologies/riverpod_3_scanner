"""Unit tests for the parsing utilities."""

from pathlib import Path

from riverpod_3_scanner.utils import (
    FileCache,
    blank_comments,
    blank_string_literals,
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


class TestBlankStringLiterals:
    def test_preserves_length_and_newlines(self):
        src = "log('a\\nb ${x}');\nfinal t = '''one\ntwo''';\nfinal r = r'raw $y';\n"
        out = blank_string_literals(src)
        assert len(out) == len(src)
        assert out.count("\n") == src.count("\n")

    def test_blanks_literal_text_but_keeps_delimiters(self):
        out = blank_string_literals("logger.logError('Could not restore state.');")
        assert "state" not in out
        assert out == "logger.logError('                        ');"

    def test_message_mentioning_ref_read_is_blanked(self):
        assert "ref.read" not in blank_string_literals("log('ref.read(x) skipped');")

    def test_interpolation_expression_is_code_and_kept(self):
        out = blank_string_literals("log('for ${ref.read(idProvider)} done');")
        assert "ref.read(idProvider)" in out
        assert "for" not in out and "done" not in out

    def test_simple_interpolation_identifier_is_code_and_kept(self):
        # `$state.name` reads `state`; only `.name` is literal text. v1.14.0
        # blanked the identifier as if it were literal and hid the read.
        out = blank_string_literals("log('at $state.name');")
        assert out == "log('   $state     ');"

    def test_simple_interpolation_ends_at_the_first_non_identifier_character(self):
        # `$stateful` interpolates `stateful` — kept whole, so a matcher for
        # `state` sees a longer identifier and not `state`.
        assert blank_string_literals("log('a $stateful b');") == "log('  $stateful  ');"
        assert blank_string_literals("log('$state_x $state2');") == "log('$state_x $state2');"

    def test_adjacent_simple_interpolations_are_all_kept(self):
        assert blank_string_literals("log('$a$state');") == "log('$a$state');"

    def test_this_is_a_simple_interpolation(self):
        assert blank_string_literals('log("x $this.state");') == 'log("  $this      ");'

    def test_literal_dollar_signs_are_blanked(self):
        # `$` followed by neither `{` nor an identifier start is a literal `$`.
        assert blank_string_literals("log('costs $5 and $');") == "log('              ');"
        # `$$state`: the first `$` is literal, the second opens `$state`.
        assert blank_string_literals("log('$$state');") == "log(' $state');"

    def test_simple_interpolation_in_double_and_triple_quoted_strings(self):
        assert blank_string_literals('log("v $state");') == 'log("  $state");'
        out = blank_string_literals("log('''a $state\nb $ref.read''');")
        assert out == "log('''  $state\n  $ref     ''');"

    def test_simple_interpolation_in_adjacent_strings(self):
        out = blank_string_literals("log('a ' 'b $state');")
        assert out == "log('  ' '  $state');"

    def test_simple_interpolation_nested_in_a_braced_interpolation(self):
        out = blank_string_literals("log('${'$state'}');")
        assert out == "log('${'$state'}');"
        out = blank_string_literals("log('x ${f('y $state z')} w');")
        assert out == "log('  ${f('  $state  ')}  ');"

    def test_raw_string_has_no_interpolation(self):
        assert blank_string_literals("log(r'$state');") == "log(r'      ');"
        interior = "a ${state} $ref"
        assert blank_string_literals(f'log(r"{interior}");') == f'log(r"{" " * len(interior)}");'
        assert blank_string_literals("log(r'''\n$state\n''');") == "log(r'''\n      \n''');"

    def test_interpolation_keeps_length_and_newlines(self):
        src = "log('$a ${b} \\$c $$d $e_f');\nlog('''\n$g\n''');"
        out = blank_string_literals(src)
        assert len(out) == len(src) and out.count("\n") == src.count("\n")

    def test_escaped_dollar_does_not_open_an_interpolation(self):
        assert "ref.read" not in blank_string_literals("log('cost \\${ref.read(x)}');")
        # ...nor a simple one: `\$state` is the literal text `$state`.
        interior = "cost \\$state"
        assert blank_string_literals(f"log('{interior}');") == f"log('{' ' * len(interior)}');"

    def test_nested_string_inside_interpolation_is_blanked_recursively(self):
        out = blank_string_literals("log('a ${f('ref.read(y)')} b');")
        assert "f(" in out
        assert "ref.read" not in out

    def test_double_quoted_triple_quoted_and_raw_strings(self):
        assert "ref.read" not in blank_string_literals('log("ref.read(a)");')
        assert "ref.read" not in blank_string_literals("log('''\nref.read(a)\n''');")
        assert "ref.read" not in blank_string_literals("log(r'ref.read(a)');")

    def test_comment_markers_inside_strings_are_not_comments(self):
        out = blank_string_literals("final u = 'https://x.io'; ref.read(p);")
        assert "ref.read(p);" in out

    def test_quote_inside_a_comment_does_not_open_a_string(self):
        out = blank_string_literals("// don't do this\nref.read(p);")
        assert "ref.read(p);" in out

    def test_unterminated_string_stops_at_the_newline(self):
        out = blank_string_literals("log('oops\nref.read(p);")
        assert "ref.read(p);" in out

    def test_empty_string_and_adjacent_code_are_untouched(self):
        assert blank_string_literals("a('', b);") == "a('', b);"

    def test_code_without_strings_is_returned_unchanged(self):
        src = "final a = ref.read(p);\nstate = a;"
        assert blank_string_literals(src) == src
