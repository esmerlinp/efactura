from datetime import datetime


class TaxEngine:
    def __init__(self, owner_uid=None, sandbox=True, country="DO"):
        self.owner_uid = owner_uid
        self.sandbox = sandbox
        self.country = country
        self._overrides = None
        self._provider = None
        self._rules = None
        self._withholding_isr = None
        self._withholding_vat = None

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

    def _resolve_provider(self):
        if self._provider is None:
            from app.services.country_provider import CountryProviderFactory
            self._provider = CountryProviderFactory.create(self.country)
        if self._provider is None:
            raise ValueError(f"No country provider for {self.country}")
        if self._rules is None:
            rules = self._provider.get_tax_rules()
            self._rules = rules
            self._withholding_isr = rules.get("withholding_isr", {})
            self._withholding_vat = rules.get("withholding_vat", {})

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
        self._resolve_provider()
        return self._rules.get("vat", {}).get(item_type, self._rules.get("vat", {}).get("general", 0.0))

    def get_isr_corporate_rate(self, is_large_taxpayer=False):
        key = "large_taxpayer" if is_large_taxpayer else "general"
        override = self._get_override("isr_corporate", key)
        if override is not None:
            return float(override)
        self._resolve_provider()
        return self._rules["isr_corporate"][key]

    def get_withholding_isr_rate(self, withholding_type="goods_services"):
        override = self._get_override("withholding_isr", withholding_type)
        if override is not None:
            return float(override)
        self._resolve_provider()
        return self._withholding_isr.get(withholding_type, 0.0)

    def get_withholding_itbis_rate(self, withholding_type="corporate_goods"):
        override = self._get_override("withholding_itbis", withholding_type)
        if override is not None:
            return float(override)
        self._resolve_provider()
        return self._withholding_vat.get(withholding_type, 0.0)

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
        self._resolve_provider()
        return self._rules.get("isc", {}).get(key, 0.0)

    def get_country(self) -> str:
        override = self._get_override("country")
        if override:
            return override
        self._resolve_provider()
        return self._rules.get("country", self.country)

    def get_rst_limit(self):
        override = self._get_override("rst", "limit")
        if override is not None:
            return float(override)
        self._resolve_provider()
        return self._rules.get("rst", {}).get("limit", 0.0)

    def calc_rst_isr(self, annual_taxable_income):
        override_brackets = self._get_override("rst", "brackets")
        if override_brackets:
            brackets = override_brackets
        else:
            self._resolve_provider()
            brackets = self._rules.get("rst", {}).get("brackets", [])
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
            vat_enabled = rules.get("vat_enabled", rules.get("itbis_enabled", True))
            if not vat_enabled:
                return 0.0
        explicit = item.get("itbisRate")
        if explicit is not None and float(explicit) > 0:
            return float(explicit)
        tax_code = str(item.get("codigoImpuesto", "")).strip().zfill(3)
        if tax_code == "003":
            return self.get_itbis_rate("reduced")
        return self.get_itbis_rate("general")

    def _get_regimen_rules(self, regimen):
        self._resolve_provider()
        regimen_data = self._provider.get_regimen_rules()
        regimes = regimen_data["regimes"]
        default = regimen_data["default"]
        return regimes.get(regimen, regimes.get(default, {}))
