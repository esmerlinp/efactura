import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session

web_bank_entities_bp = Blueprint('web_bank_entities', __name__)

BPD_SERVICE_TYPES = [
    {"value": "01", "label": "01 - Nomina automatica"},
    {"value": "02", "label": "02 - Pago a suplidores"},
    {"value": "03", "label": "03 - Cobros automaticos"},
    {"value": "04", "label": "04 - Pago de prestamos"},
    {"value": "05", "label": "05 - Pago de tarjetas"},
    {"value": "06", "label": "06 - Transferencia a cuenta"},
]

DEFAULT_BANKS = [
    {"name": "Banco Popular Dominicano", "bpd_code": "10101070", "digi_ver": "8"},
    {"name": "Banco de Reservas", "bpd_code": "10101010", "digi_ver": "6"},
    {"name": "Banco BHD Leon", "bpd_code": "10101230", "digi_ver": "8"},
    {"name": "Banco del Progreso", "bpd_code": "10101110", "digi_ver": "0"},
    {"name": "Banco Santa Cruz", "bpd_code": "4123123", "digi_ver": "4"},
    {"name": "Banco Caribe", "bpd_code": "10101350", "digi_ver": "0"},
    {"name": "Banco Scotiabank", "bpd_code": "10101030", "digi_ver": "0"},
    {"name": "Banco Lopez de Haro", "bpd_code": "10101390", "digi_ver": "0"},
    {"name": "Banco BDI", "bpd_code": "10101360", "digi_ver": "0"},
    {"name": "Banco Vimenca", "bpd_code": "10101380", "digi_ver": "0"},
    {"name": "Citibank", "bpd_code": "10101060", "digi_ver": "0"},
    {"name": "Asociacion Popular", "bpd_code": "47940900", "digi_ver": "0"},
    {"name": "Asociacion Cibao", "bpd_code": "48991200", "digi_ver": "0"},
    {"name": "Banco Promerica", "bpd_code": "44405900", "digi_ver": "0"},
    {"name": "Banesco Banco Multiple", "bpd_code": "11102328", "digi_ver": "0"},
    {"name": "Banco ADEMI", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco La Nacional", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Union", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco JMMB", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Fihogar", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Cariberia", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Associados", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Activo Dominicana", "bpd_code": "", "digi_ver": "0"},
    {"name": "Banco Bell Bank", "bpd_code": "", "digi_ver": "0"},
]


def _get_context():
    from app.services.db_service import DatabaseService
    uid = session.get("selected_owner_uid", "") or session.get("user", {}).get("ownerUID", "")
    sandbox = session.get("is_sandbox_mode", True)
    company_id = session.get("selected_company_id")
    return DatabaseService, uid, sandbox, company_id


def _seed_default_banks(db, uid, sandbox, company_id):
    existing = db.get_bank_entities(uid, sandbox=sandbox, company_id=company_id)
    existing_map = {e["name"].strip().lower(): e for e in existing}
    for bank in DEFAULT_BANKS:
        key = bank["name"].strip().lower()
        if key in existing_map:
            ent = existing_map[key]
            if (ent.get("bpd_code") != bank["bpd_code"] or ent.get("digi_ver") != bank["digi_ver"]):
                entity_dict = {
                    "name": bank["name"],
                    "bpd_code": bank["bpd_code"],
                    "digi_ver": bank["digi_ver"],
                    "contract_code": ent.get("contract_code", ""),
                    "bpd_service_type": ent.get("bpd_service_type", "01"),
                    "active": ent.get("active", True),
                    "createdAt": ent.get("createdAt", ""),
                }
                db.save_bank_entity(uid, ent["id"], entity_dict, sandbox=sandbox, company_id=company_id)
        else:
            entity_id = str(uuid.uuid4())
            entity_dict = {
                "name": bank["name"],
                "bpd_code": bank["bpd_code"],
                "digi_ver": bank["digi_ver"],
                "contract_code": "",
                "bpd_service_type": "01",
                "active": True,
            }
            db.save_bank_entity(uid, entity_id, entity_dict, sandbox=sandbox, company_id=company_id)


@web_bank_entities_bp.route('/banks/entities')
def list_bank_entities():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    db, uid, sandbox, company_id = _get_context()
    _seed_default_banks(db, uid, sandbox, company_id)
    entities = db.get_bank_entities(uid, sandbox=sandbox, company_id=company_id)
    return render_template('bank_entities/list.html', active_page='bank_entities',
                           entities=entities, service_types=BPD_SERVICE_TYPES)


@web_bank_entities_bp.route('/banks/entities/new', methods=['GET', 'POST'])
def new_bank_entity():
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    db, uid, sandbox, company_id = _get_context()

    if request.method == 'POST':
        entity_id = str(uuid.uuid4())
        entity_dict = {
            "name": request.form.get("name", "").strip(),
            "bpd_code": request.form.get("bpd_code", "").strip(),
            "digi_ver": request.form.get("digi_ver", "0").strip(),
            "contract_code": request.form.get("contract_code", "").strip(),
            "bpd_service_type": request.form.get("bpd_service_type", "01").strip(),
            "active": request.form.get("active", "1") == "1",
        }
        if not entity_dict["name"]:
            flash("El nombre de la entidad bancaria es obligatorio.", "error")
            return render_template('bank_entities/form.html', active_page='bank_entities',
                                   entity=None, service_types=BPD_SERVICE_TYPES)
        db.save_bank_entity(uid, entity_id, entity_dict, sandbox=sandbox, company_id=company_id)
        flash("Entidad bancaria registrada exitosamente.", "success")
        return redirect(url_for('web_bank_entities.list_bank_entities'))

    return render_template('bank_entities/form.html', active_page='bank_entities',
                           entity=None, service_types=BPD_SERVICE_TYPES)


@web_bank_entities_bp.route('/banks/entities/<entity_id>/edit', methods=['GET', 'POST'])
def edit_bank_entity(entity_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    db, uid, sandbox, company_id = _get_context()

    entity = db.get_bank_entity(uid, entity_id, sandbox=sandbox, company_id=company_id)
    if not entity:
        flash("Entidad bancaria no encontrada.", "error")
        return redirect(url_for('web_bank_entities.list_bank_entities'))

    if request.method == 'POST':
        entity_dict = {
            "name": request.form.get("name", "").strip(),
            "bpd_code": request.form.get("bpd_code", "").strip(),
            "digi_ver": request.form.get("digi_ver", "0").strip(),
            "contract_code": request.form.get("contract_code", "").strip(),
            "bpd_service_type": request.form.get("bpd_service_type", "01").strip(),
            "active": request.form.get("active", "1") == "1",
        }
        if not entity_dict["name"]:
            flash("El nombre de la entidad bancaria es obligatorio.", "error")
            return render_template('bank_entities/form.html', active_page='bank_entities',
                                   entity=entity, service_types=BPD_SERVICE_TYPES)
        entity_dict["createdAt"] = entity.get("createdAt", "")
        db.save_bank_entity(uid, entity_id, entity_dict, sandbox=sandbox, company_id=company_id)
        flash("Entidad bancaria actualizada exitosamente.", "success")
        return redirect(url_for('web_bank_entities.list_bank_entities'))

    return render_template('bank_entities/form.html', active_page='bank_entities',
                           entity=entity, service_types=BPD_SERVICE_TYPES)


@web_bank_entities_bp.route('/banks/entities/<entity_id>/delete', methods=['POST'])
def delete_bank_entity(entity_id):
    if 'user' not in session:
        return redirect(url_for('web_auth.login'))
    db, uid, sandbox, company_id = _get_context()
    entity = db.get_bank_entity(uid, entity_id, sandbox=sandbox, company_id=company_id)
    if entity:
        db.delete_bank_entity(uid, entity_id, sandbox=sandbox, company_id=company_id)
        flash(f"Entidad '{entity.get('name', '')}' eliminada.", "success")
    else:
        flash("Entidad no encontrada.", "error")
    return redirect(url_for('web_bank_entities.list_bank_entities'))
