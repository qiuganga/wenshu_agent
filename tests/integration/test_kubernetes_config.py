from pathlib import Path

import yaml

K8S_DIR = Path("deploy/kubernetes")


def load_yaml(name: str) -> dict:
    return yaml.safe_load((K8S_DIR / name).read_text(encoding="utf-8"))


def test_kubernetes_deployment_has_replicas_probes_resources_and_non_root():
    deployment = load_yaml("deployment.yaml")
    spec = deployment["spec"]["template"]["spec"]
    container = spec["containers"][0]

    assert deployment["spec"]["replicas"] == 2
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["terminationGracePeriodSeconds"] >= 30
    assert container["readinessProbe"]["httpGet"]["path"] == "/health/ready"
    assert container["livenessProbe"]["httpGet"]["path"] == "/health/live"
    assert container["resources"]["requests"]["cpu"]
    assert container["resources"]["limits"]["memory"]


def test_kubernetes_secret_example_uses_placeholders_not_real_values():
    secret = load_yaml("secret.example.yaml")
    values = secret["stringData"]

    assert values
    assert values["LLM_API_KEY"] == "your_api_key_here"
    assert values["DB_META_PASSWORD"] == "change_me"
    assert values["DB_DW_PASSWORD"] == "change_me"
    assert values["REDIS_PASSWORD"] == "change_me"


def test_hpa_scales_between_two_and_ten():
    hpa = load_yaml("hpa.yaml")

    assert hpa["spec"]["minReplicas"] == 2
    assert hpa["spec"]["maxReplicas"] == 10
    assert {metric["type"] for metric in hpa["spec"]["metrics"]} == {"Resource"}
