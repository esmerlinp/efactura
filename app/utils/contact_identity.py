def is_client_contact(contact):
    """Return whether a CRM contact represents a customer."""
    return 'cliente' in {
        str(value or '').strip().lower()
        for value in (contact or {}).get('types', [])
    }
