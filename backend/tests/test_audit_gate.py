from scripts.npm_audit_gate import advisories, check

HIGH = {"vulnerabilities": {"braces": {"via": [{"severity": "high", "url": "https://github.com/advisories/GHSA-aaaa"}]},
                            "micromatch": {"via": ["braces"]}}}  # fmt: skip
CLEAN: dict = {}


def test_a_high_advisory_is_found_and_names_in_the_chain_are_ignored():
    assert advisories(HIGH) == {("GHSA-aaaa", "high")}
    assert (
        advisories({"vulnerabilities": {"x": {"via": [{"severity": "low", "url": "u/GHSA-b"}]}}})
        == set()
    )


def test_an_accepted_dev_advisory_passes_but_any_production_one_fails():
    assert check(CLEAN, HIGH, {"GHSA-aaaa"}) == []
    assert check(HIGH, HIGH, {"GHSA-aaaa"})  # in production: never accepted
    assert check(CLEAN, HIGH, set())  # not in the accepted list


def test_the_accepted_risks_file_explains_each_exception():
    import json

    from scripts.npm_audit_gate import ACCEPTED

    for item in json.loads(ACCEPTED.read_text())["npm"]:
        assert item["reason"] and item["reviewed"] and item["review_again"]
