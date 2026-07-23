from dataclasses import dataclass, field
from typing import Optional
from flask import session, g

from app.services.db_service import db_firestore, firebase_initialized


# ── In-memory cache for current request ──
_ctx_local = {}


def _clear_ctx():
    _ctx_local.clear()


def _resolve_company_id_from_session() -> Optional[str]:
    return session.get('selected_company_id')


def _resolve_owner_uid_from_session() -> Optional[str]:
    return session.get('selected_owner_uid') or session.get('user', {}).get('ownerUID')


@dataclass
class CompanyContext:
    company_id: str = ''
    owner_uid: str = ''
    name: str = ''
    trade_name: str = ''
    rnc: str = ''
    plan_id: str = ''
    plan_version: int = 0
    status: str = 'active'
    configured: bool = False
    country: str = 'DO'
    certificate_name: str = ''
    certificate_content: str = ''
    certificate_password: str = ''
    regimen_fiscal: str = 'ordinary'
    pos_enabled: bool = True
    production_enabled: bool = True
    sandbox_enabled: bool = True
    sandbox_indefinite: bool = True
    sandbox_start_date: str = ''
    sandbox_end_date: str = ''
    color_marca: str = '#10b981'
    gradient_enabled: bool = False
    logo_url: str = ''
    logo_base64: str = ''
    theme: str = 'moderno'
    apply_color_marca_ui: bool = True
    apply_color_marca_reports: bool = True
    billing_type: str = 'Pago por uso'
    modules: dict = field(default_factory=dict)

    @property
    def is_configured(self) -> bool:
        return bool(self.configured)

    def to_legacy_profile(self) -> dict:
        return {
            'ownerUID': self.owner_uid,
            'companyName': self.name,
            'tradeName': self.trade_name,
            'companyRNC': self.rnc,
            'planId': self.plan_id,
            'plan_version': self.plan_version,
            'status': 'Activo' if self.status == 'active' else self.status,
            'country': self.country,
            'certificateName': self.certificate_name,
            'certificateContent': self.certificate_content,
            'certificatePassword': self.certificate_password,
            'regimenFiscal': self.regimen_fiscal,
            'posEnabled': self.pos_enabled,
            'productionEnabled': self.production_enabled,
            'sandboxEnabled': self.sandbox_enabled,
            'sandboxIndefinite': self.sandbox_indefinite,
            'sandboxStartDate': self.sandbox_start_date,
            'sandboxEndDate': self.sandbox_end_date,
            'colorMarca': self.color_marca,
            'gradientEnabled': self.gradient_enabled,
            'logoUrl': self.logo_url,
            'logoBase64': self.logo_base64,
            'theme': self.theme,
            'applyColorMarcaUI': self.apply_color_marca_ui,
            'applyColorMarcaReports': self.apply_color_marca_reports,
            'configured': self.configured,
            'billingType': self.billing_type,
        }


def get_current_company() -> Optional[CompanyContext]:
    cached = _ctx_local.get('company')
    if cached is not None:
        return cached

    company_id = _resolve_company_id_from_session()
    if not company_id:
        _ctx_local['company'] = None
        return None

    company = _load_company(company_id)
    _ctx_local['company'] = company
    return company


def get_current_company_id() -> Optional[str]:
    cid = _resolve_company_id_from_session()
    if cid:
        return cid
    c = get_current_company()
    return c.company_id if c else None


def get_current_owner_uid() -> Optional[str]:
    return _resolve_owner_uid_from_session()


def require_company():
    company = get_current_company()
    if not company:
        from flask import current_app, abort
        current_app.logger.warning('Se requirió contexto de compañía pero no hay selected_company_id en sesión.')
        abort(403, 'No hay una compañía seleccionada.')
    return company


def company_coll(collection_name: str, sandbox: Optional[bool] = None) -> Optional:
    company_id = get_current_company_id()
    if not company_id:
        return None
    if sandbox is None and session:
        sandbox = session.get('is_sandbox_mode', False)
    prefix = 'sandbox_' if sandbox else ''
    return db_firestore.collection('companies').document(company_id).collection(f'{prefix}{collection_name}')


def _load_company(company_id: str) -> Optional[CompanyContext]:
    if not firebase_initialized:
        return None
    data = None
    try:
        doc = db_firestore.collection('companies').document(company_id).get()
        if doc.exists:
            data = doc.to_dict()
    except Exception:
        pass

    if not data:
        try:
            legacy_ref = db_firestore.collection('users').document(company_id)\
                .collection('config').document('profile')
            legacy_doc = legacy_ref.get()
            if legacy_doc.exists:
                legacy_data = legacy_doc.to_dict()
                data = {
                    'id': company_id,
                    'owner_uid': legacy_data.get('ownerUID', company_id),
                    'name': legacy_data.get('companyName', ''),
                    'trade_name': legacy_data.get('tradeName', ''),
                    'rnc': legacy_data.get('companyRNC', ''),
                    'plan_id': legacy_data.get('planId', ''),
                    'plan_version': legacy_data.get('plan_version', 0),
                    'status': legacy_data.get('status', 'active'),
                    'configured': legacy_data.get('configured', False),
                    'country': legacy_data.get('country', 'DO'),
                    'certificate_name': legacy_data.get('certificateName', ''),
                    'certificate_content': legacy_data.get('certificateContent', ''),
                    'certificate_password': legacy_data.get('certificatePassword', ''),
                    'regimen_fiscal': legacy_data.get('regimenFiscal', 'ordinary'),
                    'pos_enabled': legacy_data.get('posEnabled', True),
                    'production_enabled': legacy_data.get('productionEnabled', True),
                    'sandbox_enabled': legacy_data.get('sandboxEnabled', True),
                    'sandbox_indefinite': legacy_data.get('sandboxIndefinite', True),
                    'sandbox_start_date': legacy_data.get('sandboxStartDate', ''),
                    'sandbox_end_date': legacy_data.get('sandboxEndDate', ''),
                    'color_marca': legacy_data.get('colorMarca', '#10b981'),
                    'gradient_enabled': legacy_data.get('gradientEnabled', False),
                    'logo_url': legacy_data.get('logoUrl', ''),
                    'logo_base64': legacy_data.get('logoBase64', ''),
                    'theme': legacy_data.get('theme', 'moderno'),
                    'apply_color_marca_ui': legacy_data.get('applyColorMarcaUI', True),
                    'apply_color_marca_reports': legacy_data.get('applyColorMarcaReports', True),
                    'billing_type': legacy_data.get('billingType', 'Pago por uso'),
                    'modules': legacy_data.get('modules', {}),
                }
        except Exception:
            pass

    if not data:
        return None

    return CompanyContext(
            company_id=data.get('id', company_id),
            owner_uid=data.get('owner_uid', ''),
            name=data.get('name', ''),
            trade_name=data.get('trade_name', ''),
            rnc=data.get('rnc', ''),
            plan_id=data.get('plan_id', ''),
            plan_version=data.get('plan_version', 0),
            status=data.get('status', 'active'),
            configured=data.get('configured', False),
            country=data.get('country', 'DO'),
            certificate_name=data.get('certificate_name', ''),
            certificate_content=data.get('certificate_content', ''),
            certificate_password=data.get('certificate_password', ''),
            regimen_fiscal=data.get('regimen_fiscal', 'ordinary'),
            pos_enabled=data.get('pos_enabled', True),
            production_enabled=data.get('production_enabled', True),
            sandbox_enabled=data.get('sandbox_enabled', True),
            sandbox_indefinite=data.get('sandbox_indefinite', True),
            sandbox_start_date=data.get('sandbox_start_date', ''),
            sandbox_end_date=data.get('sandbox_end_date', ''),
            color_marca=data.get('color_marca', '#10b981'),
            gradient_enabled=data.get('gradient_enabled', False),
            logo_url=data.get('logo_url', ''),
            logo_base64=data.get('logo_base64', ''),
            theme=data.get('theme', 'moderno'),
            apply_color_marca_ui=data.get('apply_color_marca_ui', True),
            apply_color_marca_reports=data.get('apply_color_marca_reports', True),
            billing_type=data.get('billing_type', 'Pago por uso'),
            modules=data.get('modules', {}),
        )
