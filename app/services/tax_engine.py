from datetime import datetime


class TaxEngine:
    def __init__(self, owner_uid=None, sandbox=True, country="DO", company_id=None):
        self.owner_uid = owner_uid
        self.sandbox = sandbox
        self.country = country
        self.company_id = company_id
        self._overrides = None
        self._provider = None
        self._rules = None
        self._withholding_isr = None
        self._withholding_vat = None

    def _load_overrides(self):
        if self._overrides is not None:
            return
        self._overrides = {}
        if self.owner_uid or self.company_id:
            try:
                from app.services.db_service import firebase_initialized, db_firestore, _company_coll
                if firebase_initialized and db_firestore is not None:
                    overrides_ref = _company_coll(owner_uid=self.owner_uid, company_id=self.company_id, coll_name="config").document("tax_rules").get()
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
        """Retención ISR por proveedor.

        Precedencia: tasaRetencionISR (custom) > withholdingCategory > esExtranjero
        (servicios digitales) > isrWithholding (bienes/servicios) > 0.
        """
        if not supplier:
            return 0.0
        tasa = float(supplier.get("tasaRetencionISR", 0.0) or 0)
        if tasa > 0:
            return tasa / 100.0
        category = str(supplier.get("withholdingCategory") or "").strip()
        cat_map, _ = self._category_maps()
        if category and category in cat_map and cat_map[category].get("isr"):
            return self.get_withholding_isr_rate(cat_map[category]["isr"])
        if supplier.get("esExtranjero"):
            return self.get_withholding_isr_rate("digital_services_abroad")
        if supplier.get("isrWithholding"):
            return self.get_withholding_isr_rate("goods_services")
        return 0.0

    def get_withholding_itbis_rate_for_supplier(self, supplier):
        """Retención ITBIS por proveedor (% del ITBIS a retener).

        Precedencia: tasaRetencionITBIS (custom) > withholdingCategory > itbisWithholding
        (bienes a personas jurídicas) > 0.
        """
        if not supplier:
            return 0.0
        tasa = float(supplier.get("tasaRetencionITBIS", 0.0) or 0)
        if tasa > 0:
            return tasa / 100.0
        category = str(supplier.get("withholdingCategory") or "").strip()
        cat_map, _ = self._category_maps()
        if category and category in cat_map and cat_map[category].get("itbis"):
            return self.get_withholding_itbis_rate(cat_map[category]["itbis"])
        if supplier.get("itbisWithholding"):
            return self.get_withholding_itbis_rate("corporate_goods")
        return 0.0

    def _category_maps(self):
        self._resolve_provider()
        return (
            self._rules.get("withholding_category_map", {}),
            self._rules.get("isr_rule_to_ir17_line", {}),
        )

    def resolve_withholding(self, supplier):
        """Resuelve la retención ISR/ITBIS de un proveedor con su regla e IR-17."""
        if not supplier:
            supplier = {}
        isr_rate = self.get_withholding_isr_rate_for_supplier(supplier)
        itbis_rate = self.get_withholding_itbis_rate_for_supplier(supplier)

        isr_rule = None
        if float(supplier.get("tasaRetencionISR", 0.0) or 0) > 0:
            isr_rule = "custom"
        else:
            category = str(supplier.get("withholdingCategory") or "").strip()
            cat_map, _ = self._category_maps()
            if category and category in cat_map and cat_map[category].get("isr"):
                isr_rule = cat_map[category]["isr"]
            elif supplier.get("esExtranjero"):
                isr_rule = "digital_services_abroad"
            elif supplier.get("isrWithholding"):
                isr_rule = "goods_services"

        itbis_rule = None
        if float(supplier.get("tasaRetencionITBIS", 0.0) or 0) > 0:
            itbis_rule = "custom"
        else:
            category = str(supplier.get("withholdingCategory") or "").strip()
            cat_map, _ = self._category_maps()
            if category and category in cat_map and cat_map[category].get("itbis"):
                itbis_rule = cat_map[category]["itbis"]
            elif supplier.get("itbisWithholding"):
                itbis_rule = "corporate_goods"

        _, ir17_map = self._category_maps()
        ir17_line = ir17_map.get(isr_rule) if isr_rule else None

        return {
            "isr_rate": round(isr_rate, 6),
            "isr_rule": isr_rule,
            "isr_ir17_line": ir17_line,
            "itbis_rate": round(itbis_rate, 6),
            "itbis_rule": itbis_rule,
        }

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
