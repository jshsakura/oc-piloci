from piloci.tools._schema import compact_schema


def test_removes_title():
    schema = {"title": "Foo", "type": "object", "properties": {"x": {"title": "X", "type": "str"}}}
    result = compact_schema(schema)
    assert "title" not in result
    assert "title" not in result["properties"]["x"]


def test_flattens_nullable_anyof():
    schema = {"anyOf": [{"type": "string"}, {"type": "null"}]}
    result = compact_schema(schema)
    assert result == {"type": "string"}


def test_truncates_long_description():
    long_desc = "x" * 100
    schema = {"description": long_desc}
    result = compact_schema(schema)
    assert len(result["description"]) == 80


def test_removes_top_level_description():
    schema = {"description": "should be removed", "type": "object"}
    result = compact_schema(schema, _top=True)
    assert "description" not in result
