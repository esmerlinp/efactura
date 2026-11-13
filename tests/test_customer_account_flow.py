"""Regresión del flujo de identidad global del cliente en DatabaseService.save_client.

Un cliente creado desde cualquier empresa debe quedar vinculado a la cuenta
global (`customer_accounts`) usada por el portal independiente, con contraseña
inicial = RNC. Si el cliente no trae email, se usa el email de la empresa.
"""

from unittest.mock import MagicMock, patch

from app.services import db_service


def _run_save(client_dict, company_email=""):
    with patch.object(db_service, "firebase_initialized", True), \
         patch.object(db_service, "_company_coll", return_value=MagicMock()), \
         patch.object(db_service, "_invalidate_clients"), \
         patch.object(db_service, "_invalidate_crm_contacts"), \
         patch.object(
             db_service.DatabaseService, "get_company_profile",
             return_value={"companyEmail": company_email, "email": company_email},
         ), \
         patch(
             "app.services.customer_account_service.CustomerAccountService.ensure_for_contact",
             return_value="acct-1",
         ) as ensure:
        result = db_service.DatabaseService.save_client(
            owner_uid="u1", client_id="c1", client_dict=client_dict,
            sandbox=True, company_id="comp-1",
        )
        return result, ensure


def test_save_client_links_global_account_when_email_present():
    result, ensure = _run_save({
        "rnc": "131880681",
        "razonSocial": "Cliente Uno SRL",
        "email": "cliente@dominio.com",
    })

    ensure.assert_called_once()
    contact = ensure.call_args.args[0]
    assert contact["id"] == "c1"
    assert contact["email"] == "cliente@dominio.com"
    assert "cliente" in contact.get("types", [])
    assert result["customerId"] == "acct-1"


def test_save_client_falls_back_to_company_email():
    result, ensure = _run_save(
        {"rnc": "131880681", "razonSocial": "Cliente Sin Email SRL"},
        company_email="facturacion@empresa.com.do",
    )

    ensure.assert_called_once()
    contact = ensure.call_args.args[0]
    assert contact["email"] == "facturacion@empresa.com.do"
    assert result["email"] == "facturacion@empresa.com.do"
    assert result["customerId"] == "acct-1"


def test_save_client_skips_account_when_no_email_anywhere():
    result, ensure = _run_save(
        {"rnc": "131880681", "razonSocial": "Cliente Sin Email SRL"},
        company_email="",
    )

    ensure.assert_not_called()
    assert result.get("customerId") is None


def test_save_client_swallows_account_errors():
    with patch.object(db_service, "firebase_initialized", True), \
         patch.object(db_service, "_company_coll", return_value=MagicMock()), \
         patch.object(db_service, "_invalidate_clients"), \
         patch.object(db_service, "_invalidate_crm_contacts"), \
         patch(
             "app.services.customer_account_service.CustomerAccountService.ensure_for_contact",
             side_effect=ValueError("boom"),
         ):
        result = db_service.DatabaseService.save_client(
            owner_uid="u1", client_id="c1",
            client_dict={"rnc": "131880681", "razonSocial": "X", "email": "x@y.com"},
            sandbox=True, company_id="comp-1",
        )

    assert result.get("customerId") is None
