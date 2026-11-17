from obs_html.render import base_definition_error

TABLE = {"type": "table", "name": "T", "order": ["file.name"]}


def test_a_view_projection_that_ends_in_a_line_break_fails_at_its_field() -> None:
    error = base_definition_error({"obsHtml": {"viewProjection": "mapping\n"}, "views": [dict(TABLE)]}, "t.base")
    assert error is not None and (error.source, error.field) == ("t.base", "obsHtml.viewProjection")
