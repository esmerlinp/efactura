from datetime import datetime

from app.countries.do.tax_rules import (
    ITBIS_RATE_GENERAL, ITBIS_RATE_REDUCED,
    ISR_CORPORATE_RATE, ISR_LARGE_TAXPAYER_RATE,
    WITHHOLDING_ISR_RATES, WITHHOLDING_ITBIS_RATES,
    RST_TAX_BRACKETS_2026, RST_ANNUAL_LIMIT_2026,
    calc_rst_isr, DEFAULT_TAX_RULES,
)


class TaxEngine:
    def __init__(self, owner_uid=None, sandbox=True):
        self.owner_uid = owner_uid
        self.sandbox = sandbox
        self._overrides = None

    def _load_overrides(self):
        if self._overrides is not None:
            return
        self._overrides = {}
        if self.owner_uid:
            try:
                from app.services.db_service import firebase_initialized, db_firestore
                if firebase_initialized and db_firestore is not None:
                    overrides_ref = db_firestore.collection("users").document(
                        self.owner_uid
                    ).collection("config").document("tax_rules").get()
                    if overrides_ref.exists:
                        self._overrides = overrides_ref.to_dict()
            except Exception as e:
                print(f"⚠️ TaxEngine: Error loading overrides: {e}")

    def _get_override(self, *keys):
        self._load_overrides()
        val = self._overrides
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return None
        return val

    def get_itbis_rate(self, item_type="general"):
        override = self._get_override("itbis", item_type)
        if override is not None:
            return float(override)
        return DEFAULT_TAX_RULES["itbis"].get(item_type, ITBIS_RATE_GENERAL)

    def get_isr_corporate_rate(self, is_large_taxpayer=False):
        key = "large_taxpayer" if is_large_taxpayer else "general"
        override = self._get_override("isr_corporate", key)
        if override is not None:
            return float(override)
        return DEFAULT_TAX_RULES["isr_corporate"][key]

    def get_withholding_isr_rate(self, withholding_type="goods_services"):
        override = self._get_override("withholding_isr", withholding_type)
        if override is not None:
            return float(override)
        return WITHHOLDING_ISR_RATES.get(withholding_type, 0.0)

    def get_withholding_itbis_rate(self, withholding_type="corporate_goods"):
        override = self._get_override("withholding_itbis", withholding_type)
        if override is not None:
            return float(override)
        return WITHHOLDING_ITBIS_RATES.get(withholding_type, 0.0)

    def get_withholding_isr_rate_for_supplier(self, supplier):
        if not supplier:
            return 0.0
        tasa = supplier.get("tasaRetencionISR", 0.0)
        if tasa > 0:
            return tasa / 100.0
        if supplier.get("esExtranjero"):
            return self.get_withholding_isr_rate("digital_services_abroad")
        if supplier.get("isrWithholding"):
            return self.get_withholding_isr_rate("goods_services")
        return 0.0

    def get_withholding_itbis_rate_for_supplier(self, supplier):
        if not supplier:
            return 0.0
        tasa = supplier.get("tasaRetencionITBIS", 0.0)
        if tasa > 0:
            return tasa / 100.0
        if supplier.get("itbisWithholding"):
            return self.get_withholding_itbis_rate("corporate_goods")
        return 0.0

    def get_isc_rate(self, codigo: str) -> float:
        codigo_map = {
            "001": "codigo_001_propina_legal",
            "002": "codigo_002_cdt",
            "003": "codigo_003_isc_seguros",
            "004": "codigo_004_telecomunicaciones",
            "005": "codigo_005_primera_placa",
        }
        key = codigo_map.get(str(codigo).zfill(3))
        if not key:
            return 0.0
        override = self._get_override("isc", key)
        if override is not None:
            return float(override)
        return DEFAULT_TAX_RULES.get("isc", {}).get(key, 0.0)

    def get_country(self) -> str:
        override = self._get_override("country")
        return override or DEFAULT_TAX_RULES.get("country", "RD")

    def get_rst_limit(self):
        override = self._get_override("rst", "limit")
        if override is not None:
            return float(override)
        return RST_ANNUAL_LIMIT_2026

    def calc_rst_isr(self, annual_taxable_income):
        override_brackets = self._get_override("rst", "brackets")
        brackets = override_brackets if override_brackets else RST_TAX_BRACKETS_2026
        prev_limit = 0.0
        for limit, rate, base_tax in brackets:
            if base_tax is None:
                return annual_taxable_income * rate
            if annual_taxable_income <= limit:
                return base_tax + (annual_taxable_income - prev_limit) * rate
            prev_limit = limit
        return annual_taxable_income * 0.25

    def resolve_itbis_rate(self, item, profile=None, client=None):
        if profile:
            regimen = profile.get("regimenFiscal", "ordinary")
            rules = self._get_regimen_rules(regimen)
            if not rules.get("itbis_enabled", True):
                return 0.0
        explicit = item.get("itbisRate")
        if explicit is not None and float(explicit) > 0:
            return float(explicit)
        tax_code = str(item.get("codigoImpuesto", "")).strip().zfill(3)
        if tax_code == "003":
            return self.get_itbis_rate("reduced")
        return self.get_itbis_rate("general")

    def _get_regimen_rules(self, regimen):
        from app.services.dgii import DGIIService
        return DGIIService.get_regimen_rules(regimen)
