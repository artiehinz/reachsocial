import importlib.util
from pathlib import Path

from reachsocial.catalog import InputField, ProviderConfig, ServiceDefinition

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release_provider_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("release_provider_acceptance", _SCRIPT)
assert _SPEC and _SPEC.loader
acceptance = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(acceptance)


def test_acceptance_ledger_counts_provider_units_and_never_stores_input() -> None:
    service = ServiceDefinition(
        id="x.profile",
        title="X Profile",
        platform="X",
        description="Profile",
        input_fields=[InputField(name="url", description="URL", format="url")],
        provider=ProviderConfig(name="scrapecreators"),
    )
    event = acceptance._event(
        stage=2,
        service=service,
        input_data={"url": "https://x.com/example"},
        outcome="passed",
        provider_units=1,
        upstream_cost_microusd=1_880,
        provider_reference="provider-private-reference",
    )

    assert acceptance._credited_units({"events": [event]}) == 1
    assert "https://x.com/example" not in repr(event)
    assert "provider-private-reference" not in repr(event)
    assert acceptance._already_passed({"events": [event]}, "x.profile")


def test_target_parser_and_stage_coverage_are_explicit() -> None:
    assert acceptance.parse_target("news.person=Artie Hinz") == ("news.person", "Artie Hinz")
    assert acceptance.STAGES[4] == (
        "facebook.profile",
        "reddit.post",
        "instagram.highlight",
    )


def test_recheck_mode_does_not_treat_an_existing_pass_as_a_skip() -> None:
    service = ServiceDefinition(
        id="x.profile",
        title="X Profile",
        platform="X",
        description="Profile",
        input_fields=[InputField(name="url", description="URL", format="url")],
        provider=ProviderConfig(name="scrapecreators"),
    )
    ledger = {
        "events": [
            acceptance._event(
                stage=2,
                service=service,
                input_data={"url": "https://x.com/example"},
                outcome="passed",
                provider_units=1,
                upstream_cost_microusd=1_880,
                provider_reference=None,
            )
        ]
    }

    assert acceptance._should_skip_service(ledger, "x.profile", recheck_passed=False)
    assert not acceptance._should_skip_service(ledger, "x.profile", recheck_passed=True)
