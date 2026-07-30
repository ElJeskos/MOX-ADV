"""Authenticated issuance for campaign and goal lifecycle authorities."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Protocol

from mox_adv.control_state import AuthenticatedPrincipal, ControlRejected
from mox_adv.mandate_signing import MandateSigner


class PrincipalAuthenticator(Protocol):
    def authenticate(self) -> AuthenticatedPrincipal: ...


_AUTHORITY_SEAL = object()


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(nested)
            for key, nested in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "authority timestamps must be timezone-aware.",
            )
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ControlRejected(
        "AUTHORITY_INVALID",
        "authority contains a non-canonical value.",
    )


def _canonical(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True)
class VerifiedLifecycleAuthority:
    authority_type: str
    authority: Any
    canonical_hash: str
    signature: str
    issued_at: str
    issuer: str
    authentication: str
    _seal: object = field(repr=False, compare=False)


class LifecycleAuthorityService:
    """Authenticate the configured human before sealing an authority record."""

    def __init__(
        self,
        policy: Mapping[str, Any],
        authenticator: PrincipalAuthenticator,
        signer: MandateSigner,
    ) -> None:
        self.policy = policy
        self.authenticator = authenticator
        self.signer = signer

    def issue_goal(
        self,
        authority: Any,
        now: datetime,
    ) -> VerifiedLifecycleAuthority:
        from mox_adv.goal_contracts import GoalAuthority

        if type(authority) is not GoalAuthority:
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "goal authority type is invalid.",
            )
        kind = getattr(authority, "kind", None)
        kind_value = getattr(kind, "value", kind)
        role = "approver" if kind_value == "APPROVAL" else "mandate_issuer"
        return self._issue("GOAL_AUTHORITY", authority, role, now)

    def issue_campaign(
        self,
        authority: Any,
        now: datetime,
    ) -> VerifiedLifecycleAuthority:
        from mox_adv.campaign_lifecycle import CampaignApproval

        if type(authority) is not CampaignApproval:
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "campaign approval type is invalid.",
            )
        return self._issue("CAMPAIGN_APPROVAL", authority, "approver", now)

    def verify(
        self,
        verified: VerifiedLifecycleAuthority,
        authority_type: str,
    ) -> Any:
        if (
            type(verified) is not VerifiedLifecycleAuthority
            or verified._seal is not _AUTHORITY_SEAL
            or verified.authority_type != authority_type
        ):
            raise ControlRejected(
                "AUTHORITY_NOT_AUTHENTICATED",
                "authority was not issued by the authenticated authority service.",
            )
        document = self._document(
            verified.authority_type,
            verified.authority,
            verified.issued_at,
            verified.issuer,
            verified.authentication,
        )
        canonical = _canonical(document)
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if digest != verified.canonical_hash or not self.signer.verify(
            canonical,
            verified.signature,
        ):
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "authority canonical hash or issuer signature is invalid.",
            )
        return verified.authority

    def proof(
        self,
        verified: VerifiedLifecycleAuthority,
        authority_type: str,
    ) -> Mapping[str, str]:
        self.verify(verified, authority_type)
        document = self._document(
            verified.authority_type,
            verified.authority,
            verified.issued_at,
            verified.issuer,
            verified.authentication,
        )
        return {
            "canonical_hash": verified.canonical_hash,
            "signature": verified.signature,
            "issued_at": verified.issued_at,
            "issuer": verified.issuer,
            "authentication": verified.authentication,
            "canonical_json": _canonical(document).decode("utf-8"),
        }

    def verify_persisted_proof(
        self,
        *,
        authority_type: str,
        canonical_json: str,
        canonical_hash: str,
        signature: str,
    ) -> Mapping[str, Any]:
        try:
            document = json.loads(canonical_json)
        except (TypeError, json.JSONDecodeError) as error:
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof is not canonical JSON.",
            ) from error
        if (
            not isinstance(document, Mapping)
            or set(document)
            != {
                "schema_version",
                "authority_type",
                "policy_id",
                "issued_at",
                "issuer",
                "authority",
            }
            or document["schema_version"] != "lifecycle-authority-v1"
            or document["authority_type"] != authority_type
            or document["policy_id"] != self.policy["policy_id"]
            or not isinstance(document["authority"], Mapping)
            or not isinstance(document["issuer"], Mapping)
            or set(document["issuer"]) != {"identity", "authentication"}
        ):
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof does not match its trust domain.",
            )
        authority = document["authority"]
        kind = authority.get("kind")
        if authority_type == "CAMPAIGN_APPROVAL":
            role = "approver"
            authority_identity = authority.get("approver")
        elif authority_type == "GOAL_AUTHORITY" and kind in {
            "APPROVAL",
            "MANDATE",
        }:
            role = "approver" if kind == "APPROVAL" else "mandate_issuer"
            authority_identity = authority.get("principal")
        else:
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof has an invalid authority kind.",
            )
        expected = self.policy["principals"][role]
        issuer = document["issuer"]
        if (
            issuer["identity"] != expected["identity"]
            or issuer["authentication"] != expected["authentication"]
            or authority_identity != issuer["identity"]
            or authority.get("authentication") != issuer["authentication"]
        ):
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof has an invalid authenticated issuer.",
            )
        canonical = _canonical(document)
        if canonical.decode("utf-8") != canonical_json:
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof bytes are not canonical.",
            )
        digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
        if digest != canonical_hash or not self.signer.verify(
            canonical,
            signature,
        ):
            raise ControlRejected(
                "AUTHORITY_INTEGRITY_FAILURE",
                "persisted authority proof signature is invalid.",
            )
        return authority

    def _issue(
        self,
        authority_type: str,
        authority: Any,
        role: str,
        now: datetime,
    ) -> VerifiedLifecycleAuthority:
        if now.tzinfo is None:
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "authority issuance time must be timezone-aware.",
            )
        expected = self.policy["principals"][role]
        principal = self.authenticator.authenticate()
        if (
            principal.identity != expected["identity"]
            or principal.authentication != expected["authentication"]
            or getattr(authority, "principal", getattr(authority, "approver", None))
            != principal.identity
            or getattr(authority, "authentication", None)
            != principal.authentication
        ):
            raise ControlRejected(
                "UNAUTHENTICATED_PRINCIPAL",
                "only the configured human principal may issue this authority.",
            )
        expires_at = getattr(authority, "expires_at", None)
        if (
            not isinstance(expires_at, datetime)
            or expires_at.tzinfo is None
            or expires_at.astimezone(timezone.utc) <= now.astimezone(timezone.utc)
        ):
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "authority expiry must be current and timezone-aware.",
            )
        policy_id = getattr(authority, "policy_id", self.policy["policy_id"])
        if policy_id != self.policy["policy_id"]:
            raise ControlRejected(
                "AUTHORITY_INVALID",
                "authority policy version does not match Gate 0.",
            )
        issued_at = now.astimezone(timezone.utc).isoformat()
        document = self._document(
            authority_type,
            authority,
            issued_at,
            principal.identity,
            principal.authentication,
        )
        canonical = _canonical(document)
        return VerifiedLifecycleAuthority(
            authority_type=authority_type,
            authority=authority,
            canonical_hash="sha256:" + hashlib.sha256(canonical).hexdigest(),
            signature=self.signer.sign(canonical),
            issued_at=issued_at,
            issuer=principal.identity,
            authentication=principal.authentication,
            _seal=_AUTHORITY_SEAL,
        )

    def _document(
        self,
        authority_type: str,
        authority: Any,
        issued_at: str,
        issuer: str,
        authentication: str,
    ) -> Mapping[str, Any]:
        return {
            "schema_version": "lifecycle-authority-v1",
            "authority_type": authority_type,
            "policy_id": str(self.policy["policy_id"]),
            "issued_at": issued_at,
            "issuer": {
                "identity": issuer,
                "authentication": authentication,
            },
            "authority": _normalize(authority),
        }
