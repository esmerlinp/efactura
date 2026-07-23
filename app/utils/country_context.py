from flask import session


def get_current_country(owner_uid=None, company_id=None):
    if company_id:
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(company_id, company_id=company_id)
        return profile.get("country", "DO") if profile else "DO"
    if owner_uid:
        from app.services.db_service import DatabaseService
        profile = DatabaseService.get_company_profile(owner_uid, company_id=company_id)
        return profile.get("country", "DO") if profile else "DO"
    return session.get('company_country', 'DO')
