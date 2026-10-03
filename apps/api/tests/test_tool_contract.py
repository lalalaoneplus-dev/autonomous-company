from app.main import tools


def test_registered_tools_publish_their_parameter_schema():
    registered = tools(None)
    assert registered
    assert all(item["parameter_schema"]["properties"]["action_type"] for item in registered)
