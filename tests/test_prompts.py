import pytest
from localdesign import prompts as P


def test_extract_html_strips_fences_and_chatter():
    assert P.extract_html("Sure! ```html\n<!DOCTYPE html><html><body>x</body></html>\n``` done") == "<!DOCTYPE html><html><body>x</body></html>"
    assert P.extract_html("<html><body>x</body></html>") == "<html><body>x</body></html>"


def test_partial_html_for_live_preview():
    assert P.partial_html("```html\n<!DOCTYPE html><html><he").startswith("<!DOCTYPE")
    assert P.partial_html("Here:\n<style>") == "<style>"
    assert P.partial_html("nothing yet") == ""


def test_extract_fragment_unwraps_full_documents():
    frag = P.extract_fragment("```html\n<!DOCTYPE html><html><head><style>.z{}</style></head><body><h1>Hi</h1></body></html>\n```")
    assert frag == "<style>.z{}</style><h1>Hi</h1>"
    assert P.extract_fragment("<button>x</button> trailing") == "<button>x</button>"
    assert P.extract_fragment("no tags") == ""


def test_extract_json_array_tolerates_fences_and_truncation():
    assert P.extract_json_array('```json\n[{"title":"A"}]\n```')[0]["title"] == "A"
    assert P.extract_json_array('[{"title":"A"},{"title":"B","brief":"cut')[0]["title"] == "A"
    with pytest.raises(ValueError):
        P.extract_json_array("none")


def test_spec_system_prompt_contains_schema_and_mobile_hint():
    p = P.spec_system_prompt(390, "Design direction: bold")
    assert "Node types" in p and "layout \"mobile\"" in p and "Design direction: bold" in p and "Fleet overview" in p
    assert "{width}" not in p and "{nodes}" not in p


def test_design_system_and_data_prompts():
    ds = {"name": "Acme", "tokens": {"primary": "#5b4bff", "font": ""}, "components": [{"name": "Btn", "html": "<button class=btn>x</button>"}], "css": ".btn{}", "notes": "Be nice"}
    html_p = P.design_system_prompt(ds, for_spec=False)
    assert "Design system: Acme." in html_p and '"primary":"#5b4bff"' in html_p and "<button class=btn>" in html_p and ".btn{}" in html_p and "Be nice" in html_p
    spec_p = P.design_system_prompt(ds, for_spec=True)
    assert "<button" not in spec_p and "#5b4bff" in spec_p
    d = P.data_prompt({"orders": [{"a": 1}] * 20}, for_spec=True)
    assert 'Source "orders" (20 rows)' in d and '"data": "<source name>"' in d
    assert P.design_system_prompt(None, True) == "" and P.data_prompt({}, True) == ""
