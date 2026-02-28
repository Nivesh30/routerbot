"""Unit tests for the Kubernetes operator module (Task 8J).

Covers: models, CRD schemas, operator CRUD/reconcile, autoscaler, health manager.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestModels:
    """Pydantic model validation tests."""

    def test_resource_phase_values(self) -> None:
        from routerbot.k8s.models import ResourcePhase

        assert ResourcePhase.PENDING == "Pending"
        assert ResourcePhase.RUNNING == "Running"
        assert ResourcePhase.FAILED == "Failed"

    def test_health_status_values(self) -> None:
        from routerbot.k8s.models import HealthStatus

        assert HealthStatus.HEALTHY == "Healthy"
        assert HealthStatus.DEGRADED == "Degraded"
        assert HealthStatus.UNHEALTHY == "Unhealthy"
        assert HealthStatus.UNKNOWN == "Unknown"

    def test_scaling_direction_values(self) -> None:
        from routerbot.k8s.models import ScalingDirection

        assert ScalingDirection.UP == "up"
        assert ScalingDirection.DOWN == "down"
        assert ScalingDirection.NONE == "none"

    def test_object_meta_defaults(self) -> None:
        from routerbot.k8s.models import ObjectMeta

        m = ObjectMeta()
        assert m.namespace == "default"
        assert m.labels == {}
        assert m.generation == 1

    def test_gateway_spec_defaults(self) -> None:
        from routerbot.k8s.models import GatewaySpec

        s = GatewaySpec()
        assert s.replicas == 1
        assert s.image == "routerbot:latest"
        assert s.port == 8000
        assert s.autoscaling is None

    def test_gateway_spec_validation(self) -> None:
        from pydantic import ValidationError

        from routerbot.k8s.models import GatewaySpec

        with pytest.raises(ValidationError):
            GatewaySpec(replicas=0)  # ge=1

    def test_resource_requirements_defaults(self) -> None:
        from routerbot.k8s.models import ResourceRequirements

        r = ResourceRequirements()
        assert r.cpu_request == "100m"
        assert r.memory_limit == "1Gi"

    def test_autoscaling_spec_defaults(self) -> None:
        from routerbot.k8s.models import AutoscalingSpec

        a = AutoscalingSpec()
        assert a.enabled is True
        assert a.min_replicas == 1
        assert a.max_replicas == 10
        assert a.target_cpu_percent == 70
        assert a.scale_up_cooldown_seconds == 60
        assert a.scale_down_cooldown_seconds == 300

    def test_health_check_spec_defaults(self) -> None:
        from routerbot.k8s.models import HealthCheckSpec

        h = HealthCheckSpec()
        assert h.liveness_path == "/health"
        assert h.readiness_path == "/ready"

    def test_llm_gateway_defaults(self) -> None:
        from routerbot.k8s.models import LLMGateway

        gw = LLMGateway()
        assert gw.kind == "LLMGateway"
        assert gw.api_version == "routerbot.io/v1alpha1"

    def test_model_spec_defaults(self) -> None:
        from routerbot.k8s.models import ModelSpec

        s = ModelSpec()
        assert s.max_tokens == 4096
        assert s.temperature == 0.7
        assert s.enabled is True

    def test_llm_model_defaults(self) -> None:
        from routerbot.k8s.models import LLMModel

        m = LLMModel()
        assert m.kind == "LLMModel"

    def test_key_spec_defaults(self) -> None:
        from routerbot.k8s.models import KeySpec

        k = KeySpec()
        assert k.budget_limit == 0.0
        assert k.enabled is True

    def test_llm_key_defaults(self) -> None:
        from routerbot.k8s.models import LLMKey

        k = LLMKey()
        assert k.kind == "LLMKey"

    def test_team_spec_defaults(self) -> None:
        from routerbot.k8s.models import TeamSpec

        t = TeamSpec()
        assert t.max_keys == 10
        assert t.rate_limit_rpm == 120

    def test_llm_team_defaults(self) -> None:
        from routerbot.k8s.models import LLMTeam

        t = LLMTeam()
        assert t.kind == "LLMTeam"

    def test_reconcile_event_defaults(self) -> None:
        from routerbot.k8s.models import ReconcileEvent

        e = ReconcileEvent()
        assert e.namespace == "default"
        assert e.action == ""

    def test_scaling_event_defaults(self) -> None:
        from routerbot.k8s.models import ScalingDirection, ScalingEvent

        e = ScalingEvent()
        assert e.direction == ScalingDirection.NONE

    def test_pod_health_defaults(self) -> None:
        from routerbot.k8s.models import HealthStatus, PodHealth

        p = PodHealth()
        assert p.status == HealthStatus.UNKNOWN
        assert p.ready is False

    def test_k8s_operator_config_defaults(self) -> None:
        from routerbot.k8s.models import K8sOperatorConfig

        cfg = K8sOperatorConfig()
        assert cfg.enabled is False
        assert cfg.reconcile_interval_seconds == 30
        assert cfg.autoscale_enabled is True


# ---------------------------------------------------------------------------
# CRD Schemas
# ---------------------------------------------------------------------------


class TestCRDSchemas:
    """CRD schema generation tests."""

    def test_register_all_crds(self) -> None:
        from routerbot.k8s.crd_schemas import register_all_crds

        crds = register_all_crds()
        assert "LLMGateway" in crds
        assert "LLMModel" in crds
        assert "LLMKey" in crds
        assert "LLMTeam" in crds

    def test_crd_structure(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        crd = get_crd("LLMGateway")
        assert crd is not None
        assert crd["apiVersion"] == "apiextensions.k8s.io/v1"
        assert crd["kind"] == "CustomResourceDefinition"
        assert crd["spec"]["group"] == "routerbot.io"

    def test_crd_has_spec_and_status(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        crd = get_crd("LLMModel")
        assert crd is not None
        version = crd["spec"]["versions"][0]
        props = version["schema"]["openAPIV3Schema"]["properties"]
        assert "spec" in props
        assert "status" in props

    def test_crd_names(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        crd = get_crd("LLMKey")
        assert crd is not None
        names = crd["spec"]["names"]
        assert names["kind"] == "LLMKey"
        assert names["plural"] == "llmkeys"

    def test_list_crds(self) -> None:
        from routerbot.k8s.crd_schemas import list_crds

        kinds = list_crds()
        assert len(kinds) == 4
        assert "LLMGateway" in kinds

    def test_get_crd_nonexistent(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        assert get_crd("Nonexistent") is None

    def test_crd_subresources(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        crd = get_crd("LLMTeam")
        assert crd is not None
        version = crd["spec"]["versions"][0]
        assert "status" in version["subresources"]

    def test_crd_printer_columns(self) -> None:
        from routerbot.k8s.crd_schemas import get_crd

        crd = get_crd("LLMGateway")
        assert crd is not None
        columns = crd["spec"]["versions"][0]["additionalPrinterColumns"]
        names = [c["name"] for c in columns]
        assert "Phase" in names
        assert "Age" in names


# ---------------------------------------------------------------------------
# Operator
# ---------------------------------------------------------------------------


class TestOperator:
    """Operator CRUD and reconciliation tests."""

    def _make_gateway(self, name: str = "test-gw", replicas: int = 2) -> object:
        from routerbot.k8s.models import GatewaySpec, LLMGateway, ObjectMeta

        return LLMGateway(
            metadata=ObjectMeta(name=name, namespace="default"),
            spec=GatewaySpec(replicas=replicas),
        )

    def _make_model(self, name: str = "gpt4", provider: str = "openai") -> object:
        from routerbot.k8s.models import LLMModel, ModelSpec, ObjectMeta

        return LLMModel(
            metadata=ObjectMeta(name=name),
            spec=ModelSpec(provider=provider, model_name=name),
        )

    def test_apply_gateway_create(self) -> None:
        from routerbot.k8s.models import ResourcePhase
        from routerbot.k8s.operator import Operator

        op = Operator()
        gw = self._make_gateway()
        result = op.apply_gateway(gw)
        assert result.status.phase == ResourcePhase.RUNNING
        assert result.status.replicas == 2
        assert result.metadata.uid != ""
        assert len(op.events) == 1
        assert op.events[0].action == "Created"

    def test_apply_gateway_update(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        gw = self._make_gateway(replicas=2)
        op.apply_gateway(gw)

        gw2 = self._make_gateway(replicas=5)
        result = op.apply_gateway(gw2)
        assert result.status.replicas == 5
        assert result.metadata.generation == 2
        assert len(op.events) == 2
        assert op.events[1].action == "Updated"

    def test_delete_gateway(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_gateway(self._make_gateway())
        assert op.delete_gateway("default", "test-gw") is True
        assert op.delete_gateway("default", "test-gw") is False
        assert op.get_gateway("default", "test-gw") is None

    def test_list_gateways(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_gateway(self._make_gateway("gw1"))
        op.apply_gateway(self._make_gateway("gw2"))
        assert len(op.list_gateways()) == 2
        assert len(op.list_gateways(namespace="default")) == 2
        assert len(op.list_gateways(namespace="other")) == 0

    def test_apply_model(self) -> None:
        from routerbot.k8s.models import ResourcePhase
        from routerbot.k8s.operator import Operator

        op = Operator()
        model = self._make_model()
        result = op.apply_model(model)
        assert result.status.phase == ResourcePhase.RUNNING
        assert result.status.healthy is True

    def test_apply_model_disabled(self) -> None:
        from routerbot.k8s.models import LLMModel, ModelSpec, ObjectMeta, ResourcePhase
        from routerbot.k8s.operator import Operator

        op = Operator()
        model = LLMModel(
            metadata=ObjectMeta(name="disabled-model"),
            spec=ModelSpec(enabled=False),
        )
        result = op.apply_model(model)
        assert result.status.phase == ResourcePhase.PENDING
        assert result.status.healthy is False

    def test_delete_model(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_model(self._make_model())
        assert op.delete_model("default", "gpt4") is True
        assert op.delete_model("default", "gpt4") is False

    def test_list_models(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_model(self._make_model("m1"))
        op.apply_model(self._make_model("m2"))
        assert len(op.list_models()) == 2

    def test_apply_key(self) -> None:
        from routerbot.k8s.models import KeySpec, LLMKey, ObjectMeta, ResourcePhase
        from routerbot.k8s.operator import Operator

        op = Operator()
        key = LLMKey(
            metadata=ObjectMeta(name="key1"),
            spec=KeySpec(owner="user1"),
        )
        result = op.apply_key(key)
        assert result.status.phase == ResourcePhase.RUNNING
        assert result.status.active is True

    def test_apply_key_disabled(self) -> None:
        from routerbot.k8s.models import KeySpec, LLMKey, ObjectMeta, ResourcePhase
        from routerbot.k8s.operator import Operator

        op = Operator()
        key = LLMKey(
            metadata=ObjectMeta(name="key-off"),
            spec=KeySpec(enabled=False),
        )
        result = op.apply_key(key)
        assert result.status.phase == ResourcePhase.PENDING
        assert result.status.active is False

    def test_delete_key(self) -> None:
        from routerbot.k8s.models import LLMKey, ObjectMeta
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_key(LLMKey(metadata=ObjectMeta(name="k1")))
        assert op.delete_key("default", "k1") is True
        assert op.delete_key("default", "k1") is False

    def test_list_keys(self) -> None:
        from routerbot.k8s.models import LLMKey, ObjectMeta
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_key(LLMKey(metadata=ObjectMeta(name="k1")))
        op.apply_key(LLMKey(metadata=ObjectMeta(name="k2")))
        assert len(op.list_keys()) == 2

    def test_apply_team(self) -> None:
        from routerbot.k8s.models import LLMTeam, ObjectMeta, ResourcePhase, TeamSpec
        from routerbot.k8s.operator import Operator

        op = Operator()
        team = LLMTeam(
            metadata=ObjectMeta(name="eng"),
            spec=TeamSpec(display_name="Engineering", members=["alice", "bob"]),
        )
        result = op.apply_team(team)
        assert result.status.phase == ResourcePhase.RUNNING

    def test_team_counts_active_keys(self) -> None:
        from routerbot.k8s.models import KeySpec, LLMKey, LLMTeam, ObjectMeta, TeamSpec
        from routerbot.k8s.operator import Operator

        op = Operator()
        # Create team
        op.apply_team(
            LLMTeam(
                metadata=ObjectMeta(name="eng"),
                spec=TeamSpec(display_name="Eng"),
            )
        )
        # Create keys referencing the team
        op.apply_key(
            LLMKey(
                metadata=ObjectMeta(name="k1"),
                spec=KeySpec(owner="alice", team_ref="eng"),
            )
        )
        op.apply_key(
            LLMKey(
                metadata=ObjectMeta(name="k2"),
                spec=KeySpec(owner="bob", team_ref="eng"),
            )
        )
        # Re-reconcile team to count keys
        team = op.get_team("default", "eng")
        assert team is not None
        op.reconcile_team("default/eng")
        team = op.get_team("default", "eng")
        assert team.status.active_keys == 2

    def test_delete_team(self) -> None:
        from routerbot.k8s.models import LLMTeam, ObjectMeta
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_team(LLMTeam(metadata=ObjectMeta(name="t1")))
        assert op.delete_team("default", "t1") is True
        assert op.delete_team("default", "t1") is False

    def test_reconcile_all(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_gateway(self._make_gateway())
        op.apply_model(self._make_model())
        op.clear_events()
        op.reconcile_all()
        # reconcile_all just ensures convergence, no new events for already running resources

    def test_stats(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_gateway(self._make_gateway())
        op.apply_model(self._make_model())
        s = op.stats()
        assert s["gateways"] == 1
        assert s["models"] == 1
        assert s["events"] >= 2

    def test_clear_events(self) -> None:
        from routerbot.k8s.operator import Operator

        op = Operator()
        op.apply_gateway(self._make_gateway())
        assert len(op.events) > 0
        op.clear_events()
        assert len(op.events) == 0


# ---------------------------------------------------------------------------
# Autoscaler
# ---------------------------------------------------------------------------


class TestAutoscaler:
    """Autoscaling tests."""

    def _make_gateway(self, replicas: int = 2, autoscaling: object = None) -> object:
        from routerbot.k8s.models import (
            AutoscalingSpec,
            GatewaySpec,
            GatewayStatus,
            LLMGateway,
            ObjectMeta,
            ResourcePhase,
        )

        return LLMGateway(
            metadata=ObjectMeta(name="test-gw"),
            spec=GatewaySpec(
                replicas=replicas,
                autoscaling=autoscaling
                or AutoscalingSpec(
                    min_replicas=1,
                    max_replicas=10,
                    target_cpu_percent=70,
                    scale_up_cooldown_seconds=0,
                    scale_down_cooldown_seconds=0,
                ),
            ),
            status=GatewayStatus(
                phase=ResourcePhase.RUNNING,
                replicas=replicas,
                ready_replicas=replicas,
            ),
        )

    def test_no_autoscaling_when_disabled(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import GatewaySpec, GatewayStatus, LLMGateway, ObjectMeta, ScalingDirection

        gw = LLMGateway(
            metadata=ObjectMeta(name="gw"),
            spec=GatewaySpec(autoscaling=None),
            status=GatewayStatus(replicas=2),
        )
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 100})
        assert event.direction == ScalingDirection.NONE

    def test_scale_up_on_high_cpu(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import ScalingDirection

        gw = self._make_gateway(replicas=2)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 140})
        # 140/70 = 2.0 ratio, ceil(2*2.0) = 4
        assert event.direction == ScalingDirection.UP
        assert event.to_replicas == 4

    def test_scale_down_on_low_cpu(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import ScalingDirection

        gw = self._make_gateway(replicas=4)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 20})
        # 20/70 = 0.29, ceil(4*0.29) = 2
        assert event.direction == ScalingDirection.DOWN
        assert event.to_replicas < 4

    def test_no_scale_when_at_target(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import ScalingDirection

        gw = self._make_gateway(replicas=2)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 70})
        # 70/70 = 1.0, ceil(2*1.0) = 2 → no change
        assert event.direction == ScalingDirection.NONE

    def test_clamp_to_max_replicas(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler

        gw = self._make_gateway(replicas=5)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 500})
        # 500/70 = 7.14, ceil(5*7.14) = 36, clamped to max=10
        assert event.to_replicas == 10

    def test_clamp_to_min_replicas(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler

        gw = self._make_gateway(replicas=5)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 1})
        # 1/70 = 0.014, ceil(5*0.014) = 1, min=1
        assert event.to_replicas >= 1

    def test_rps_based_scaling(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import AutoscalingSpec, ScalingDirection

        gw = self._make_gateway(
            replicas=2,
            autoscaling=AutoscalingSpec(
                target_rps=100,
                scale_up_cooldown_seconds=0,
                scale_down_cooldown_seconds=0,
            ),
        )
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"rps": 300})
        # 300/100 = 3.0, ceil(2*3) = 6
        assert event.direction == ScalingDirection.UP
        assert event.to_replicas == 6

    def test_apply_scaling(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import ScalingDirection

        gw = self._make_gateway(replicas=2)
        scaler = Autoscaler()
        event = scaler.evaluate(gw, {"cpu_percent": 140})
        assert event.direction == ScalingDirection.UP
        scaler.apply_scaling(gw, event)
        assert gw.spec.replicas == event.to_replicas

    def test_cooldown_blocks_scale(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler
        from routerbot.k8s.models import AutoscalingSpec, ScalingDirection

        gw = self._make_gateway(
            replicas=2,
            autoscaling=AutoscalingSpec(
                scale_up_cooldown_seconds=600,  # 10 min cooldown
                scale_down_cooldown_seconds=600,
            ),
        )
        scaler = Autoscaler()
        # First scale up works
        event1 = scaler.evaluate(gw, {"cpu_percent": 200})
        assert event1.direction == ScalingDirection.UP
        scaler.apply_scaling(gw, event1)
        # Second scale up blocked by cooldown
        event2 = scaler.evaluate(gw, {"cpu_percent": 200})
        assert event2.direction == ScalingDirection.NONE
        assert "Cooldown" in event2.reason

    def test_stats(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler

        gw = self._make_gateway(replicas=2)
        scaler = Autoscaler()
        scaler.evaluate(gw, {"cpu_percent": 200})
        s = scaler.stats()
        assert s["total_events"] >= 1
        assert s["scale_ups"] >= 1

    def test_clear_events(self) -> None:
        from routerbot.k8s.autoscaler import Autoscaler

        gw = self._make_gateway(replicas=2)
        scaler = Autoscaler()
        scaler.evaluate(gw, {"cpu_percent": 200})
        assert len(scaler.events) > 0
        scaler.clear_events()
        assert len(scaler.events) == 0


# ---------------------------------------------------------------------------
# Health Manager
# ---------------------------------------------------------------------------


class TestHealthManager:
    """Health management tests."""

    def _make_gateway(self) -> object:
        from routerbot.k8s.models import (
            GatewaySpec,
            GatewayStatus,
            LLMGateway,
            ObjectMeta,
            ResourcePhase,
        )

        return LLMGateway(
            metadata=ObjectMeta(name="test-gw"),
            spec=GatewaySpec(replicas=3),
            status=GatewayStatus(
                phase=ResourcePhase.RUNNING,
                replicas=3,
                ready_replicas=3,
            ),
        )

    def test_all_healthy_pods(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import HealthStatus, PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=True, cpu_percent=30, memory_percent=40),
            PodHealth(pod_name="pod-2", ready=True, cpu_percent=25, memory_percent=35),
            PodHealth(pod_name="pod-3", ready=True, cpu_percent=28, memory_percent=38),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        assert mgr.evaluate_gateway_health(gw) == HealthStatus.HEALTHY

    def test_degraded_with_high_cpu(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import HealthStatus, PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=True, cpu_percent=95, memory_percent=40),
            PodHealth(pod_name="pod-2", ready=True, cpu_percent=25, memory_percent=35),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        assert mgr.evaluate_gateway_health(gw) == HealthStatus.DEGRADED

    def test_unhealthy_majority(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import HealthStatus, PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=False),
            PodHealth(pod_name="pod-2", ready=False),
            PodHealth(pod_name="pod-3", ready=True, cpu_percent=10, memory_percent=10),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        # 2 of 3 unhealthy (>= half)
        assert mgr.evaluate_gateway_health(gw) == HealthStatus.UNHEALTHY

    def test_unknown_when_no_pods(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import HealthStatus

        mgr = HealthManager()
        gw = self._make_gateway()
        assert mgr.evaluate_gateway_health(gw) == HealthStatus.UNKNOWN

    def test_remediate_restarts_unready(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=False),
            PodHealth(pod_name="pod-2", ready=True, cpu_percent=10, memory_percent=10),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        actions = mgr.check_and_remediate(gw)
        assert any("restart pod-1" in a for a in actions)

    def test_remediate_evicts_crashloop(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=False, restarts=10),
            PodHealth(pod_name="pod-2", ready=True, cpu_percent=10, memory_percent=10),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        actions = mgr.check_and_remediate(gw)
        assert any("evict pod-1" in a for a in actions)

    def test_remediate_warns_high_resource(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="pod-1", ready=True, cpu_percent=95, memory_percent=90),
            PodHealth(pod_name="pod-2", ready=True, cpu_percent=10, memory_percent=10),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        actions = mgr.check_and_remediate(gw)
        assert any("warn pod-1" in a for a in actions)

    def test_count_ready_pods(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        pods = [
            PodHealth(pod_name="pod-1", ready=True),
            PodHealth(pod_name="pod-2", ready=False),
            PodHealth(pod_name="pod-3", ready=True),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        assert mgr.count_ready_pods("test-gw") == 2

    def test_get_pod_health(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        pods = [PodHealth(pod_name="p1", ready=True)]
        mgr.report_pod_health("gw", "default", pods)
        result = mgr.get_pod_health("gw")
        assert len(result) == 1

    def test_stats(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        pods = [
            PodHealth(pod_name="p1", ready=True, cpu_percent=10, memory_percent=10),
            PodHealth(pod_name="p2", ready=False),
        ]
        mgr.report_pod_health("gw", "default", pods)
        s = mgr.stats()
        assert s["gateways_monitored"] == 1
        assert s["total_pods"] == 2
        assert s["healthy_pods"] == 1

    def test_clear_events(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [PodHealth(pod_name="p1", ready=False)]
        mgr.report_pod_health("test-gw", "default", pods)
        mgr.check_and_remediate(gw)
        assert len(mgr.events) > 0
        mgr.clear_events()
        assert len(mgr.events) == 0

    def test_unhealthy_sets_failed_phase(self) -> None:
        from routerbot.k8s.health_manager import HealthManager
        from routerbot.k8s.models import PodHealth, ResourcePhase

        mgr = HealthManager()
        gw = self._make_gateway()
        pods = [
            PodHealth(pod_name="p1", ready=False),
            PodHealth(pod_name="p2", ready=False),
        ]
        mgr.report_pod_health("test-gw", "default", pods)
        mgr.check_and_remediate(gw)
        assert gw.status.phase == ResourcePhase.FAILED
