"""Durable authority and execution state for approval-required changes."""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import sqlite3
import subprocess
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple

from mox_adv.commands import (
    ACTION_SPECS,
    ActionFamily,
    OptimizationAction,
    calculate_relative_target,
)
from mox_adv.interrupt_state import (
    DurableInterruptState,
    InterruptStateUnavailable,
    kill_switch_scopes,
)


class ControlRejected(RuntimeError):
    """A control-plane operation failed closed."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(reason_code + ": " + detail)
        self.reason_code = reason_code


class ExecutionStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_FLIGHT = "IN_FLIGHT"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    BLOCKED = "BLOCKED"
    ALREADY_PROCESSED = "ALREADY_PROCESSED"
    UNKNOWN_RESULT = "UNKNOWN_RESULT"
    FAILED = "FAILED"


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return value.astimezone(timezone.utc).isoformat()


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ControlRejected("INVALID_INPUT", "timestamp must be ISO UTC.") from error
    if parsed.tzinfo is None:
        raise ControlRejected("INVALID_INPUT", "timestamp must be timezone-aware.")
    return parsed.astimezone(timezone.utc)


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    identity: str
    authentication: str


_ELEVATED_PRINCIPAL_SEAL = object()


@dataclass(frozen=True)
class ElevatedAuthenticatedPrincipal(AuthenticatedPrincipal):
    _seal: object

    @classmethod
    def verified(
        cls,
        principal: AuthenticatedPrincipal,
        verifier: "ElevatedReauthenticationVerifier",
    ) -> "ElevatedAuthenticatedPrincipal":
        if (
            type(principal) is not AuthenticatedPrincipal
            or type(verifier) is not MacOSElevatedSecurityVerifier
            or not verifier.verify(principal)
        ):
            raise ControlRejected(
                "ELEVATED_REAUTHENTICATION_FAILED",
                "elevated reauthentication did not succeed.",
            )
        return cls(
            identity=principal.identity,
            authentication=principal.authentication,
            _seal=_ELEVATED_PRINCIPAL_SEAL,
        )

    def is_verified(self) -> bool:
        return (
            type(self) is ElevatedAuthenticatedPrincipal
            and self._seal is _ELEVATED_PRINCIPAL_SEAL
        )


class ElevatedReauthenticationVerifier(Protocol):
    def verify(self, principal: AuthenticatedPrincipal) -> bool: ...


class MacOSElevatedSecurityVerifier:
    """Use the OS authorization cache without reading or accepting a secret."""

    def verify(self, principal: AuthenticatedPrincipal) -> bool:
        if principal.authentication != "authenticated_macos_user":
            return False
        try:
            completed = subprocess.run(
                ["/usr/bin/sudo", "-n", "-v"],
                check=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0


class MacOSLocalPrincipalAuthenticator:
    """Authenticate the Gate 0 control principal at the local OS seam."""

    def __init__(
        self,
        expected_identity: str = "sviridov",
        elevated_verifier: Optional[ElevatedReauthenticationVerifier] = None,
    ) -> None:
        if (
            elevated_verifier is not None
            and type(elevated_verifier) is not MacOSElevatedSecurityVerifier
        ):
            raise ControlRejected(
                "ELEVATED_REAUTHENTICATION_FAILED",
                "elevated verifier is not a trusted OS verifier.",
            )
        self.expected_identity = expected_identity
        self.elevated_verifier = (
            MacOSElevatedSecurityVerifier()
            if elevated_verifier is None
            else elevated_verifier
        )

    def authenticate(self) -> AuthenticatedPrincipal:
        identity = getpass.getuser()
        if identity != self.expected_identity:
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "local macOS user does not match the Gate 0 principal.",
            )
        return AuthenticatedPrincipal(
            identity=identity,
            authentication="authenticated_macos_user",
        )

    def elevated_reauthenticate(self) -> ElevatedAuthenticatedPrincipal:
        principal = self.authenticate()
        return ElevatedAuthenticatedPrincipal.verified(
            principal,
            self.elevated_verifier,
        )


class CampaignApprovalRepository:
    """Own every persistence transition for campaign-creation approvals."""

    @staticmethod
    def reserve(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        proposal_id: str,
        binding_hash: str,
        approver: str,
        authentication: str,
        execution_key: str,
        now_text: str,
        proof_verifier: Callable[[sqlite3.Row], None],
    ) -> None:
        approval = connection.execute(
            "SELECT * FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if approval is None:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_FOUND",
                "campaign approval does not exist.",
            )
        proof_verifier(approval)
        if (
            approval["status"] != "AVAILABLE"
            or approval["proposal_id"] != proposal_id
            or approval["binding_hash"] != binding_hash
            or approval["approver"] != approver
            or approval["authentication"] != authentication
            or approval["expires_at"] <= now_text
            or not str(approval["authority_hash"] or "").startswith("sha256:")
            or not approval["signature"]
            or not approval["issued_at"]
            or not approval["authority_json"]
        ):
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_AUTHORIZED",
                "campaign approval is not bound, current, and available.",
            )
        updated = connection.execute(
            "UPDATE campaign_approvals SET status = 'RESERVED', "
            "reserved_execution_key = ? WHERE approval_id = ? "
            "AND status = 'AVAILABLE'",
            (execution_key, approval_id),
        ).rowcount
        if updated != 1:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_ALREADY_USED",
                "campaign approval could not be reserved.",
            )

    @staticmethod
    def consume(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        execution_key: str,
        now_text: str,
    ) -> None:
        updated = connection.execute(
            "UPDATE campaign_approvals SET status = 'USED', used_at = ? "
            "WHERE approval_id = ? AND status = 'RESERVED' "
            "AND reserved_execution_key = ?",
            (now_text, approval_id, execution_key),
        ).rowcount
        if updated != 1:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_USE_FAILED",
                "campaign approval could not be consumed.",
            )

    @staticmethod
    def authority_is_valid(
        connection: sqlite3.Connection,
        *,
        approval_id: str,
        proposal_id: str,
        binding_hash: str,
        execution_key: str,
    ) -> bool:
        row = connection.execute(
            "SELECT proposal_id, binding_hash, status, reserved_execution_key "
            "FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        return bool(
            row is not None
            and row["proposal_id"] == proposal_id
            and row["binding_hash"] == binding_hash
            and row["status"] in {"RESERVED", "USED"}
            and row["reserved_execution_key"] == execution_key
        )

    @staticmethod
    def status(connection: sqlite3.Connection, approval_id: str) -> str:
        row = connection.execute(
            "SELECT status FROM campaign_approvals WHERE approval_id = ?",
            (approval_id,),
        ).fetchone()
        if row is None:
            raise ControlRejected(
                "CAMPAIGN_APPROVAL_NOT_FOUND",
                "campaign approval does not exist.",
            )
        return str(row["status"])


@dataclass(frozen=True)
class TrustedScope:
    organization: str
    connection: str
    account: str
    campaign: str
    writer: str


@dataclass(frozen=True)
class PreparedChange:
    proposal_id: str
    proposal_hash: str
    scope: TrustedScope
    action: OptimizationAction
    current_value: Any
    target_value: Any
    expected_diff: Mapping[str, Any]
    snapshot_id: str
    snapshot_generated_at: str
    direct_watermark: str
    metrika_watermark: str
    policy_version: str
    expected_fingerprint: str
    risk: str

    def as_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["expected_diff"] = dict(self.expected_diff)
        return value

    def binding_hash(self) -> str:
        return canonical_hash(self.as_dict())

    def execution_key(self) -> str:
        return canonical_hash(
            {
                "organization": self.scope.organization,
                "connection": self.scope.connection,
                "campaign": self.scope.campaign,
                "proposal_id": self.proposal_id,
                "proposal_hash": self.proposal_hash,
                "action": self.action,
                "target_value": self.target_value,
                "expected_fingerprint": self.expected_fingerprint,
                "policy_version": self.policy_version,
            }
        )

    def target_key(self) -> str:
        return ":".join(
            (
                self.scope.organization,
                self.scope.connection,
                self.scope.account,
                self.scope.campaign,
                self.action,
            )
        )

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreparedChange":
        scope = value["scope"]
        if not isinstance(scope, Mapping):
            raise ControlRejected("INVALID_INPUT", "prepared scope is invalid.")
        return cls(
            proposal_id=str(value["proposal_id"]),
            proposal_hash=str(value["proposal_hash"]),
            scope=TrustedScope(
                organization=str(scope["organization"]),
                connection=str(scope["connection"]),
                account=str(scope["account"]),
                campaign=str(scope["campaign"]),
                writer=str(scope["writer"]),
            ),
            action=OptimizationAction(value["action"]),
            current_value=value["current_value"],
            target_value=value["target_value"],
            expected_diff=dict(value["expected_diff"]),
            snapshot_id=str(value["snapshot_id"]),
            snapshot_generated_at=str(value["snapshot_generated_at"]),
            direct_watermark=str(value["direct_watermark"]),
            metrika_watermark=str(value["metrika_watermark"]),
            policy_version=str(value["policy_version"]),
            expected_fingerprint=str(value["expected_fingerprint"]),
            risk=str(value["risk"]),
        )


_PREPARED_AD_VARIANT_SEAL = object()


@dataclass(frozen=True)
class PreparedAdVariantCatalog:
    source_plan_hash: str
    variants: Tuple[Tuple[str, str, str], ...]
    _seal: object = field(repr=False, compare=False)

    @classmethod
    def from_campaign_plan(
        cls,
        canonical_plan: Mapping[str, Any],
    ) -> "PreparedAdVariantCatalog":
        try:
            if canonical_plan["schema_version"] != "campaign-creation-plan-v1":
                raise KeyError("schema_version")
            groups = canonical_plan["draft"]["groups"]
            ads = groups[0]["ads"]
            variants = {
                item["variant_id"]: {
                    "variant_id": item["variant_id"],
                    "title": item["title"],
                    "text": item["text"],
                }
                for item in ads
            }
        except (IndexError, KeyError, TypeError) as error:
            raise ControlRejected(
                "PREPARED_AD_COPY_UNAVAILABLE",
                "campaign plan has no trusted ad variants.",
            ) from error
        if (
            set(variants) != {"A", "B"}
            or any(
                type(value["variant_id"]) is not str
                or type(value["title"]) is not str
                or type(value["text"]) is not str
                or not value["title"].strip()
                or not value["text"].strip()
                for value in variants.values()
            )
        ):
            raise ControlRejected(
                "PREPARED_AD_COPY_UNAVAILABLE",
                "campaign plan ad variants are incomplete.",
            )
        return cls(
            source_plan_hash=canonical_hash(canonical_plan),
            variants=tuple(
                sorted(
                    (
                        variant_id,
                        value["title"],
                        value["text"],
                    )
                    for variant_id, value in variants.items()
                )
            ),
            _seal=_PREPARED_AD_VARIANT_SEAL,
        )

    def exact_copy(self, variant_id: str) -> Mapping[str, str]:
        variants = {
            item_id: {
                "variant_id": item_id,
                "title": title,
                "text": text,
            }
            for item_id, title, text in self.variants
        }
        try:
            value = variants[variant_id]
        except KeyError as error:
            raise ControlRejected(
                "PREPARED_AD_COPY_UNAVAILABLE",
                "requested ad variant is not prepared.",
            ) from error
        if (
            type(self) is not PreparedAdVariantCatalog
            or self._seal is not _PREPARED_AD_VARIANT_SEAL
            or not self.source_plan_hash.startswith("sha256:")
            or set(variants) != {"A", "B"}
            or set(value) != {"variant_id", "title", "text"}
            or value["variant_id"] != variant_id
            or not value["title"].strip()
            or not value["text"].strip()
        ):
            raise ControlRejected(
                "PREPARED_AD_COPY_UNAVAILABLE",
                "prepared ad variant catalog is invalid.",
            )
        return dict(value)


@dataclass(frozen=True)
class TerminalNoWritePlan:
    proposal_id: str
    proposal_hash: str
    snapshot_id: str
    policy_version: str
    status: str
    action: str
    reason_code: Optional[str]

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TerminalExecutionRequest:
    proposal_id: str


@dataclass(frozen=True)
class ApprovalRecord:
    approval_id: str
    proposal_id: str
    binding_hash: str
    canonical_hash: str
    approver: str
    reason: str
    granted_at: str
    expires_at: str
    revoked_at: Optional[str]
    reserved_at: Optional[str]
    reserved_execution_key: Optional[str]
    used_at: Optional[str]
    execution_key: Optional[str]

    @property
    def used(self) -> bool:
        return self.used_at is not None


@dataclass(frozen=True)
class ExecutionRecord:
    execution_key: str
    proposal_id: str
    status: ExecutionStatus
    target_key: str
    current_value: Any
    target_value: Any
    detail: Optional[str]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class ExecutionUsage:
    actions_in_last_24h: int
    cumulative_daily_change_percent: int
    monetary_exposure_rub: int
    latest_effective_write_at: Optional[datetime]


class DurableControlState:
    """SQLite-backed approval, kill-switch, and single-writer ledger."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.interrupts = DurableInterruptState(path)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        self._initialize()
        with suppress(OSError):
            os.chmod(self.path, 0o600)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=0.05)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 50")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS prepared_changes (
                    proposal_id TEXT PRIMARY KEY,
                    canonical_json TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'FIXTURE',
                    proposal_json TEXT,
                    snapshot_json TEXT
                );
                CREATE TABLE IF NOT EXISTS terminal_no_write_plans (
                    proposal_id TEXT PRIMARY KEY,
                    canonical_json TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL UNIQUE,
                    approver TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    granted_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    revoked_at TEXT,
                    reserved_at TEXT,
                    reserved_execution_key TEXT,
                    used_at TEXT,
                    execution_key TEXT,
                    FOREIGN KEY(proposal_id) REFERENCES prepared_changes(proposal_id)
                );
                CREATE TABLE IF NOT EXISTS campaign_approvals (
                    approval_id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    binding_hash TEXT NOT NULL,
                    approver TEXT NOT NULL,
                    authentication TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved_execution_key TEXT,
                    used_at TEXT,
                    authority_hash TEXT,
                    signature TEXT,
                    issued_at TEXT,
                    authority_json TEXT
                );
                CREATE TABLE IF NOT EXISTS kill_switches (
                    scope TEXT PRIMARY KEY,
                    active INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    principal TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS executions (
                    execution_key TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    target_key TEXT NOT NULL,
                    current_value_json TEXT NOT NULL,
                    target_value_json TEXT NOT NULL,
                    detail TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(proposal_id) REFERENCES prepared_changes(proposal_id)
                );
                CREATE TRIGGER IF NOT EXISTS approvals_immutable_fields
                BEFORE UPDATE OF
                    proposal_id,
                    binding_hash,
                    canonical_hash,
                    approver,
                    reason,
                    granted_at,
                    expires_at
                ON approvals
                BEGIN
                    SELECT RAISE(ABORT, 'immutable approval fields');
                END;
                CREATE TRIGGER IF NOT EXISTS prepared_changes_no_update
                BEFORE UPDATE ON prepared_changes
                BEGIN
                    SELECT RAISE(ABORT, 'immutable prepared change');
                END;
                CREATE TRIGGER IF NOT EXISTS terminal_no_write_plans_no_update
                BEFORE UPDATE ON terminal_no_write_plans
                BEGIN
                    SELECT RAISE(ABORT, 'immutable terminal plan');
                END;
                """
            )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(prepared_changes)"
                ).fetchall()
            }
            if "source" not in columns:
                connection.execute(
                    "ALTER TABLE prepared_changes "
                    "ADD COLUMN source TEXT NOT NULL DEFAULT 'FIXTURE'"
                )
            if "proposal_json" not in columns:
                connection.execute(
                    "ALTER TABLE prepared_changes ADD COLUMN proposal_json TEXT"
                )
            if "snapshot_json" not in columns:
                connection.execute(
                    "ALTER TABLE prepared_changes ADD COLUMN snapshot_json TEXT"
                )
            campaign_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(campaign_approvals)"
                ).fetchall()
            }
            for name in (
                "authority_hash",
                "signature",
                "issued_at",
                "authority_json",
            ):
                if name not in campaign_columns:
                    connection.execute(
                        "ALTER TABLE campaign_approvals ADD COLUMN "
                        + name
                        + " TEXT"
                    )
            connection.execute(
                "CREATE TRIGGER IF NOT EXISTS "
                "campaign_approvals_immutable_fields "
                "BEFORE UPDATE OF approval_id, proposal_id, binding_hash, "
                "approver, authentication, expires_at, authority_hash, "
                "signature, issued_at, authority_json ON campaign_approvals "
                "BEGIN SELECT RAISE(ABORT, "
                "'immutable campaign approval fields'); END"
            )

    def register_campaign_approval_authority(
        self,
        *,
        authority_service: Any,
        verified: Any,
    ) -> None:
        from mox_adv.lifecycle_authority import (
            LifecycleAuthorityService,
            VerifiedLifecycleAuthority,
        )

        if (
            type(authority_service) is not LifecycleAuthorityService
            or type(verified) is not VerifiedLifecycleAuthority
        ):
            raise ControlRejected(
                "AUTHORITY_NOT_AUTHENTICATED",
                "campaign approval requires a verified authority capability.",
            )
        approval = authority_service.verify(
            verified,
            "CAMPAIGN_APPROVAL",
        )
        proof = authority_service.proof(
            verified,
            "CAMPAIGN_APPROVAL",
        )
        approval_id = str(getattr(approval, "approval_id", ""))
        proposal_id = str(getattr(approval, "proposal_id", ""))
        binding_hash = str(getattr(approval, "binding_hash", ""))
        approver = str(getattr(approval, "approver", ""))
        authentication = str(getattr(approval, "authentication", ""))
        expires_at = getattr(approval, "expires_at", None)
        authority_hash = proof["canonical_hash"]
        signature = proof["signature"]
        issued_at = proof["issued_at"]
        authority_json = proof["canonical_json"]
        if not isinstance(expires_at, datetime):
            raise ControlRejected(
                "INVALID_INPUT",
                "campaign approval authority expiry is invalid.",
            )
        immutable = (
            proposal_id,
            binding_hash,
            approver,
            authentication,
            _utc_text(expires_at),
            authority_hash,
            signature,
            issued_at,
            authority_json,
        )
        if (
            not approval_id
            or not proposal_id
            or not binding_hash.startswith("sha256:")
            or not approver
            or not authentication
            or not authority_hash.startswith("sha256:")
            or not signature
            or not issued_at
            or not authority_json
        ):
            raise ControlRejected(
                "INVALID_INPUT",
                "campaign approval authority is invalid.",
            )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM campaign_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if existing is not None:
                if (
                    tuple(
                        existing[name]
                        for name in (
                            "proposal_id",
                            "binding_hash",
                            "approver",
                            "authentication",
                            "expires_at",
                            "authority_hash",
                            "signature",
                            "issued_at",
                            "authority_json",
                        )
                    )
                    != immutable
                ):
                    raise ControlRejected(
                        "IMMUTABLE_APPROVAL_CONFLICT",
                        "campaign approval binding changed.",
                    )
                return
            connection.execute(
                "INSERT INTO campaign_approvals "
                "(approval_id, proposal_id, binding_hash, approver, authentication, "
                "expires_at, authority_hash, signature, issued_at, authority_json, "
                "status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AVAILABLE')",
                (approval_id,) + immutable,
            )

    def register_prepared_change(self, prepared: PreparedChange) -> None:
        """Register a predetermined Case-04 plan usable only with the sealed fake."""

        self._store_prepared_change(
            prepared,
            source="FIXTURE",
            proposal_json=None,
            snapshot_json=None,
        )

    def register_optimization_proposal(
        self,
        *,
        proposal_store: Any,
        proposal_id: str,
        snapshot: Any,
        policy: Mapping[str, Any],
        writer: str,
        at: datetime,
        prepared_ad_variants: Optional[PreparedAdVariantCatalog] = None,
    ) -> PreparedChange | TerminalNoWritePlan:
        """Load one immutable proposal and derive its executable plan server-side."""

        from mox_adv.proposal_store import (
            ImmutableProposalStore,
            ProposalConflictError,
        )
        from mox_adv.recommend_contracts import (
            OptimizationProposalV1,
            SchemaValidationError,
            _canonical_hash,
        )
        from mox_adv.recommend_projection import (
            campaign_fingerprint,
            projection_from_integrated_snapshot,
        )

        if (
            type(proposal_store) is not ImmutableProposalStore
            or at.tzinfo is None
            or not writer
        ):
            raise ControlRejected(
                "INVALID_INPUT",
                "immutable proposal registration is invalid.",
            )
        try:
            projection = projection_from_integrated_snapshot(snapshot, policy, at)
            proposal = proposal_store.load_active(proposal_id, projection, at)
            expected_fingerprint = campaign_fingerprint(snapshot)
        except (ProposalConflictError, SchemaValidationError, ValueError) as error:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "trusted proposal or snapshot validation failed.",
            ) from error
        if (
            type(proposal) is not OptimizationProposalV1
            or proposal.snapshot_id != snapshot.snapshot_id
            or proposal.expected_fingerprint != expected_fingerprint
            or len(proposal.actions) != 1
        ):
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "proposal is not bound to the trusted snapshot.",
            )
        try:
            action_name = str(proposal.actions[0]["action"])
        except KeyError as error:
            raise ControlRejected(
                "UNSUPPORTED_ACTION",
                "proposal does not contain one executable action.",
            ) from error
        if action_name in {"KEEP", "REQUEST_HUMAN_HELP"}:
            reason_code = (
                None
                if action_name == "KEEP"
                else str(proposal.actions[0]["parameters"]["reason_code"])
            )
            terminal = TerminalNoWritePlan(
                proposal_id=proposal.proposal_id,
                proposal_hash=_canonical_hash(proposal.as_dict()),
                snapshot_id=snapshot.snapshot_id,
                policy_version=snapshot.policy_version,
                status=proposal.status,
                action=action_name,
                reason_code=reason_code,
            )
            self._store_terminal_no_write_plan(
                terminal,
                proposal_json=_canonical(proposal.as_dict()),
                snapshot_json=_canonical(snapshot.as_dict()),
            )
            return terminal
        try:
            action = OptimizationAction(action_name)
        except ValueError as error:
            raise ControlRejected(
                "UNSUPPORTED_ACTION",
                "proposal does not contain one executable action.",
            ) from error
        expected_diff = dict(proposal.expected_diff)
        if expected_diff.get("operation") != action.value:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "proposal expected diff does not match its action.",
            )
        current_value, target_value = self._derive_target(
            snapshot.campaign,
            action,
            expected_diff,
            prepared_ad_variants,
        )
        if action == OptimizationAction.SET_AD_VARIANT:
            assert isinstance(target_value, Mapping)
            assert prepared_ad_variants is not None
            expected_diff = {
                "operation": action.value,
                "variant_id": target_value["variant_id"],
                "title": target_value["title"],
                "text": target_value["text"],
                "source_plan_hash": prepared_ad_variants.source_plan_hash,
            }
        prepared = PreparedChange(
            proposal_id=proposal.proposal_id,
            proposal_hash=_canonical_hash(proposal.as_dict()),
            scope=TrustedScope(
                organization=snapshot.scope.organization,
                connection=snapshot.scope.connection,
                account=snapshot.scope.account,
                campaign=snapshot.scope.campaign,
                writer=writer,
            ),
            action=action,
            current_value=current_value,
            target_value=target_value,
            expected_diff=expected_diff,
            snapshot_id=snapshot.snapshot_id,
            snapshot_generated_at=snapshot.generated_at,
            direct_watermark=snapshot.provenance.direct_report.watermark,
            metrika_watermark=snapshot.provenance.metrika_report.watermark,
            policy_version=snapshot.policy_version,
            expected_fingerprint=expected_fingerprint,
            risk=(
                str(proposal.risks[0])
                if proposal.risks
                else "REVERSIBLE_CONTROLLED_CHANGE"
            ),
        )
        self._store_prepared_change(
            prepared,
            source="IMMUTABLE_PROPOSAL",
            proposal_json=_canonical(proposal.as_dict()),
            snapshot_json=_canonical(snapshot.as_dict()),
        )
        return prepared

    @staticmethod
    def _derive_target(
        campaign: Any,
        action: OptimizationAction,
        expected_diff: Mapping[str, Any],
        prepared_ad_variants: Optional[PreparedAdVariantCatalog] = None,
    ) -> tuple[Any, Any]:
        spec = ACTION_SPECS[action]
        if spec.family == ActionFamily.WEEKLY_BUDGET:
            current = campaign.current_weekly_budget_micros
        elif spec.family == ActionFamily.SEARCH_BID:
            current = campaign.current_search_bid_micros
        elif spec.family == ActionFamily.AD_VARIANT:
            current_variant = campaign.current_ad_variant
            if type(prepared_ad_variants) is not PreparedAdVariantCatalog:
                raise ControlRejected(
                    "PREPARED_AD_COPY_UNAVAILABLE",
                    "ad variant execution requires a trusted campaign plan.",
                )
            current = prepared_ad_variants.exact_copy(current_variant)
        else:
            current = campaign.state
        if spec.relative_percent is not None:
            if expected_diff.get("relative_step_percent") != abs(
                spec.relative_percent
            ):
                raise ControlRejected(
                    "IMMUTABLE_PROPOSAL_CONFLICT",
                    "proposal numeric step is outside the deterministic plan.",
                )
            target = calculate_relative_target(current, spec.relative_percent)
        elif spec.family == ActionFamily.AD_VARIANT:
            target_variant = expected_diff.get("variant_id")
            if target_variant == current["variant_id"]:
                raise ControlRejected(
                    "IMMUTABLE_PROPOSAL_CONFLICT",
                    "proposal ad variant does not change current state.",
                )
            target = prepared_ad_variants.exact_copy(str(target_variant))
        else:
            if current != spec.source_state:
                raise ControlRejected(
                    "UNSUPPORTED_STATE",
                    "proposal action is not applicable to snapshot state.",
                )
            target = spec.target_state
            if expected_diff.get("target_state") != target:
                raise ControlRejected(
                    "IMMUTABLE_PROPOSAL_CONFLICT",
                    "proposal target state is not deterministic.",
                )
        return current, target

    def _store_terminal_no_write_plan(
        self,
        plan: TerminalNoWritePlan,
        *,
        proposal_json: str,
        snapshot_json: str,
    ) -> None:
        canonical_json = _canonical(plan.as_dict())
        digest = canonical_hash(plan.as_dict())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT canonical_json, canonical_hash, proposal_json, snapshot_json "
                "FROM terminal_no_write_plans WHERE proposal_id = ?",
                (plan.proposal_id,),
            ).fetchone()
            values = (canonical_json, digest, proposal_json, snapshot_json)
            if existing is not None:
                if tuple(existing) != values:
                    raise ControlRejected(
                        "IMMUTABLE_PROPOSAL_CONFLICT",
                        "terminal proposal evidence changed.",
                    )
                return
            connection.execute(
                "INSERT INTO terminal_no_write_plans "
                "(proposal_id, canonical_json, canonical_hash, proposal_json, "
                "snapshot_json) VALUES (?, ?, ?, ?, ?)",
                (plan.proposal_id,) + values,
            )

    def load_terminal_no_write_plan(
        self,
        proposal_id: str,
    ) -> TerminalNoWritePlan:
        from mox_adv.recommend_contracts import _canonical_hash

        with self._connect() as connection:
            row = connection.execute(
                "SELECT canonical_json, canonical_hash, proposal_json, snapshot_json "
                "FROM terminal_no_write_plans WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected(
                "APPROVAL_NOT_FOUND",
                "terminal proposal is not prepared.",
            )
        try:
            value = json.loads(row["canonical_json"])
            proposal = json.loads(row["proposal_json"])
            snapshot = json.loads(row["snapshot_json"])
            plan = TerminalNoWritePlan(**value)
            action = proposal["actions"][0]
            matches = (
                canonical_hash(value) == row["canonical_hash"]
                and plan.proposal_hash == _canonical_hash(proposal)
                and proposal["proposal_id"] == plan.proposal_id
                and proposal["snapshot_id"] == plan.snapshot_id
                and snapshot["snapshot_id"] == plan.snapshot_id
                and snapshot["policy_version"] == plan.policy_version
                and action["action"] == plan.action
                and proposal["expected_diff"]["operation"] == "NO_CHANGE"
                and (
                    plan.action == "KEEP"
                    or (
                        plan.action == "REQUEST_HUMAN_HELP"
                        and action["parameters"]["reason_code"]
                        == plan.reason_code
                    )
                )
            )
        except (IndexError, KeyError, TypeError, ValueError) as error:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "terminal proposal evidence is invalid.",
            ) from error
        if not matches:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "terminal proposal no longer matches trusted evidence.",
            )
        return plan

    def load_execution_plan(
        self,
        proposal_id: str,
    ) -> PreparedChange | TerminalNoWritePlan:
        try:
            return self.load_prepared_change(proposal_id)
        except ControlRejected as error:
            if error.reason_code != "APPROVAL_NOT_FOUND":
                raise
        return self.load_terminal_no_write_plan(proposal_id)

    def _store_prepared_change(
        self,
        prepared: PreparedChange,
        *,
        source: str,
        proposal_json: Optional[str],
        snapshot_json: Optional[str],
    ) -> None:
        canonical_json = _canonical(prepared.as_dict())
        digest = canonical_hash(prepared.as_dict())
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT canonical_json, canonical_hash, source, "
                "proposal_json, snapshot_json "
                "FROM prepared_changes WHERE proposal_id = ?",
                (prepared.proposal_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["canonical_json"] != canonical_json
                    or existing["canonical_hash"] != digest
                    or existing["source"] != source
                    or existing["proposal_json"] != proposal_json
                    or existing["snapshot_json"] != snapshot_json
                ):
                    raise ControlRejected(
                        "IMMUTABLE_PROPOSAL_CONFLICT",
                        "proposal scope, diff, snapshot, or fingerprint changed.",
                    )
                return
            connection.execute(
                "INSERT INTO prepared_changes "
                "(proposal_id, canonical_json, canonical_hash, source, "
                "proposal_json, snapshot_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    prepared.proposal_id,
                    canonical_json,
                    digest,
                    source,
                    proposal_json,
                    snapshot_json,
                ),
            )

    def load_prepared_change(self, proposal_id: str) -> PreparedChange:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT canonical_json, canonical_hash, source, "
                "proposal_json, snapshot_json "
                "FROM prepared_changes WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "proposal is not prepared.")
        value = json.loads(row["canonical_json"])
        if canonical_hash(value) != row["canonical_hash"]:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "prepared proposal canonical hash is invalid.",
            )
        prepared = PreparedChange.from_dict(value)
        if row["source"] == "IMMUTABLE_PROPOSAL":
            self._verify_immutable_prepared(
                prepared,
                row["proposal_json"],
                row["snapshot_json"],
            )
        elif row["source"] != "FIXTURE":
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "prepared proposal source is invalid.",
            )
        return prepared

    @staticmethod
    def _verify_immutable_prepared(
        prepared: PreparedChange,
        proposal_json: Optional[str],
        snapshot_json: Optional[str],
    ) -> None:
        from mox_adv.recommend_contracts import _canonical_hash
        from mox_adv.recommend_projection import campaign_fingerprint_mapping

        try:
            proposal = json.loads(str(proposal_json))
            snapshot = json.loads(str(snapshot_json))
            scope = snapshot["scope"]
            provenance = snapshot["provenance"]
            campaign = snapshot["campaign"]
            actions = proposal["actions"]
            spec = ACTION_SPECS[prepared.action]
            if spec.family == ActionFamily.WEEKLY_BUDGET:
                snapshot_current = campaign["current_weekly_budget_micros"]
            elif spec.family == ActionFamily.SEARCH_BID:
                snapshot_current = campaign["current_search_bid_micros"]
            elif spec.family == ActionFamily.AD_VARIANT:
                snapshot_current = prepared.current_value["variant_id"]
            else:
                snapshot_current = campaign["state"]
            proposal_diff = dict(proposal.get("expected_diff", {}))
            prepared_diff = dict(prepared.expected_diff)
            diff_matches = (
                proposal_diff == prepared_diff
                if spec.family != ActionFamily.AD_VARIANT
                else (
                    proposal_diff
                    == {
                        "operation": prepared.action.value,
                        "variant_id": prepared.target_value["variant_id"],
                    }
                    and prepared_diff
                    == {
                        "operation": prepared.action.value,
                        "variant_id": prepared.target_value["variant_id"],
                        "title": prepared.target_value["title"],
                        "text": prepared.target_value["text"],
                        "source_plan_hash": prepared_diff.get(
                            "source_plan_hash"
                        ),
                    }
                    and str(prepared_diff["source_plan_hash"]).startswith(
                        "sha256:"
                    )
                )
            )
            matches = (
                _canonical_hash(proposal) == prepared.proposal_hash
                and proposal.get("proposal_id") == prepared.proposal_id
                and proposal.get("snapshot_id") == prepared.snapshot_id
                and len(actions) == 1
                and actions[0].get("action") == prepared.action.value
                and diff_matches
                and snapshot.get("snapshot_id") == prepared.snapshot_id
                and snapshot.get("generated_at")
                == prepared.snapshot_generated_at
                and snapshot.get("policy_version") == prepared.policy_version
                and (
                    campaign["current_ad_variant"] == snapshot_current
                    if spec.family == ActionFamily.AD_VARIANT
                    else snapshot_current == prepared.current_value
                )
                and provenance["direct_report"]["watermark"]
                == prepared.direct_watermark
                and provenance["metrika_report"]["watermark"]
                == prepared.metrika_watermark
                and campaign_fingerprint_mapping(snapshot)
                == prepared.expected_fingerprint
                and proposal.get("expected_fingerprint")
                == prepared.expected_fingerprint
                and {
                    "organization": prepared.scope.organization,
                    "connection": prepared.scope.connection,
                    "account": prepared.scope.account,
                    "campaign": prepared.scope.campaign,
                }
                == {
                    "organization": scope["organization"],
                    "connection": scope["connection"],
                    "account": scope["account"],
                    "campaign": scope["campaign"],
                }
            )
        except (
            AttributeError,
            TypeError,
            KeyError,
            ValueError,
            json.JSONDecodeError,
        ) as error:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "trusted prepared evidence cannot be decoded.",
            ) from error
        if not matches:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "prepared proposal no longer matches trusted evidence.",
            )

    def prepared_source(self, proposal_id: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT source FROM prepared_changes WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "proposal is not prepared.")
        return str(row["source"])

    def trusted_snapshot_facts(
        self,
        proposal_id: str,
        now: datetime,
    ) -> Mapping[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT source, snapshot_json FROM prepared_changes "
                "WHERE proposal_id = ?",
                (proposal_id,),
            ).fetchone()
        if row is None or row["source"] != "IMMUTABLE_PROPOSAL":
            raise ControlRejected(
                "TRUSTED_SNAPSHOT_REQUIRED",
                "execution facts require a trusted immutable snapshot.",
            )
        try:
            snapshot = json.loads(row["snapshot_json"])
            provenance = snapshot["provenance"]
            metrics = snapshot["metrics"]
            campaign = snapshot["campaign"]
        except (TypeError, KeyError, json.JSONDecodeError) as error:
            raise ControlRejected(
                "IMMUTABLE_PROPOSAL_CONFLICT",
                "trusted snapshot facts cannot be decoded.",
            ) from error
        if now.tzinfo is None:
            raise ControlRejected(
                "INVALID_INPUT",
                "execution evaluation time must be timezone-aware.",
            )
        evaluated = now.astimezone(timezone.utc)

        def parse(value: str) -> datetime:
            return _parse_utc(value)

        generated_at = parse(snapshot["generated_at"])
        direct_times = (
            parse(provenance["direct_report"]["retrieved_at"]),
            parse(provenance["direct_state"]["retrieved_at"]),
        )
        metrika_time = parse(provenance["metrika_report"]["retrieved_at"])
        watermarks = (
            parse(provenance["direct_report"]["watermark"]),
            parse(provenance["direct_state"]["watermark"]),
            parse(provenance["metrika_report"]["watermark"]),
        )
        if evaluated < generated_at or any(
            value > evaluated
            for value in (*direct_times, metrika_time, *watermarks)
        ):
            raise ControlRejected(
                "TRUSTED_SNAPSHOT_TIME_INVALID",
                "trusted snapshot evidence is later than evaluation time.",
            )

        def age_minutes(value: datetime) -> int:
            return max(0, int((evaluated - value).total_seconds() // 60))

        return {
            "comparability_status": snapshot["comparability_status"],
            "confidence_status": snapshot["confidence_status"],
            "financial_recommendations_allowed": bool(
                snapshot["financial_recommendations_allowed"]
            ),
            "direct_age_minutes": max(age_minutes(value) for value in direct_times),
            "metrika_age_minutes": age_minutes(metrika_time),
            "watermark_skew_minutes": int(
                (max(watermarks) - min(watermarks)).total_seconds() // 60
            ),
            "clicks": int(metrics["clicks"]),
            "conversions": int(metrics["goal_visits"]),
            "impressions": int(metrics["impressions"]),
            "spend_rub": int(metrics["cost_micros"]) // 1_000_000,
            "cpa_rub": str(metrics["cpa_rub"]),
            "budget_utilization_percent": str(
                metrics["budget_utilization_percent"]
            ),
            "ctr_percent": str(metrics["ctr_percent"]),
            "campaign_state": str(campaign["state"]),
            "campaign_strategy": str(campaign["strategy"]),
        }

    def execution_usage(
        self,
        scope: TrustedScope,
        now: datetime,
        *,
        exclude_execution_key: Optional[str] = None,
    ) -> ExecutionUsage:
        cutoff = now.astimezone(timezone.utc) - timedelta(hours=24)
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT e.execution_key, e.status, e.updated_at, p.canonical_json "
                "FROM executions e JOIN prepared_changes p "
                "ON p.proposal_id = e.proposal_id "
                "WHERE e.status IN ('IN_FLIGHT', 'APPLIED', 'NO_CHANGE', "
                "'UNKNOWN_RESULT')"
            ).fetchall()
        action_count = 0
        cumulative = 0
        monetary = 0
        latest: Optional[datetime] = None
        for row in rows:
            if row["execution_key"] == exclude_execution_key:
                continue
            prepared = PreparedChange.from_dict(json.loads(row["canonical_json"]))
            if prepared.scope != scope:
                continue
            occurred = _parse_utc(row["updated_at"])
            if occurred < cutoff:
                continue
            action_count += 1
            relative = prepared.expected_diff.get("relative_step_percent", 0)
            if isinstance(relative, int) and not isinstance(relative, bool):
                cumulative += abs(relative)
            if (
                isinstance(prepared.current_value, int)
                and not isinstance(prepared.current_value, bool)
                and isinstance(prepared.target_value, int)
                and not isinstance(prepared.target_value, bool)
            ):
                monetary += abs(
                    prepared.target_value - prepared.current_value
                ) // 1_000_000
            if latest is None or occurred > latest:
                latest = occurred
        return ExecutionUsage(action_count, cumulative, monetary, latest)

    def grant_approval(
        self,
        proposal_id: str,
        expires_at: datetime,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> ApprovalRecord:
        if (
            principal.identity != "sviridov"
            or principal.authentication != "authenticated_macos_user"
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the Gate 0 approver may grant approval.",
            )
        if not reason.strip():
            raise ControlRejected("INVALID_INPUT", "approval reason is required.")
        if expires_at <= now:
            raise ControlRejected("APPROVAL_EXPIRED", "approval expiry must be future.")
        prepared = self.load_prepared_change(proposal_id)
        granted_at_text = _utc_text(now)
        expires_at_text = _utc_text(expires_at)
        immutable = {
            "schema_version": "approval-v1",
            "proposal_id": proposal_id,
            "binding_hash": prepared.binding_hash(),
            "approver": principal.identity,
            "authentication": principal.authentication,
            "reason": reason,
            "granted_at": granted_at_text,
            "expires_at": expires_at_text,
        }
        digest = canonical_hash(immutable)
        approval_id = "approval-" + digest.removeprefix("sha256:")[:24]
        with self._connect() as connection, suppress(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO approvals "
                "(approval_id, proposal_id, binding_hash, canonical_hash, "
                "approver, reason, granted_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval_id,
                    proposal_id,
                    prepared.binding_hash(),
                    digest,
                    principal.identity,
                    reason,
                    granted_at_text,
                    expires_at_text,
                ),
            )
        return self.load_approval(approval_id)

    def load_approval(self, approval_id: str) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "approval does not exist.")
        return self._approval_from_row(row)

    def load_active_approval(
        self,
        proposal_id: str,
        binding_hash: str,
        now: datetime,
    ) -> ApprovalRecord:
        approval = self.load_bound_approval(proposal_id, binding_hash)
        if approval.revoked_at is not None:
            raise ControlRejected("APPROVAL_REVOKED", "approval was revoked.")
        if approval.used:
            raise ControlRejected("APPROVAL_ALREADY_USED", "approval is single-use.")
        if _parse_utc(approval.expires_at) <= now.astimezone(timezone.utc):
            raise ControlRejected("APPROVAL_EXPIRED", "approval has expired.")
        return approval

    def load_bound_approval(
        self,
        proposal_id: str,
        binding_hash: str,
    ) -> ApprovalRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE proposal_id = ? "
                "ORDER BY granted_at DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        if row is None:
            raise ControlRejected("APPROVAL_NOT_FOUND", "approval does not exist.")
        approval = self._approval_from_row(row)
        if approval.binding_hash != binding_hash:
            raise ControlRejected(
                "APPROVAL_SCOPE_MISMATCH",
                "approval does not bind the current exact proposal.",
            )
        return approval

    def revoke_approval(
        self,
        approval_id: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT approver, used_at, revoked_at FROM approvals "
                "WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None or row["approver"] != principal.identity:
                raise ControlRejected(
                    "APPROVAL_NOT_FOUND",
                    "approval is not revocable.",
                )
            if row["used_at"] is not None:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "used approval cannot be revoked.",
                )
            if row["revoked_at"] is None:
                connection.execute(
                    "UPDATE approvals SET revoked_at = ? WHERE approval_id = ?",
                    (_utc_text(now), approval_id),
                )

    def reserve_execution(
        self,
        prepared: PreparedChange,
        now: datetime,
    ) -> Tuple[ExecutionStatus, ExecutionRecord]:
        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT execution_key FROM executions "
                "WHERE status = 'UNKNOWN_RESULT' LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                connection.rollback()
                raise ControlRejected(
                    "UNKNOWN_RESULT",
                    "an unresolved execution blocks the next write.",
                )
            existing = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if existing is not None:
                record = self._execution_from_row(existing)
                connection.rollback()
                outcome = (
                    ExecutionStatus.ALREADY_PROCESSED
                    if record.status in {"APPLIED", "NO_CHANGE"}
                    else record.status
                )
                return outcome, record
            other = connection.execute(
                "SELECT * FROM executions "
                "WHERE status IN ('RESERVED', 'IN_FLIGHT') LIMIT 1"
            ).fetchone()
            if other is not None:
                record = self._execution_from_row(other)
                connection.rollback()
                return ExecutionStatus.BLOCKED, record
            connection.execute(
                "INSERT INTO executions "
                "(execution_key, proposal_id, status, target_key, "
                "current_value_json, target_value_json, created_at, updated_at) "
                "VALUES (?, ?, 'RESERVED', ?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    prepared.proposal_id,
                    prepared.target_key(),
                    json.dumps(prepared.current_value),
                    json.dumps(prepared.target_value),
                    now_text,
                    now_text,
                ),
            )
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return ExecutionStatus.RESERVED, self._execution_from_row(row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def begin_execution(
        self,
        prepared: PreparedChange,
        approval: ApprovalRecord,
        now: datetime,
    ) -> ExecutionRecord:
        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            current = self._approval_from_row(row) if row is not None else None
            if (
                current is None
                or current.used
                or current.revoked_at is not None
                or current.reserved_at is not None
                or current.binding_hash != prepared.binding_hash()
                or _parse_utc(current.expires_at) <= now.astimezone(timezone.utc)
            ):
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval changed, expired, or was already consumed.",
                )
            updated = connection.execute(
                "UPDATE approvals SET reserved_at = ?, reserved_execution_key = ? "
                "WHERE approval_id = ? AND reserved_at IS NULL "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (now_text, prepared.execution_key(), approval.approval_id),
            )
            if updated.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "approval was consumed concurrently.",
                )
            changed = connection.execute(
                "UPDATE executions SET status = 'IN_FLIGHT', updated_at = ? "
                "WHERE execution_key = ? AND status = 'RESERVED'",
                (now_text, prepared.execution_key()),
            )
            if changed.rowcount != 1:
                raise ControlRejected(
                    "EXECUTION_CONFLICT",
                    "execution reservation is no longer available.",
                )
            execution_row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            return self._execution_from_row(execution_row)
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def send_once(
        self,
        prepared: PreparedChange,
        approval: ApprovalRecord,
        now: datetime,
        sender: Callable[[], None],
        at_dispatch_boundary: Optional[Callable[[], datetime]] = None,
        immediate_pre_transport: Optional[Callable[[], datetime]] = None,
    ) -> Tuple[ExecutionStatus, ExecutionRecord]:
        """Commit authority and IN_FLIGHT before the immediate dispatch boundary."""

        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unresolved = connection.execute(
                "SELECT execution_key FROM executions "
                "WHERE status = 'UNKNOWN_RESULT' LIMIT 1"
            ).fetchone()
            if unresolved is not None:
                raise ControlRejected(
                    "UNKNOWN_RESULT",
                    "an unresolved execution blocks the next write.",
                )
            existing = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            if existing is not None:
                record = self._execution_from_row(existing)
                connection.rollback()
                outcome = (
                    ExecutionStatus.ALREADY_PROCESSED
                    if record.status
                    in {
                        ExecutionStatus.RESERVED,
                        ExecutionStatus.IN_FLIGHT,
                        ExecutionStatus.APPLIED,
                        ExecutionStatus.NO_CHANGE,
                    }
                    else record.status
                )
                return outcome, record
            other = connection.execute(
                "SELECT * FROM executions "
                "WHERE status IN ('RESERVED', 'IN_FLIGHT') LIMIT 1"
            ).fetchone()
            if other is not None:
                record = self._execution_from_row(other)
                connection.rollback()
                return ExecutionStatus.BLOCKED, record
            if self._kill_switch_active_in_connection(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            self._require_no_interrupt(prepared.scope)
            approval_row = connection.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval.approval_id,),
            ).fetchone()
            current = (
                self._approval_from_row(approval_row)
                if approval_row is not None
                else None
            )
            if (
                current is None
                or current.used
                or current.revoked_at is not None
                or current.reserved_at is not None
                or current.binding_hash != prepared.binding_hash()
                or _parse_utc(current.expires_at) <= now.astimezone(timezone.utc)
            ):
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval changed, expired, or was already consumed.",
                )
            connection.execute(
                "INSERT INTO executions "
                "(execution_key, proposal_id, status, target_key, "
                "current_value_json, target_value_json, created_at, updated_at) "
                "VALUES (?, ?, 'RESERVED', ?, ?, ?, ?, ?)",
                (
                    prepared.execution_key(),
                    prepared.proposal_id,
                    prepared.target_key(),
                    json.dumps(prepared.current_value),
                    json.dumps(prepared.target_value),
                    now_text,
                    now_text,
                ),
            )
            reserved = connection.execute(
                "UPDATE approvals SET reserved_at = ?, reserved_execution_key = ? "
                "WHERE approval_id = ? AND reserved_at IS NULL "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (now_text, prepared.execution_key(), approval.approval_id),
            )
            if reserved.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_ALREADY_USED",
                    "approval was reserved concurrently.",
                )
            moved = connection.execute(
                "UPDATE executions SET status = 'IN_FLIGHT', updated_at = ? "
                "WHERE execution_key = ? AND status = 'RESERVED'",
                (now_text, prepared.execution_key()),
            )
            if moved.rowcount != 1:
                raise ControlRejected(
                    "EXECUTION_CONFLICT",
                    "execution reservation is no longer available.",
                )
            if self._kill_switch_active_in_connection(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            self._require_no_interrupt(prepared.scope)
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (prepared.execution_key(),),
            ).fetchone()
            connection.commit()
            record = self._execution_from_row(row)
        except ControlRejected:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable authority state is unavailable.",
            ) from error
        finally:
            connection.close()

        try:
            self._require_no_interrupt(prepared.scope)
            with self._connect() as dispatch_connection:
                if self._kill_switch_active_in_connection(
                    dispatch_connection,
                    prepared.scope,
                ):
                    raise ControlRejected(
                        "KILL_SWITCH_ACTIVE",
                        "durable kill switch blocks the unsent command.",
                    )
            dispatch_at = (
                now
                if at_dispatch_boundary is None
                else at_dispatch_boundary()
            )
            immediate_at = (
                dispatch_at
                if immediate_pre_transport is None
                else immediate_pre_transport()
            )
            self._consume_reserved_approval_for_dispatch(
                prepared,
                approval.approval_id,
                immediate_at,
            )
        except ControlRejected as error:
            self.release_approval_reservation(
                approval.approval_id,
                prepared.execution_key(),
            )
            self.finish_execution(
                prepared.execution_key(),
                ExecutionStatus.BLOCKED,
                error.reason_code,
                now,
            )
            raise
        sender()
        return ExecutionStatus.IN_FLIGHT, record

    def _consume_reserved_approval_for_dispatch(
        self,
        prepared: PreparedChange,
        approval_id: str,
        now: datetime,
    ) -> None:
        self._require_no_interrupt(prepared.scope)
        now_text = _utc_text(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self._kill_switch_active_in_connection(connection, prepared.scope):
                raise ControlRejected(
                    "KILL_SWITCH_ACTIVE",
                    "durable kill switch blocks the unsent command.",
                )
            row = connection.execute(
                "SELECT reserved_execution_key, used_at, revoked_at, expires_at "
                "FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if (
                row is None
                or row["reserved_execution_key"] != prepared.execution_key()
                or row["used_at"] is not None
                or row["revoked_at"] is not None
                or _parse_utc(row["expires_at"]) <= now.astimezone(timezone.utc)
            ):
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval reservation cannot be consumed.",
                )
            consumed = connection.execute(
                "UPDATE approvals SET used_at = ?, execution_key = ? "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL AND revoked_at IS NULL",
                (
                    now_text,
                    prepared.execution_key(),
                    approval_id,
                    prepared.execution_key(),
                ),
            )
            if consumed.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval reservation cannot be consumed.",
                )
            connection.commit()
        except ControlRejected:
            if connection.in_transaction:
                connection.rollback()
            raise
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise ControlRejected(
                "CONTROL_STATE_UNAVAILABLE",
                "durable authority state is unavailable.",
            ) from error
        finally:
            connection.close()

    def mark_approval_used(
        self,
        approval_id: str,
        execution_key: str,
        now: datetime,
    ) -> None:
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE approvals SET used_at = ?, execution_key = ? "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL",
                (_utc_text(now), execution_key, approval_id, execution_key),
            )
            if changed.rowcount != 1:
                raise ControlRejected(
                    "APPROVAL_NOT_APPLICABLE",
                    "approval reservation cannot be consumed.",
                )

    def release_approval_reservation(
        self,
        approval_id: str,
        execution_key: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE approvals SET reserved_at = NULL, "
                "reserved_execution_key = NULL "
                "WHERE approval_id = ? AND reserved_execution_key = ? "
                "AND used_at IS NULL",
                (approval_id, execution_key),
            )

    def finish_execution(
        self,
        execution_key: str,
        status: ExecutionStatus,
        detail: Optional[str],
        now: datetime,
    ) -> ExecutionRecord:
        try:
            terminal_status = ExecutionStatus(status)
        except ValueError as error:
            raise ControlRejected(
                "INVALID_INPUT",
                "execution status is invalid.",
            ) from error
        if terminal_status not in {
            ExecutionStatus.APPLIED,
            ExecutionStatus.NO_CHANGE,
            ExecutionStatus.BLOCKED,
            ExecutionStatus.UNKNOWN_RESULT,
            ExecutionStatus.FAILED,
        }:
            raise ControlRejected("INVALID_INPUT", "execution status is not terminal.")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE executions SET status = ?, detail = ?, updated_at = ? "
                "WHERE execution_key = ? "
                "AND status IN ('RESERVED', 'IN_FLIGHT')",
                (
                    terminal_status.value,
                    detail,
                    _utc_text(now),
                    execution_key,
                ),
            )
            if changed.rowcount != 1:
                existing = connection.execute(
                    "SELECT status FROM executions WHERE execution_key = ?",
                    (execution_key,),
                ).fetchone()
                if existing is None or existing["status"] != terminal_status.value:
                    raise ControlRejected(
                        "ILLEGAL_EXECUTION_TRANSITION",
                        "terminal execution state is immutable.",
                    )
        return self.load_execution(execution_key)

    def load_execution(self, execution_key: str) -> ExecutionRecord:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM executions WHERE execution_key = ?",
                (execution_key,),
            ).fetchone()
        if row is None:
            raise ControlRejected("EXECUTION_NOT_FOUND", "execution does not exist.")
        return self._execution_from_row(row)

    def engage_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        self._validate_incident_control(scope, reason, principal)
        try:
            self.interrupts.engage("kill_switch", scope, reason, now)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO kill_switches "
                "(scope, active, reason, principal, updated_at) "
                "VALUES (?, 1, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET active = 1, "
                "reason = excluded.reason, "
                "principal = excluded.principal, updated_at = excluded.updated_at",
                (scope, reason, principal.identity, _utc_text(now)),
            )

    def release_kill_switch(
        self,
        scope: str,
        reason: str,
        principal: ElevatedAuthenticatedPrincipal,
        now: datetime,
    ) -> None:
        if (
            type(principal) is not ElevatedAuthenticatedPrincipal
            or not principal.is_verified()
        ):
            raise ControlRejected(
                "ELEVATED_REAUTHENTICATION_REQUIRED",
                "kill-switch release requires verified elevated confirmation.",
            )
        self._validate_incident_control(scope, reason, principal)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO kill_switches "
                "(scope, active, reason, principal, updated_at) "
                "VALUES (?, 0, ?, ?, ?) "
                "ON CONFLICT(scope) DO UPDATE SET active = 0, "
                "reason = excluded.reason, "
                "principal = excluded.principal, updated_at = excluded.updated_at",
                (scope, reason, principal.identity, _utc_text(now)),
            )
        try:
            self.interrupts.release("kill_switch", scope, reason, now)
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state remains engaged.",
            ) from error

    def kill_switch_active(self, scope: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT active FROM kill_switches WHERE scope = ?",
                (scope,),
            ).fetchone()
        return row is not None and bool(row["active"])

    def any_kill_switch_active(self, scope: TrustedScope) -> bool:
        try:
            self._require_no_interrupt(scope)
            with self._connect() as connection:
                return self._kill_switch_active_in_connection(connection, scope)
        except sqlite3.Error as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable kill-switch state is unavailable.",
            ) from error

    def require_dispatch_allowed(self, scope: TrustedScope) -> None:
        """Fail closed on every durable interrupt immediately before transport."""

        if self.any_kill_switch_active(scope):
            raise ControlRejected(
                "KILL_SWITCH_ACTIVE",
                "durable kill switch blocks the unsent command.",
            )

    def _require_no_interrupt(self, scope: TrustedScope) -> None:
        try:
            active = self.interrupts.any_active(
                "kill_switch",
                kill_switch_scopes(
                    scope.organization,
                    scope.connection,
                    scope.campaign,
                ),
            )
        except InterruptStateUnavailable as error:
            raise ControlRejected(
                "KILL_SWITCH_UNAVAILABLE",
                "durable interrupt state is unavailable.",
            ) from error
        if active:
            raise ControlRejected(
                "KILL_SWITCH_ACTIVE",
                "durable kill switch blocks the unsent command.",
            )

    @staticmethod
    def _kill_switch_active_in_connection(
        connection: sqlite3.Connection,
        scope: TrustedScope,
    ) -> bool:
        scopes = (
            "global",
            "organization:" + scope.organization,
            "connection:" + scope.connection,
            "campaign:" + scope.campaign,
        )
        placeholders = ",".join("?" for _ in scopes)
        row = connection.execute(
            "SELECT 1 FROM kill_switches "
            f"WHERE active = 1 AND scope IN ({placeholders}) LIMIT 1",
            scopes,
        ).fetchone()
        return row is not None

    @staticmethod
    def _validate_incident_control(
        scope: str,
        reason: str,
        principal: AuthenticatedPrincipal,
    ) -> None:
        valid_scope = scope == "global" or scope.startswith(
            ("organization:", "connection:", "campaign:")
        )
        if not valid_scope or not reason.strip():
            raise ControlRejected(
                "INVALID_INPUT",
                "kill-switch scope or reason invalid.",
            )
        if (
            principal.identity != "sviridov"
            or principal.authentication != "authenticated_macos_user"
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the incident principal may control the kill switch.",
            )

    @staticmethod
    def _approval_from_row(row: sqlite3.Row) -> ApprovalRecord:
        record = ApprovalRecord(
            approval_id=row["approval_id"],
            proposal_id=row["proposal_id"],
            binding_hash=row["binding_hash"],
            canonical_hash=row["canonical_hash"],
            approver=row["approver"],
            reason=row["reason"],
            granted_at=row["granted_at"],
            expires_at=row["expires_at"],
            revoked_at=row["revoked_at"],
            reserved_at=row["reserved_at"],
            reserved_execution_key=row["reserved_execution_key"],
            used_at=row["used_at"],
            execution_key=row["execution_key"],
        )
        immutable = {
            "schema_version": "approval-v1",
            "proposal_id": record.proposal_id,
            "binding_hash": record.binding_hash,
            "approver": record.approver,
            "authentication": "authenticated_macos_user",
            "reason": record.reason,
            "granted_at": record.granted_at,
            "expires_at": record.expires_at,
        }
        if canonical_hash(immutable) != record.canonical_hash:
            raise ControlRejected(
                "APPROVAL_INTEGRITY_FAILURE",
                "approval canonical hash is invalid.",
            )
        return record

    @staticmethod
    def _execution_from_row(row: sqlite3.Row) -> ExecutionRecord:
        return ExecutionRecord(
            execution_key=row["execution_key"],
            proposal_id=row["proposal_id"],
            status=ExecutionStatus(row["status"]),
            target_key=row["target_key"],
            current_value=json.loads(row["current_value_json"]),
            target_value=json.loads(row["target_value_json"]),
            detail=row["detail"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
