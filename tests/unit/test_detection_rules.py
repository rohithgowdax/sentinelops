"""
Unit tests for detection rule YAML loading.
"""
from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from sentinelops.detection.rules import DetectionRule, Operator, Aggregation, load_rules


VALID_RULES_YAML = textwrap.dedent("""\
    rules:
      - rule_id: rule-test-001
        name: Test Error Rate
        signal: metric
        metric: http.error_rate
        operator: gt
        threshold: 0.10
        window_seconds: 60
        severity: critical
        service_filter: payments-service
        enabled: true

      - rule_id: rule-test-002
        name: Disabled Rule
        signal: metric
        metric: http.latency.p99
        operator: gt
        threshold: 300
        window_seconds: 60
        severity: high
        enabled: false
""")


class TestLoadRules:
    def test_loads_enabled_rules_only(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(VALID_RULES_YAML)
        rules = load_rules(str(rules_file))
        assert len(rules) == 1  # rule-test-002 is disabled
        assert rules[0].rule_id == "rule-test-001"

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        rules = load_rules(str(tmp_path / "nonexistent.yaml"))
        assert rules == []

    def test_rule_fields_correct(self, tmp_path: Path) -> None:
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(VALID_RULES_YAML)
        rules = load_rules(str(rules_file))
        rule = rules[0]
        assert rule.metric == "http.error_rate"
        assert rule.operator == Operator.GT
        assert rule.threshold == pytest.approx(0.10)
        assert rule.window_seconds == 60
        assert rule.severity == "critical"
        assert rule.aggregation == Aggregation.LATEST  # default

    def test_invalid_rule_skipped_without_abort(self, tmp_path: Path) -> None:
        yaml_with_invalid = textwrap.dedent("""\
            rules:
              - rule_id: good-rule
                name: Good Rule
                signal: metric
                metric: http.error_rate
                operator: gt
                threshold: 0.10
                window_seconds: 60
                severity: critical
                enabled: true
              - not_rule: invalid
                missing_required_fields: true
        """)
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(yaml_with_invalid)
        # Should not raise; invalid rule is skipped
        rules = load_rules(str(rules_file))
        assert len(rules) == 1
        assert rules[0].rule_id == "good-rule"

    def test_loads_actual_config_file(self) -> None:
        """Smoke test: the committed config file parses without error."""
        rules = load_rules("config/detection_rules.yaml")
        assert len(rules) >= 2
