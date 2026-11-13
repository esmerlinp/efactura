"""Email resolution for customer communications."""


def get_client_communication_email(client=None, invoice=None, explicit_email=""):
    """Return the most specific customer email, keeping legacy data compatible."""
    client = client or {}
    invoice = invoice or {}
    for value in (
        explicit_email,
        client.get("companyEmail"),
        client.get("email"),
        client.get("correo"),
        invoice.get("clientEmail"),
        invoice.get("email"),
        invoice.get("correo"),
    ):
        value = str(value or "").strip()
        if value:
            return value
    return ""
