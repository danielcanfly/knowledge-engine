from runpy import run_path


def test_m8_boundary_query_targets_only_the_internal_fixture() -> None:
    module = run_path("scripts/m8_runtime_acceptance.py")
    assert module["BOUNDARY_QUERY"] == "quartz lantern protocol"
