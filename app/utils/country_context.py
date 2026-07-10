from flask import session


def get_current_country() -> str:
    return session.get('company_country', 'DO')
