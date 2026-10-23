import json
import pytest
from localdesign import components as C


def test_example_spec_renders_full_document():
    html = C.render(C.EXAMPLE_SPEC, 1280)
    assert html.startswith("<!DOCTYPE html>") and html.endswith("</html>")
    assert "Good afternoon, Mara" in html and "412.6 MWh" in html
    assert "<svg" in html                       # chart rendered as inline SVG
    assert "ld-badge" in html                    # badge_col applied


@pytest.mark.parametrize("node_type", sorted(C.NODES))
def test_every_node_type_renders_without_error(node_type):
    node = {"type": node_type, "text": "x", "title": "T", "label": "L", "value": 40, "kind": "bar",
            "items": [{"title": "a", "sub": "b", "label": "L", "k": "k", "v": "v", "time": "9:00", "text": "t", "from": "me", "icon": "★", "on": True}],
            "children": [{"type": "text", "text": "c"}],
            "fields": [{"label": "Email", "type": "email"}, {"label": "Plan", "type": "select", "options": ["A"]}, {"label": "On", "type": "toggle", "on": True}],
            "tiers": [{"name": "Pro", "price": "$12", "features": ["a"], "highlight": True}],
            "series": [{"name": "s", "values": [1, 2, 3]}], "labels": ["a", "b", "c"],
            "columns": ["A", "B"], "rows": [["1", "Online"]], "badge_col": 1, "messages": [{"from": "me", "text": "hi"}]}
    out = C.render_node(node, {"data": {}})
    assert "ld-alert error" not in out


def test_unknown_node_falls_back_to_text():
    assert "mystery text" in C.render_node({"type": "nonsense", "text": "mystery text"}, {"data": {}})


def test_bad_node_does_not_raise():
    out = C.render_node({"type": "chart", "series": "not-a-list"}, {"data": {}})
    assert isinstance(out, str)


def test_mobile_width_forces_mobile_layout():
    html = C.render({"layout": "sidebar", "sections": [{"type": "text", "text": "x"}]}, 390)
    assert 'class="ld-app mobile"' in html


def test_data_source_fills_table_with_case_insensitive_columns():
    spec = {"sections": [{"type": "table", "columns": ["Order", "Customer"], "data": "orders"}]}
    data = {"orders": [{"order": "#1", "customer": "Mara"}, {"order": "#2", "customer": "Theo"}]}
    html = C.render(spec, 1280, None, data)
    assert html.count("<tr>") == 3 and "Mara" in html and "Theo" in html


def test_data_source_falls_back_to_data_keys_when_columns_dont_match():
    spec = {"sections": [{"type": "table", "columns": ["Zzz", "Yyy"], "data": "d"}]}
    html = C.render(spec, 1280, None, {"d": [{"name": "n1", "qty": 3}]})
    assert "<th>name</th>" in html and "n1" in html


def test_design_system_tokens_override_spec_tokens():
    spec = {"tokens": {"primary": "#111111"}, "sections": []}
    html = C.render(spec, 1280, {"tokens": {"primary": "#5b4bff", "font": "Inter", "radius": 4}})
    assert "--primary:#5b4bff" in html and "--font:Inter" in html and "--r:4px" in html


def test_dark_theme_palette():
    html = C.render({"tokens": {"theme": "dark"}, "sections": []}, 1280)
    assert "--bg:#0f1115" in html


def test_named_colors_resolve():
    assert C._color("teal", "#000") == "#0d9488" and C._color("#abc", "#000") == "#abc" and C._color("nope", "#000") == "#000"


@pytest.mark.parametrize("frag", [
    '{"title":"A","sections":[{"type":"hero","title":"Big',
    '{"title":"A","sections":[{"type":"hero",',
    '{"tokens":{"primary":',
    '{"sections":[{"type":"chart","series":[{"values":[1,2,',
    '{"a":tru',
    '{"a":"b",',
])
def test_repair_json_closes_truncated_documents(frag):
    json.loads(C.repair_json(frag))


def test_extract_json_handles_fences_and_chatter():
    text = "Sure!\n```json\n" + json.dumps(C.EXAMPLE_SPEC) + "\n```\nHope that helps"
    assert C.extract_json(text)["title"] == "Fleet overview"


def test_extract_json_repairs_truncated_reply():
    text = json.dumps(C.EXAMPLE_SPEC)[:200]
    out = C.extract_json(text)
    assert isinstance(out, dict) and out.get("title") == "Fleet overview"


def test_extract_json_raises_without_object():
    with pytest.raises(ValueError):
        C.extract_json("no json here")


def test_links_become_data_link_attributes():
    html = C.render({"sections": [{"type": "buttons", "items": [{"label": "Go", "link": "Second"}]}]}, 1280)
    assert 'data-link="Second"' in html
