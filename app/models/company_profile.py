from pydantic import BaseModel


class CompanyProfile(BaseModel):
    ownerUID: str = ""
    companyName: str = "Mi Empresa SRL"
    tradeName: str = "Mi Empresa"
    companyRNC: str = "132109122"
    companyType: str = "associated"
    companyAddress: str = "Santo Domingo, RD"
    province: str = "Santo Domingo"
    municipality: str = "Santo Domingo de Guzmán"
    companyPhone: str = "809-555-0199"
    companyEmail: str = "factura@miempresa.com.do"
    colorMarca: str = "#10b981"
    gradientEnabled: bool = False
    logoUrl: str = ""
    logoBase64: str = ""
    regimenFiscal: str = "ordinary"
    certificateName: str = ""
    certificateExtension: str = ""
    certificateContent: str = ""
    certificatePassword: str = ""
    planId: str = ""
    plan_version: int = 0
    status: str = "Activo"
    posEnabled: bool = True
    ruiEnabled: bool = False
    ruiAuthorizationNumber: str = ""
    ruiAutoGenerate: bool = True
    ruiAutoGenerateHour: str = "23:00"
    productionEnabled: bool = True
    sandboxEnabled: bool = True
    sandboxIndefinite: bool = True
    sandboxStartDate: str = ""
    sandboxEndDate: str = ""
    cancel_at_period_end: bool = False
    cancel_scheduled_date: str = ""
    country: str = "DO"
    createdBy: str = ""
    createdAt: str = ""
    updatedBy: str = ""
    updatedAt: str = ""
    certificateSignerName: str = ""
    certificateSignerPosition: str = ""
    stampUrl: str = ""
    signatureUrl: str = ""
    nextCertificateNumber: int = 1
