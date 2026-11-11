"""Conservative, non-destructive migration of commercial legacy contracts."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable

from app.models.recurring_contract import (
    BillingFrequency,
    BillingMode,
    ContractTermsVersion,
    FirstBillingPolicy,
    PeriodEndPolicy,
    ProrationPolicy,
    RecurringContract,
    RecurringContractLine,
    RecurringContractStatus,
)
from app.models.recurring_contract_migration import (
    MigrationDisposition,
    MigrationReport,
    RecurringContractMigrationRecord,
)


class RecurringContractMigrationService:
    """Maps only unambiguous legacy data and never changes source records."""

    FREQUENCY_MAP = {
        "semanal": BillingFrequency.WEEKLY,
        "weekly": BillingFrequency.WEEKLY,
        "quincenal": BillingFrequency.BIWEEKLY,
        "biweekly": BillingFrequency.BIWEEKLY,
        "mensual": BillingFrequency.MONTHLY,
        "monthly": BillingFrequency.MONTHLY,
        "trimestral": BillingFrequency.QUARTERLY,
        "quarterly": BillingFrequency.QUARTERLY,
        "semestral": BillingFrequency.SEMIANNUAL,
        "semiannual": BillingFrequency.SEMIANNUAL,
        "anual": BillingFrequency.ANNUAL,
        "annual": BillingFrequency.ANNUAL,
    }
    STATUS_MAP = {
        "activo": RecurringContractStatus.ACTIVE,
        "active": RecurringContractStatus.ACTIVE,
        "borrador": RecurringContractStatus.DRAFT,
        "draft": RecurringContractStatus.DRAFT,
        "pendiente de aprobación": RecurringContractStatus.PENDING_APPROVAL,
        "pending_approval": RecurringContractStatus.PENDING_APPROVAL,
        "suspendido": RecurringContractStatus.SUSPENDED,
        "suspended": RecurringContractStatus.SUSPENDED,
        "cancelado": RecurringContractStatus.CANCELLED,
        "cancelled": RecurringContractStatus.CANCELLED,
        "expirado": RecurringContractStatus.EXPIRED,
        "expired": RecurringContractStatus.EXPIRED,
    }

    def __init__(self, store: Any | None = None, *, clock: Callable[[], datetime] | None = None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def dry_run(self, contracts: Iterable[dict], *, owner_uid: str, company_id: str, sandbox: bool = True) -> MigrationReport:
        return self.run(contracts, owner_uid=owner_uid, company_id=company_id, sandbox=sandbox, dry_run=True)

    def run(self, contracts: Iterable[dict], *, owner_uid: str, company_id: str, sandbox: bool = True, dry_run: bool = True) -> MigrationReport:
        records = []
        for source in contracts:
            record = self.plan_one(source, owner_uid=owner_uid, company_id=company_id, sandbox=sandbox)
            records.append(record)
            if not dry_run and record.disposition == MigrationDisposition.MIGRATABLE:
                if not self.store:
                    raise RuntimeError("Se requiere store para una migración con escritura")
                self.store.save_if_absent(record)
        counts = {disposition: sum(record.disposition == disposition for record in records) for disposition in MigrationDisposition}
        return MigrationReport(
            owner_uid=owner_uid,
            company_id=company_id,
            sandbox=sandbox,
            dry_run=dry_run,
            total=len(records),
            migratable=counts[MigrationDisposition.MIGRATABLE],
            needs_review=counts[MigrationDisposition.NEEDS_REVIEW],
            incompatible=counts[MigrationDisposition.INCOMPATIBLE],
            already_migrated=counts[MigrationDisposition.ALREADY_MIGRATED],
            records=tuple(records),
        )

    def plan_one(self, source: dict, *, owner_uid: str, company_id: str, sandbox: bool) -> RecurringContractMigrationRecord:
        source_id = str(source.get("id") or "").strip()
        if not source_id:
            return self._record(source, "", owner_uid, company_id, sandbox, MigrationDisposition.INCOMPATIBLE, errors=("Falta id del contrato legacy",))
        fingerprint = self.fingerprint(source)
        target_id = source_id
        if self.store and self.store.exists(source_id, owner_uid=owner_uid, company_id=company_id, sandbox=sandbox, source_fingerprint=fingerprint):
            return self._record(source, source_id, owner_uid, company_id, sandbox, MigrationDisposition.ALREADY_MIGRATED, fingerprint=fingerprint)

        warnings = []
        errors = []
        values = self._normalize(source, errors, warnings)
        disposition = MigrationDisposition.MIGRATABLE if not errors and not warnings else MigrationDisposition.NEEDS_REVIEW if not errors else MigrationDisposition.INCOMPATIBLE
        target = None
        if values and not errors:
            try:
                target = self._build_target(source, values, owner_uid, company_id, target_id, warnings)
            except (TypeError, ValueError) as exc:
                errors.append(str(exc))
                disposition = MigrationDisposition.INCOMPATIBLE
        return self._record(source, source_id, owner_uid, company_id, sandbox, disposition, fingerprint=fingerprint, target=target, warnings=warnings, errors=errors)

    def _normalize(self, source, errors, warnings):
        start = self._date(source.get("startDate") or source.get("start_date"), "startDate", errors)
        next_billing = self._date(source.get("nextBillingDate") or source.get("next_billing_date"), "nextBillingDate", errors)
        end = self._date(source.get("endDate") or source.get("end_date"), "endDate", errors, optional=True)
        frequency_raw = str(source.get("frequency") or source.get("recurrenceInterval") or "").strip().lower()
        frequency = self.FREQUENCY_MAP.get(frequency_raw)
        if not frequency:
            errors.append("Frecuencia ausente o desconocida")
        status_raw = str(source.get("status") or "").strip().lower()
        status = self.STATUS_MAP.get(status_raw)
        if not status:
            errors.append("Estado ausente o desconocido")
        lines = self._lines(source, errors, warnings)
        if not lines:
            errors.append("No existen líneas inequívocas para migrar")
        ecf_type = source.get("ecfType") or source.get("ecf_type")
        if not ecf_type:
            warnings.append("Falta configuración fiscal formal; needsFiscalReview=true")
        amount = self._amount(source, lines, warnings)
        if amount is None:
            warnings.append("La interpretación del importe no es inequívoca")
        return {"start": start, "next": next_billing, "end": end, "frequency": frequency, "status": status, "lines": lines, "ecf_type": ecf_type, "amount": amount}

    def _build_target(self, source, values, owner_uid, company_id, target_id, warnings):
        start = values["start"]
        target = RecurringContract(
            id=target_id,
            owner_uid=owner_uid,
            company_id=company_id,
            contract_number=str(source.get("contractNumber") or source.get("contract_number") or ""),
            client_id=str(source.get("clientId") or source.get("client_id") or ""),
            client_name_snapshot=str(source.get("clientName") or source.get("client_name") or ""),
            client_rnc_snapshot=str(source.get("clientRNC") or source.get("client_rnc") or ""),
            quotation_id=str(source.get("quotationId") or ""),
            status=values["status"],
            start_date=start,
            end_date=values["end"],
            auto_renew=bool(source.get("autoRenew", False)),
            frequency=values["frequency"],
            billing_mode=BillingMode.ADVANCE,
            billing_day=values["next"].day,
            billing_anchor_date=values["next"],
            first_billing_policy=FirstBillingPolicy.NEXT_ANCHOR,
            proration_policy=ProrationPolicy.DAILY if source.get("proratedFirstAmount") is not None else ProrationPolicy.NONE,
            period_end_policy=PeriodEndPolicy.ANCHOR_DAY,
            ecf_type=values["ecf_type"] or None,
            currency=str(source.get("currency") or "DOP"),
            needs_fiscal_review=not bool(values["ecf_type"]),
            lines=tuple(values["lines"]),
            schema_version=2,
        )
        original = dict(source)
        terms = ContractTermsVersion(
            version=1,
            effective_from=start,
            ecf_type=values["ecf_type"] or None,
            currency=target.currency,
            billing_mode=target.billing_mode,
            lines=tuple(values["lines"]),
        )
        target = target.add_terms_version(terms)
        target_dict = target.model_dump(mode="json")
        target_dict["legacySource"] = original
        target_dict["legacySourceId"] = source.get("id")
        target_dict["legacySourceFingerprint"] = self.fingerprint(source)
        target_dict["migrationSchemaVersion"] = 1
        target_dict["legacyUnmappedFields"] = {key: value for key, value in original.items() if key not in target_dict}
        return target_dict

    def _lines(self, source, errors, warnings):
        raw_lines = source.get("contractLines") or source.get("lines") or []
        result = []
        if not isinstance(raw_lines, list):
            errors.append("contractLines no es una lista")
            return result
        for index, line in enumerate(raw_lines):
            if not isinstance(line, dict):
                errors.append(f"Línea {index + 1} inválida")
                continue
            name = str(line.get("name") or "").strip()
            if not name:
                errors.append(f"Línea {index + 1} sin nombre")
                continue
            try:
                result.append(RecurringContractLine(
                    item_id=str(line.get("itemId") or line.get("item_id") or ""),
                    code=str(line.get("code") or ""),
                    name=name,
                    quantity=float(line.get("quantity", 1)),
                    unit_price=float(line.get("unitPrice", line.get("unit_price", 0))),
                    itbis_rate=float(line.get("itbisRate", line.get("itbis_rate", 0))),
                    discount_rate=float(line.get("discountRate", line.get("discount_rate", 0))),
                ))
            except (TypeError, ValueError) as exc:
                errors.append(f"Línea {index + 1} inválida: {exc}")
        return result

    @staticmethod
    def _amount(source, lines, warnings):
        if lines:
            calculated = round(sum(line.total for line in lines), 2)
            raw = source.get("amount")
            if raw is not None:
                try:
                    if abs(float(raw) - calculated) > 0.01:
                        warnings.append("amount no coincide con el total calculado de las líneas")
                except (TypeError, ValueError):
                    warnings.append("amount no numérico")
            return calculated
        return None

    @staticmethod
    def _date(value, field, errors, optional=False):
        if value in (None, ""):
            if not optional:
                errors.append(f"Falta {field}")
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            errors.append(f"{field} no tiene formato ISO válido")
            return None

    @staticmethod
    def fingerprint(source):
        return hashlib.sha256(json.dumps(source, sort_keys=True, default=str).encode()).hexdigest()

    def _record(self, source, source_id, owner_uid, company_id, sandbox, disposition, *, fingerprint=None, target=None, warnings=(), errors=()):
        return RecurringContractMigrationRecord(
            migration_id=hashlib.sha256(f"{company_id}:{sandbox}:{source_id}:{fingerprint or self.fingerprint(source)}".encode()).hexdigest(),
            source_id=source_id,
            owner_uid=owner_uid,
            company_id=company_id,
            sandbox=sandbox,
            target_id=source_id,
            disposition=disposition,
            source_fingerprint=fingerprint or self.fingerprint(source),
            source_document=dict(source),
            target_document=target,
            warnings=tuple(warnings),
            errors=tuple(errors),
            created_at=self.clock(),
        )
