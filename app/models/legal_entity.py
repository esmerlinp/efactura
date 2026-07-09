"""LegalEntity — Entidad legal/razón social para soporte multi-compañía."""

from pydantic import BaseModel


class LegalEntity(BaseModel):
    """Razón social o entidad legal independiente dentro de un tenant."""

    id: str = ""
    name: str = ""                    # Razón social
    tradeName: str = ""               # Nombre comercial
    rnc: str = ""                     # RNC/Cédula jurídica (9 u 11 dígitos)
    taxRegime: str = "normal"         # "normal" | "simplificado" | "especial"
    economicActivityCode: str = ""    # Código de actividad económica DGII
    currency: str = "DOP"
    country: str = "DO"
    address: str = ""
    municipality: str = ""
    province: str = ""
    phone: str = ""
    email: str = ""
    website: str = ""

    # Certificado digital para e-CF
    dgiiCertificateAlias: str = ""

    # Configuración fiscal
    fiscalYearStartMonth: int = 1     # Mes de inicio del año fiscal
    fiscalYearEndMonth: int = 12
    itbisRate: float = 0.18

    # Estado
    isActive: bool = True
    isDefault: bool = False

    # Metadatos
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""

    @property
    def rnc_clean(self) -> str:
        return self.rnc.replace("-", "").strip()
