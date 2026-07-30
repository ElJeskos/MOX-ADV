"""Durable reservation and settlement for every model invocation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from mox_adv.recommend_contracts import ProviderMetadata


class ModelCostRejected(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _decimal(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID") from error
    if not parsed.is_finite() or parsed < 0:
        raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
    return parsed


def _text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


@dataclass(frozen=True)
class ModelCostReservation:
    reservation_id: str
    provider: str
    model_id: str
    maximum_input_tokens: int
    maximum_output_tokens: int
    reserved_cost_rub: str
    warning: bool


@dataclass(frozen=True)
class ModelCostUsage:
    charged_cost_rub: str
    reserved_cost_rub: str
    call_count: int
    warning: bool
    exhausted: bool


class DurableModelCostLedger:
    """Atomically cap model calls using one persisted tariff configuration."""

    def __init__(self, path: Path, policy: Mapping[str, Any]) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.limit = _decimal(policy["limits"]["llm_total_cost_rub"], "limit")
        self.warning_percent = _decimal(
            policy["limits"]["llm_warning_percent"],
            "warning",
        )
        config = policy.get("llm_cost")
        if (
            not isinstance(config, Mapping)
            or set(config)
            != {
                "currency",
                "exchange_rate_rub_per_usd",
                "tariffs",
            }
            or config["currency"] != "RUB"
        ):
            raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
        self.currency = str(config["currency"])
        self.exchange_rate = _decimal(
            config.get("exchange_rate_rub_per_usd"),
            "exchange rate",
        )
        if (
            self.limit <= 0
            or self.warning_percent <= 0
            or self.warning_percent >= 100
            or self.exchange_rate <= 0
        ):
            raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
        tariffs = config.get("tariffs")
        if not isinstance(tariffs, list) or not tariffs:
            raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
        self.tariffs: dict[tuple[str, str], tuple[Decimal, Decimal]] = {}
        for item in tariffs:
            if (
                not isinstance(item, Mapping)
                or set(item)
                != {
                    "provider",
                    "model_id",
                    "input_usd_per_million",
                    "output_usd_per_million",
                }
            ):
                raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
            key = (str(item.get("provider", "")), str(item.get("model_id", "")))
            if not all(key) or key in self.tariffs:
                raise ModelCostRejected("MODEL_COST_CONFIGURATION_INVALID")
            self.tariffs[key] = (
                _decimal(item.get("input_usd_per_million"), "input tariff"),
                _decimal(item.get("output_usd_per_million"), "output tariff"),
            )
        canonical_config = json.dumps(
            {
                "currency": self.currency,
                "limit": _text(self.limit),
                "warning_percent": _text(self.warning_percent),
                "exchange_rate_rub_per_usd": _text(self.exchange_rate),
                "tariffs": [
                    {
                        "provider": provider,
                        "model_id": model,
                        "input_usd_per_million": _text(rates[0]),
                        "output_usd_per_million": _text(rates[1]),
                    }
                    for (provider, model), rates in sorted(self.tariffs.items())
                ],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        self.config_hash = "sha256:" + hashlib.sha256(
            canonical_config.encode("utf-8")
        ).hexdigest()
        self._initialize(canonical_config)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self, canonical_config: str) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS model_cost_configuration (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    canonical_json TEXT NOT NULL,
                    canonical_hash TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_cost_calls (
                    reservation_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    maximum_input_tokens INTEGER NOT NULL,
                    maximum_output_tokens INTEGER NOT NULL,
                    reserved_cost_rub TEXT NOT NULL,
                    charged_cost_rub TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    status TEXT NOT NULL,
                    detail TEXT
                );
                """
            )
            existing = connection.execute(
                "SELECT canonical_json, canonical_hash "
                "FROM model_cost_configuration WHERE singleton = 1"
            ).fetchone()
            if existing is None:
                connection.execute(
                    "INSERT INTO model_cost_configuration "
                    "(singleton, canonical_json, canonical_hash) VALUES (1, ?, ?)",
                    (canonical_config, self.config_hash),
                )
            elif (
                existing["canonical_json"] != canonical_config
                or existing["canonical_hash"] != self.config_hash
            ):
                raise ModelCostRejected("MODEL_COST_CONFIGURATION_CHANGED")

    def reserve(
        self,
        provider: str,
        model_id: str,
        maximum_input_tokens: int,
        maximum_output_tokens: int,
    ) -> ModelCostReservation:
        if (
            (provider, model_id) not in self.tariffs
            or isinstance(maximum_input_tokens, bool)
            or isinstance(maximum_output_tokens, bool)
            or not isinstance(maximum_input_tokens, int)
            or not isinstance(maximum_output_tokens, int)
            or maximum_input_tokens < 0
            or maximum_output_tokens < 0
        ):
            raise ModelCostRejected("MODEL_COST_PROFILE_MISSING")
        reserved = self._calculate(
            provider,
            model_id,
            maximum_input_tokens,
            maximum_output_tokens,
        )
        reservation_id = "model-call-" + uuid.uuid4().hex
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            charged, active, _ = self._totals(connection)
            if charged >= self.limit or charged + active + reserved > self.limit:
                raise ModelCostRejected("MODEL_COST_LIMIT_EXHAUSTED")
            warning = self._warning(charged + active + reserved)
            connection.execute(
                "INSERT INTO model_cost_calls "
                "(reservation_id, provider, model_id, maximum_input_tokens, "
                "maximum_output_tokens, reserved_cost_rub, status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'RESERVED')",
                (
                    reservation_id,
                    provider,
                    model_id,
                    maximum_input_tokens,
                    maximum_output_tokens,
                    _text(reserved),
                ),
            )
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
        return ModelCostReservation(
            reservation_id=reservation_id,
            provider=provider,
            model_id=model_id,
            maximum_input_tokens=maximum_input_tokens,
            maximum_output_tokens=maximum_output_tokens,
            reserved_cost_rub=_text(reserved),
            warning=warning,
        )

    def settle(
        self,
        reservation: ModelCostReservation,
        metadata: ProviderMetadata,
    ) -> ProviderMetadata:
        if (
            type(metadata) is not ProviderMetadata
            or metadata.provider != reservation.provider
            or metadata.model_id != reservation.model_id
            or isinstance(metadata.input_tokens, bool)
            or isinstance(metadata.output_tokens, bool)
            or not isinstance(metadata.input_tokens, int)
            or not isinstance(metadata.output_tokens, int)
            or metadata.input_tokens < 0
            or metadata.output_tokens < 0
            or metadata.input_tokens > reservation.maximum_input_tokens
            or metadata.output_tokens > reservation.maximum_output_tokens
        ):
            self.fail(reservation, "MODEL_USAGE_METADATA_INVALID")
            raise ModelCostRejected("MODEL_USAGE_METADATA_INVALID")
        charged = self._calculate(
            metadata.provider,
            metadata.model_id,
            metadata.input_tokens,
            metadata.output_tokens,
        )
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE model_cost_calls SET charged_cost_rub = ?, "
                "input_tokens = ?, output_tokens = ?, status = 'SETTLED' "
                "WHERE reservation_id = ? AND status = 'RESERVED'",
                (
                    _text(charged),
                    metadata.input_tokens,
                    metadata.output_tokens,
                    reservation.reservation_id,
                ),
            )
            if updated.rowcount != 1:
                raise ModelCostRejected("MODEL_COST_RESERVATION_INVALID")
        return ProviderMetadata(
            provider=metadata.provider,
            model_id=metadata.model_id,
            input_tokens=metadata.input_tokens,
            output_tokens=metadata.output_tokens,
            cost_rub=_text(charged),
            duration_ms=metadata.duration_ms,
        )

    def fail(
        self,
        reservation: ModelCostReservation,
        detail: str,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE model_cost_calls SET charged_cost_rub = reserved_cost_rub, "
                "status = 'FAILED', detail = ? "
                "WHERE reservation_id = ? AND status = 'RESERVED'",
                (detail, reservation.reservation_id),
            )

    def record_synthetic_cost(self, call_id: str, cost_rub: Any) -> None:
        cost = _decimal(cost_rub, "synthetic cost")
        if not call_id:
            raise ModelCostRejected("MODEL_COST_SYNTHETIC_INPUT_INVALID")
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO model_cost_calls "
                "(reservation_id, provider, model_id, maximum_input_tokens, "
                "maximum_output_tokens, reserved_cost_rub, charged_cost_rub, "
                "input_tokens, output_tokens, status, detail) "
                "VALUES (?, 'synthetic', 'synthetic', 0, 0, '0', ?, 0, 0, "
                "'SETTLED', 'SYNTHETIC_ACCEPTANCE_COUNTER')",
                (call_id, _text(cost)),
            )

    def usage(self) -> ModelCostUsage:
        with self._connect() as connection:
            charged, reserved, count = self._totals(connection)
        return ModelCostUsage(
            charged_cost_rub=_text(charged),
            reserved_cost_rub=_text(reserved),
            call_count=count,
            warning=self._warning(charged + reserved),
            exhausted=charged >= self.limit,
        )

    def _calculate(
        self,
        provider: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
    ) -> Decimal:
        input_rate, output_rate = self.tariffs[(provider, model_id)]
        usd = (
            Decimal(input_tokens) * input_rate
            + Decimal(output_tokens) * output_rate
        ) / Decimal(1_000_000)
        return usd * self.exchange_rate

    def _warning(self, total: Decimal) -> bool:
        return total * Decimal(100) >= self.limit * self.warning_percent

    @staticmethod
    def _totals(
        connection: sqlite3.Connection,
    ) -> tuple[Decimal, Decimal, int]:
        rows = connection.execute(
            "SELECT charged_cost_rub, reserved_cost_rub, status "
            "FROM model_cost_calls"
        ).fetchall()
        return (
            sum(
                (
                    Decimal(str(row["charged_cost_rub"]))
                    for row in rows
                    if row["charged_cost_rub"] is not None
                ),
                Decimal(0),
            ),
            sum(
                (
                    Decimal(str(row["reserved_cost_rub"]))
                    for row in rows
                    if row["status"] == "RESERVED"
                ),
                Decimal(0),
            ),
            len(rows),
        )
