from reachsocial.provider_inventory import build_inventory


def test_inventory_is_review_only_and_excludes_account_utilities() -> None:
    spec = {
        "paths": {
            "/v1/instagram/profile": {
                "get": {
                    "tags": ["Instagram"],
                    "summary": "Profile",
                    "parameters": [{"name": "handle", "in": "query"}],
                }
            },
            "/v1/account/get-api-usage": {
                "get": {"tags": ["Account"], "summary": "Usage"}
            },
            "/v1/tiktok/user/followers": {
                "get": {"tags": ["TikTok"], "summary": "Followers"}
            },
        }
    }
    inventory = build_inventory(spec, source="fixture")
    assert inventory["summary"]["operations"] == 3
    by_id = {item["candidate_id"]: item for item in inventory["candidates"]}
    assert by_id["instagram.profile"]["review_state"] == "unreviewed"
    assert by_id["account.get-api-usage"]["review_state"] == "excluded"
    assert by_id["tiktok.user.followers"]["review_flags"] == ["followers"]
    assert "not ReachSocial services" in inventory["notice"]
