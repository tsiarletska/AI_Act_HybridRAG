from app.docs import render_markdown


def test_lists_without_blank_line_and_nested_lists_render():
    html = render_markdown("**Agent actions:**\n- one\n- two\n  - nested a\n  - nested b\n- three\n\nText")
    assert html.count("<ul>") == 2 and "<li>one</li>" in html and "<li>nested a</li>" in html


def test_code_blocks_untouched():
    html = render_markdown("Run:\n```\n- not a list\n```")
    assert "<li>" not in html
