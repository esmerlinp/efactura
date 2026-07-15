from datetime import datetime, timezone, timedelta
from app.services.db_service import DatabaseService

try:
    from cryptography.hazmat.primitives.serialization import pkcs12
    CRYPTOGRAPHY_AVAILABLE = True
except Exception:
    CRYPTOGRAPHY_AVAILABLE = False


class EcfReadinessError(ValueError):
    pass


class EcfReadinessService:

    ERROR_CODES = {
        "CERTIFICATE_MISSING",
        "CERTIFICATE_PASSWORD_INVALID",
        "CERTIFICATE_CORRUPT",
        "CERTIFICATE_EXPIRED",
        "LOGO_MISSING",
        "CERTIFICATE_EXPIRING_SOON",
        "COMPANY_RNC_MISSING",
        "COMPANY_NAME_MISSING",
    }

    @staticmethod
    def get_status(owner_uid):
        profile = DatabaseService.get_company_profile(owner_uid)
        if not profile:
            return EcfReadinessService._empty_status()

        blocking_errors = []
        warnings = []
        certificate_info = {"configured": False, "valid": False, "expires_at": None}
        logo_info = {"configured": False}
        company_info = {
            "rnc_configured": bool(profile.get("companyRNC")),
            "name_configured": bool(profile.get("companyName")),
        }

        # --- RNC / Name ---
        rnc = (profile.get("companyRNC") or "").strip()
        name = (profile.get("companyName") or "").strip()
        if not rnc:
            blocking_errors.append({
                "code": "COMPANY_RNC_MISSING",
                "message": "No se ha configurado el RNC de la empresa."
            })
        if not name:
            blocking_errors.append({
                "code": "COMPANY_NAME_MISSING",
                "message": "No se ha configurado la razón social de la empresa."
            })

        # --- Certificate ---
        cert_content = profile.get("certificateContent") or ""
        cert_password = profile.get("certificatePassword") or ""

        if not cert_content:
            blocking_errors.append({
                "code": "CERTIFICATE_MISSING",
                "message": "No existe un certificado digital configurado."
            })
        else:
            certificate_info["configured"] = True
            cert_valid, cert_detail = EcfReadinessService._validate_certificate(
                cert_content, cert_password
            )
            if cert_valid:
                certificate_info["valid"] = True
                if cert_detail and cert_detail.get("notAfter"):
                    expires_at = cert_detail["notAfter"]
                    certificate_info["expires_at"] = expires_at
                    try:
                        exp_dt = datetime.fromisoformat(expires_at)
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        now = datetime.now(timezone.utc)
                        if exp_dt < now:
                            blocking_errors.append({
                                "code": "CERTIFICATE_EXPIRED",
                                "message": "El certificado digital ha expirado."
                            })
                            certificate_info["valid"] = False
                        elif exp_dt - now <= timedelta(days=30):
                            warnings.append({
                                "code": "CERTIFICATE_EXPIRING_SOON",
                                "message": f"El certificado digital expira el {exp_dt.strftime('%d/%m/%Y')}."
                            })
                    except Exception:
                        pass
            else:
                certificate_info["valid"] = False
                blocking_errors.append({
                    "code": cert_detail.get("code", "CERTIFICATE_CORRUPT"),
                    "message": cert_detail.get("message", "El certificado digital no es válido.")
                })

        # --- Logo ---
        logo_url = profile.get("logoUrl") or ""
        logo_b64 = profile.get("logoBase64") or ""
        logo_info["configured"] = bool(logo_url or logo_b64)
        if not logo_info["configured"]:
            warnings.append({
                "code": "LOGO_MISSING",
                "message": "No se ha configurado un logo para la empresa."
            })

        can_issue_ecf = len(blocking_errors) == 0

        return {
            "can_issue_ecf": can_issue_ecf,
            "blocking_errors": blocking_errors,
            "warnings": warnings,
            "certificate": certificate_info,
            "logo": logo_info,
            "company": company_info,
        }

    @staticmethod
    def validate_or_raise(owner_uid):
        status = EcfReadinessService.get_status(owner_uid)
        if not status["can_issue_ecf"]:
            messages = [e["message"] for e in status["blocking_errors"]]
            first_code = status["blocking_errors"][0]["code"]
            raise EcfReadinessError(" | ".join(messages))
        return status

    @staticmethod
    def _validate_certificate(cert_content_b64, cert_password):
        if not CRYPTOGRAPHY_AVAILABLE:
            return False, {"code": "CERTIFICATE_CORRUPT", "message": "Librería criptográfica no disponible."}
        if not cert_content_b64:
            return False, {"code": "CERTIFICATE_MISSING", "message": "No hay contenido de certificado."}

        import base64
        try:
            cert_data = base64.b64decode(cert_content_b64)
        except Exception:
            return False, {"code": "CERTIFICATE_CORRUPT", "message": "El certificado almacenado está corrupto (base64 inválido)."}

        try:
            key, cert, additional = pkcs12.load_key_and_certificates(
                cert_data,
                cert_password.encode("utf-8") if cert_password else None
            )
        except ValueError:
            return False, {"code": "CERTIFICATE_PASSWORD_INVALID", "message": "La contraseña del certificado es incorrecta."}
        except Exception as e:
            return False, {"code": "CERTIFICATE_CORRUPT", "message": f"Error al leer el certificado: {str(e)}"}

        if not cert:
            return False, {"code": "CERTIFICATE_CORRUPT", "message": "No se encontró un certificado válido en el archivo."}

        try:
            not_after = cert.not_valid_after_utc.isoformat()
        except AttributeError:
            not_after = cert.not_valid_after.isoformat()

        return True, {"notAfter": not_after}

    @staticmethod
    def _empty_status():
        return {
            "can_issue_ecf": False,
            "blocking_errors": [{"code": "COMPANY_NOT_FOUND", "message": "No se encontró perfil de empresa."}],
            "warnings": [],
            "certificate": {"configured": False, "valid": False, "expires_at": None},
            "logo": {"configured": False},
            "company": {"rnc_configured": False, "name_configured": False},
        }
