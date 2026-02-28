"""Reconciliation operator for RouterBot Kubernetes resources.

Implements a control-loop pattern that watches CRD instances and
reconciles their desired state with the actual cluster state.
This is a *simulation* layer that doesn't require a live Kubernetes
cluster -- it manages in-memory resource state with the same
semantics a real operator would use.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from routerbot.k8s.models import (
    KeyStatus,
    LLMGateway,
    LLMKey,
    LLMModel,
    LLMTeam,
    ModelStatus,
    ReconcileEvent,
    ResourceCondition,
    ResourcePhase,
    TeamStatus,
)

logger = logging.getLogger(__name__)


class Operator:
    """RouterBot Kubernetes Operator (simulation).

    Manages the lifecycle of LLMGateway, LLMModel, LLMKey, and LLMTeam
    custom resources via a reconcile-loop pattern.
    """

    def __init__(self) -> None:
        self._gateways: dict[str, LLMGateway] = {}
        self._models: dict[str, LLMModel] = {}
        self._keys: dict[str, LLMKey] = {}
        self._teams: dict[str, LLMTeam] = {}
        self._events: list[ReconcileEvent] = []

    # ------------------------------------------------------------------
    # Gateway CRUD + reconcile
    # ------------------------------------------------------------------

    def apply_gateway(self, gateway: LLMGateway) -> LLMGateway:
        """Create or update an LLMGateway resource."""
        key = self._resource_key(gateway.metadata.namespace, gateway.metadata.name)
        existing = self._gateways.get(key)

        if existing is None:
            gateway.metadata.uid = str(uuid.uuid4())
            gateway.metadata.created_at = datetime.now(tz=UTC)
            gateway.status.phase = ResourcePhase.CREATING
            self._gateways[key] = gateway
            self._emit(
                kind="LLMGateway",
                name=gateway.metadata.name,
                ns=gateway.metadata.namespace,
                action="Created",
                message=f"Gateway {gateway.metadata.name} created",
            )
        else:
            gateway.metadata.uid = existing.metadata.uid
            gateway.metadata.created_at = existing.metadata.created_at
            gateway.metadata.generation = existing.metadata.generation + 1
            gateway.status = existing.status
            gateway.status.phase = ResourcePhase.UPDATING
            self._gateways[key] = gateway
            self._emit(
                kind="LLMGateway",
                name=gateway.metadata.name,
                ns=gateway.metadata.namespace,
                action="Updated",
                message=f"Gateway {gateway.metadata.name} updated (gen {gateway.metadata.generation})",
            )

        return self.reconcile_gateway(key)

    def reconcile_gateway(self, key: str) -> LLMGateway:
        """Reconcile a gateway to its desired state."""
        gw = self._gateways[key]
        spec = gw.spec
        status = gw.status

        # Simulate deployment convergence
        status.replicas = spec.replicas
        status.ready_replicas = spec.replicas
        status.available_replicas = spec.replicas
        status.observed_generation = gw.metadata.generation
        status.phase = ResourcePhase.RUNNING
        status.last_updated = datetime.now(tz=UTC)

        # Set condition
        status.conditions = [
            ResourceCondition(
                condition_type="Available",
                status="True",
                reason="DeploymentReady",
                message=f"{spec.replicas}/{spec.replicas} replicas available",
                last_transition=datetime.now(tz=UTC),
            ),
        ]
        return gw

    def delete_gateway(self, namespace: str, name: str) -> bool:
        """Delete a gateway resource."""
        key = self._resource_key(namespace, name)
        gw = self._gateways.pop(key, None)
        if gw is None:
            return False
        self._emit(
            kind="LLMGateway",
            name=name,
            ns=namespace,
            action="Deleted",
            message=f"Gateway {name} deleted",
        )
        return True

    def get_gateway(self, namespace: str, name: str) -> LLMGateway | None:
        return self._gateways.get(self._resource_key(namespace, name))

    def list_gateways(self, namespace: str | None = None) -> list[LLMGateway]:
        gateways = list(self._gateways.values())
        if namespace:
            gateways = [g for g in gateways if g.metadata.namespace == namespace]
        return gateways

    # ------------------------------------------------------------------
    # Model CRUD + reconcile
    # ------------------------------------------------------------------

    def apply_model(self, model: LLMModel) -> LLMModel:
        """Create or update an LLMModel resource."""
        key = self._resource_key(model.metadata.namespace, model.metadata.name)
        existing = self._models.get(key)

        if existing is None:
            model.metadata.uid = str(uuid.uuid4())
            model.metadata.created_at = datetime.now(tz=UTC)
            model.status = ModelStatus(phase=ResourcePhase.CREATING)
            self._models[key] = model
            self._emit(
                kind="LLMModel",
                name=model.metadata.name,
                ns=model.metadata.namespace,
                action="Created",
                message=f"Model {model.metadata.name} ({model.spec.provider}/{model.spec.model_name}) registered",
            )
        else:
            model.metadata.uid = existing.metadata.uid
            model.metadata.created_at = existing.metadata.created_at
            model.metadata.generation = existing.metadata.generation + 1
            model.status = existing.status
            model.status.phase = ResourcePhase.UPDATING
            self._models[key] = model
            self._emit(
                kind="LLMModel",
                name=model.metadata.name,
                ns=model.metadata.namespace,
                action="Updated",
                message=f"Model {model.metadata.name} updated",
            )

        return self.reconcile_model(key)

    def reconcile_model(self, key: str) -> LLMModel:
        """Reconcile a model to its desired state."""
        model = self._models[key]
        status = model.status

        if model.spec.enabled:
            status.phase = ResourcePhase.RUNNING
            status.healthy = True
        else:
            status.phase = ResourcePhase.PENDING
            status.healthy = False

        status.last_check = datetime.now(tz=UTC)
        status.conditions = [
            ResourceCondition(
                condition_type="Ready",
                status="True" if status.healthy else "False",
                reason="ModelEnabled" if model.spec.enabled else "ModelDisabled",
                message=f"Model is {'ready' if status.healthy else 'disabled'}",
                last_transition=datetime.now(tz=UTC),
            ),
        ]
        return model

    def delete_model(self, namespace: str, name: str) -> bool:
        key = self._resource_key(namespace, name)
        model = self._models.pop(key, None)
        if model is None:
            return False
        self._emit(
            kind="LLMModel", name=name, ns=namespace,
            action="Deleted", message=f"Model {name} deleted",
        )
        return True

    def get_model(self, namespace: str, name: str) -> LLMModel | None:
        return self._models.get(self._resource_key(namespace, name))

    def list_models(self, namespace: str | None = None) -> list[LLMModel]:
        models = list(self._models.values())
        if namespace:
            models = [m for m in models if m.metadata.namespace == namespace]
        return models

    # ------------------------------------------------------------------
    # Key CRUD + reconcile
    # ------------------------------------------------------------------

    def apply_key(self, key_resource: LLMKey) -> LLMKey:
        """Create or update an LLMKey resource."""
        rkey = self._resource_key(key_resource.metadata.namespace, key_resource.metadata.name)
        existing = self._keys.get(rkey)

        if existing is None:
            key_resource.metadata.uid = str(uuid.uuid4())
            key_resource.metadata.created_at = datetime.now(tz=UTC)
            key_resource.status = KeyStatus(phase=ResourcePhase.CREATING)
            self._keys[rkey] = key_resource
            self._emit(
                kind="LLMKey",
                name=key_resource.metadata.name,
                ns=key_resource.metadata.namespace,
                action="Created",
                message=f"Key {key_resource.metadata.name} created for {key_resource.spec.owner}",
            )
        else:
            key_resource.metadata.uid = existing.metadata.uid
            key_resource.metadata.created_at = existing.metadata.created_at
            key_resource.metadata.generation = existing.metadata.generation + 1
            key_resource.status = existing.status
            self._keys[rkey] = key_resource
            self._emit(
                kind="LLMKey",
                name=key_resource.metadata.name,
                ns=key_resource.metadata.namespace,
                action="Updated",
                message=f"Key {key_resource.metadata.name} updated",
            )

        return self.reconcile_key(rkey)

    def reconcile_key(self, rkey: str) -> LLMKey:
        """Reconcile a key to desired state."""
        key_resource = self._keys[rkey]
        status = key_resource.status

        if key_resource.spec.enabled:
            status.phase = ResourcePhase.RUNNING
            status.active = True
        else:
            status.phase = ResourcePhase.PENDING
            status.active = False

        status.conditions = [
            ResourceCondition(
                condition_type="Active",
                status="True" if status.active else "False",
                reason="KeyEnabled" if key_resource.spec.enabled else "KeyDisabled",
                message=f"Key is {'active' if status.active else 'disabled'}",
                last_transition=datetime.now(tz=UTC),
            ),
        ]
        return key_resource

    def delete_key(self, namespace: str, name: str) -> bool:
        rkey = self._resource_key(namespace, name)
        k = self._keys.pop(rkey, None)
        if k is None:
            return False
        self._emit(
            kind="LLMKey", name=name, ns=namespace,
            action="Deleted", message=f"Key {name} deleted",
        )
        return True

    def get_key(self, namespace: str, name: str) -> LLMKey | None:
        return self._keys.get(self._resource_key(namespace, name))

    def list_keys(self, namespace: str | None = None) -> list[LLMKey]:
        keys = list(self._keys.values())
        if namespace:
            keys = [k for k in keys if k.metadata.namespace == namespace]
        return keys

    # ------------------------------------------------------------------
    # Team CRUD + reconcile
    # ------------------------------------------------------------------

    def apply_team(self, team: LLMTeam) -> LLMTeam:
        """Create or update an LLMTeam resource."""
        key = self._resource_key(team.metadata.namespace, team.metadata.name)
        existing = self._teams.get(key)

        if existing is None:
            team.metadata.uid = str(uuid.uuid4())
            team.metadata.created_at = datetime.now(tz=UTC)
            team.status = TeamStatus(phase=ResourcePhase.CREATING)
            self._teams[key] = team
            self._emit(
                kind="LLMTeam",
                name=team.metadata.name,
                ns=team.metadata.namespace,
                action="Created",
                message=f"Team {team.metadata.name} created",
            )
        else:
            team.metadata.uid = existing.metadata.uid
            team.metadata.created_at = existing.metadata.created_at
            team.metadata.generation = existing.metadata.generation + 1
            team.status = existing.status
            self._teams[key] = team
            self._emit(
                kind="LLMTeam",
                name=team.metadata.name,
                ns=team.metadata.namespace,
                action="Updated",
                message=f"Team {team.metadata.name} updated",
            )

        return self.reconcile_team(key)

    def reconcile_team(self, key: str) -> LLMTeam:
        """Reconcile a team to desired state."""
        team = self._teams[key]
        status = team.status
        status.phase = ResourcePhase.RUNNING

        # Count active keys for this team
        active_keys = sum(
            1 for k in self._keys.values()
            if k.spec.team_ref == team.metadata.name and k.status.active
        )
        status.active_keys = active_keys
        status.conditions = [
            ResourceCondition(
                condition_type="Ready",
                status="True",
                reason="TeamReady",
                message=f"Team has {active_keys} active keys",
                last_transition=datetime.now(tz=UTC),
            ),
        ]
        return team

    def delete_team(self, namespace: str, name: str) -> bool:
        key = self._resource_key(namespace, name)
        team = self._teams.pop(key, None)
        if team is None:
            return False
        self._emit(
            kind="LLMTeam", name=name, ns=namespace,
            action="Deleted", message=f"Team {name} deleted",
        )
        return True

    def get_team(self, namespace: str, name: str) -> LLMTeam | None:
        return self._teams.get(self._resource_key(namespace, name))

    def list_teams(self, namespace: str | None = None) -> list[LLMTeam]:
        teams = list(self._teams.values())
        if namespace:
            teams = [t for t in teams if t.metadata.namespace == namespace]
        return teams

    # ------------------------------------------------------------------
    # Reconcile all
    # ------------------------------------------------------------------

    def reconcile_all(self) -> list[ReconcileEvent]:
        """Run a full reconciliation loop across all resources."""
        before = len(self._events)

        for key in list(self._gateways):
            self.reconcile_gateway(key)
        for key in list(self._models):
            self.reconcile_model(key)
        for key in list(self._keys):
            self.reconcile_key(key)
        for key in list(self._teams):
            self.reconcile_team(key)

        return self._events[before:]

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[ReconcileEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "gateways": len(self._gateways),
            "models": len(self._models),
            "keys": len(self._keys),
            "teams": len(self._teams),
            "events": len(self._events),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resource_key(namespace: str, name: str) -> str:
        return f"{namespace}/{name}"

    def _emit(
        self,
        *,
        kind: str,
        name: str,
        ns: str,
        action: str,
        message: str,
    ) -> None:
        self._events.append(
            ReconcileEvent(
                resource_kind=kind,
                resource_name=name,
                namespace=ns,
                action=action,
                message=message,
                timestamp=datetime.now(tz=UTC),
            ),
        )
