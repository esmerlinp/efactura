"""Punto de extensión para el Anexo IT-H hotelero."""


class IT1ITHAdapter:
    RULES_VERSION = "pending-official-source"

    @classmethod
    def supported(cls, profile):
        return bool((profile or {}).get("economicSector") == "hotel")

    @classmethod
    def build_empty(cls):
        return {"enabled": False, "rules_version": cls.RULES_VERSION, "values": {}}
