import os
import firebase_admin
from firebase_admin import credentials, firestore


class DatabaseService:
    _db = None

    @classmethod
    def get_db(cls):
        if cls._db is None:
            if not firebase_admin._apps:
                cred_path = os.path.join(os.path.dirname(__file__), 'firebase-adminsdk.json')
                if os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    firebase_admin.initialize_app()  # Fallback for GCP runtime
            cls._db = firestore.client()
        return cls._db

    @classmethod
    def get_all_companies(cls):
        """
        Obtiene todos los usuarios registrados en Firebase Authentication y
        para cada owner (role='owner') lee su perfil de empresa en Firestore
        bajo la ruta: users/{uid}/config/profile.
        """
        db = cls.get_db()
        from firebase_admin import auth
        companies = []

        try:
            # Obtener usuarios directamente de Firebase Authentication para evitar
            # la limitación de Firestore donde los documentos padre virtuales sin campos no se retornan en streams.
            page = auth.list_users()
            while page:
                for user in page.users:
                    owner_uid = user.uid
                    try:
                        # Leer perfil de usuario de Firestore
                        profile_doc = db.collection('users').document(owner_uid)\
                            .collection('config').document('user_profile').get()

                        if not profile_doc.exists:
                            continue

                        profile_data = profile_doc.to_dict()
                        # Solo procesar cuentas de tipo 'owner'
                        role = profile_data.get('role', 'owner')
                        if role != 'owner' and profile_data.get('ownerUID') != owner_uid:
                            continue

                        # Leer perfil de empresa
                        company_doc = db.collection('users').document(owner_uid)\
                            .collection('config').document('profile').get()

                        company_data = {}
                        if company_doc.exists:
                            company_data = company_doc.to_dict()

                        company = {
                            'id': owner_uid,
                            'ownerUID': owner_uid,
                            'razonSocial': company_data.get('companyName', profile_data.get('name', user.display_name or 'Sin nombre')),
                            'rnc': company_data.get('companyRNC', ''),
                            'email': company_data.get('companyEmail', profile_data.get('email', user.email or '')),
                            'phone': company_data.get('companyPhone', ''),
                            'configured': company_data.get('configured', False),
                            'status': company_data.get('status', 'Activo'),
                            'planId': company_data.get('planId', ''),
                            'documentLimit': company_data.get('documentLimit', ''),
                            'storageLimitMB': company_data.get('storageLimitMB', ''),
                            'monthlyPayment': company_data.get('monthlyPayment', 0),
                            'additionalDocumentCost': company_data.get('additionalDocumentCost', 0),
                            'billingDay': company_data.get('billingDay', 1),
                            'posEnabled': bool(company_data.get('posEnabled', True)),
                            'userLimit': company_data.get('userLimit', 2),
                            'additionalUserCost': company_data.get('additionalUserCost', 0.0),
                            'boxLimit': company_data.get('boxLimit', 0),
                            'additionalBoxCost': company_data.get('additionalBoxCost', 0.0),
                            'productionEnabled': bool(company_data.get('productionEnabled', True)),
                            'sandboxEnabled': bool(company_data.get('sandboxEnabled', True)),
                            'sandboxIndefinite': bool(company_data.get('sandboxIndefinite', True)),
                            'sandboxStartDate': company_data.get('sandboxStartDate', ''),
                            'sandboxEndDate': company_data.get('sandboxEndDate', ''),
                        }
                        # Cargar estadísticas de consumo
                        company['stats'] = cls.get_invoice_stats(owner_uid, company['billingDay'])
                        companies.append(company)
                    except Exception as e:
                        print(f"⚠️ Error leyendo perfil de {owner_uid}: {e}")
                        continue
                page = page.get_next_page()

        except Exception as e:
            print(f"❌ Error listando usuarios en get_all_companies: {e}")

        companies.sort(key=lambda c: (c.get('razonSocial') or '').lower())
        return companies

    @classmethod
    def get_company(cls, company_id):
        """Lee el perfil completo de una empresa por ownerUID."""
        db = cls.get_db()
        try:
            profile_doc = db.collection('users').document(company_id)\
                .collection('config').document('user_profile').get()
            company_doc = db.collection('users').document(company_id)\
                .collection('config').document('profile').get()

            if not profile_doc.exists:
                return None

            profile_data = profile_doc.to_dict()
            company_data = company_doc.to_dict() if company_doc.exists else {}

            company_obj = {
                'id': company_id,
                'ownerUID': company_id,
                'razonSocial': company_data.get('companyName', profile_data.get('name', 'Sin nombre')),
                'rnc': company_data.get('companyRNC', ''),
                'email': company_data.get('companyEmail', profile_data.get('email', '')),
                'phone': company_data.get('companyPhone', ''),
                'configured': company_data.get('configured', False),
                'status': company_data.get('status', 'Activo'),
                'planId': company_data.get('planId', ''),
                'documentLimit': company_data.get('documentLimit', ''),
                'storageLimitMB': company_data.get('storageLimitMB', ''),
                'monthlyPayment': company_data.get('monthlyPayment', 0),
                'additionalDocumentCost': company_data.get('additionalDocumentCost', 0),
                'billingDay': company_data.get('billingDay', 1),
                'posEnabled': bool(company_data.get('posEnabled', True)),
                'userLimit': company_data.get('userLimit', 2),
                'additionalUserCost': company_data.get('additionalUserCost', 0.0),
                'boxLimit': company_data.get('boxLimit', 0),
                'additionalBoxCost': company_data.get('additionalBoxCost', 0.0),
                'productionEnabled': bool(company_data.get('productionEnabled', True)),
                'sandboxEnabled': bool(company_data.get('sandboxEnabled', True)),
                'sandboxIndefinite': bool(company_data.get('sandboxIndefinite', True)),
                'sandboxStartDate': company_data.get('sandboxStartDate', ''),
                'sandboxEndDate': company_data.get('sandboxEndDate', ''),
                'companyName': company_data.get('companyName', ''),
                'companyRNC': company_data.get('companyRNC', ''),
                'companyAddress': company_data.get('companyAddress', ''),
                'companyPhone': company_data.get('companyPhone', ''),
                'companyEmail': company_data.get('companyEmail', ''),
                'tradeName': company_data.get('tradeName', ''),
                'province': company_data.get('province', ''),
                'municipality': company_data.get('municipality', ''),
                'certificateName': company_data.get('certificateName', ''),
                'certificateExtension': company_data.get('certificateExtension', ''),
                'certificatePassword': company_data.get('certificatePassword', ''),
            }
            company_obj['stats'] = cls.get_invoice_stats(company_id, company_obj['billingDay'])
            return company_obj
        except Exception as e:
            print(f"❌ Error en get_company({company_id}): {e}")
            return None

    @classmethod
    def update_company(cls, company_id, data):
        """Actualiza campos del perfil de empresa (users/{id}/config/profile)."""
        db = cls.get_db()
        try:
            db.collection('users').document(company_id)\
                .collection('config').document('profile').set(data, merge=True)
        except Exception as e:
            print(f"❌ Error en update_company({company_id}): {e}")

    @classmethod
    def get_all_plans(cls):
        db = cls.get_db()
        docs = db.collection('plans').stream()
        plans = []
        for doc in docs:
            data = doc.to_dict()
            data['id'] = doc.id
            plans.append(data)
        plans.sort(key=lambda p: p.get('monthlyPrice', 0))
        return plans

    @classmethod
    def save_plan(cls, plan_id, data):
        db = cls.get_db()
        db.collection('plans').document(plan_id).set(data)

    @classmethod
    def delete_plan(cls, plan_id):
        db = cls.get_db()
        db.collection('plans').document(plan_id).delete()

    @classmethod
    def record_payment(cls, company_id, amount, method, reference):
        """Registra un pago manual para una empresa y actualiza su status a 'Activo'."""
        db = cls.get_db()
        try:
            import datetime
            payment_ref = db.collection('users').document(company_id)\
                .collection('payments').document()
            payment_data = {
                'id': payment_ref.id,
                'amount': amount,
                'method': method,
                'reference': reference,
                'date': datetime.datetime.utcnow(),
                'type': 'Manual'
            }
            payment_ref.set(payment_data)

            # Actualizar estado de la empresa a 'Activo'
            db.collection('users').document(company_id)\
                .collection('config').document('profile').set({
                    'status': 'Activo'
                }, merge=True)
            return True
        except Exception as e:
            print(f"❌ Error en record_payment({company_id}): {e}")
            return False

    @classmethod
    def get_payments(cls, company_id):
        """Retorna el historial de pagos de una empresa."""
        db = cls.get_db()
        try:
            docs = db.collection('users').document(company_id)\
                .collection('payments').order_by('date', direction=firestore.Query.DESCENDING).stream()
            payments = []
            for doc in docs:
                data = doc.to_dict()
                payments.append(data)
            return payments
        except Exception as e:
            print(f"❌ Error en get_payments({company_id}): {e}")
            return []

    @classmethod
    def get_invoice_stats(cls, owner_uid, billing_day=1):
        """
        Calcula estadísticas de facturas emitidas en producción y sandbox para el ciclo actual.
        """
        db = cls.get_db()
        import datetime
        
        stats = {
            'prod_total': 0,
            'prod_current_cycle': 0,
            'sandbox_total': 0,
            'sandbox_current_cycle': 0,
            'current_cycle_start': None,
            'current_cycle_end': None
        }
        
        now = datetime.datetime.now()
        try:
            billing_day = int(billing_day) if billing_day else 1
            if billing_day < 1 or billing_day > 28:
                billing_day = 1
        except Exception:
            billing_day = 1
            
        # Rango del ciclo de facturación
        if now.day >= billing_day:
            start_date = datetime.datetime(now.year, now.month, billing_day, 0, 0, 0)
            if now.month == 12:
                end_date = datetime.datetime(now.year + 1, 1, billing_day, 23, 59, 59)
            else:
                end_date = datetime.datetime(now.year, now.month + 1, billing_day, 23, 59, 59)
        else:
            if now.month == 1:
                start_date = datetime.datetime(now.year - 1, 12, billing_day, 0, 0, 0)
            else:
                start_date = datetime.datetime(now.year, now.month - 1, billing_day, 0, 0, 0)
            end_date = datetime.datetime(now.year, now.month, billing_day, 23, 59, 59)
            
        stats['current_cycle_start'] = start_date.strftime('%Y-%m-%d')
        stats['current_cycle_end'] = end_date.strftime('%Y-%m-%d')
        
        def parse_date(date_val):
            if not date_val:
                return None
            if hasattr(date_val, 'year'):
                return date_val
            if isinstance(date_val, str):
                try:
                    return datetime.datetime.fromisoformat(date_val.split('Z')[0].split('+')[0])
                except Exception:
                    try:
                        return datetime.datetime.strptime(date_val[:10], '%Y-%m-%d')
                    except Exception:
                        pass
            return None

        # Contar facturas de producción (excluyendo cotizaciones y borradores)
        try:
            prod_docs = db.collection('users').document(owner_uid).collection('invoices')\
                .where(filter=firestore.FieldFilter('isQuotation', '==', False)).stream()
            for doc in prod_docs:
                data = doc.to_dict()
                if data.get('status') == 'Borrador':
                    continue
                stats['prod_total'] += 1
                doc_date = parse_date(data.get('date') or data.get('createdAt'))
                if doc_date and start_date <= doc_date <= end_date:
                    stats['prod_current_cycle'] += 1
        except Exception as e:
            print(f"⚠️ Error counting prod invoices for {owner_uid}: {e}")
            
        # Contar facturas de sandbox (excluyendo cotizaciones y borradores)
        try:
            sandbox_docs = db.collection('users').document(owner_uid).collection('sandbox_invoices')\
                .where(filter=firestore.FieldFilter('isQuotation', '==', False)).stream()
            for doc in sandbox_docs:
                data = doc.to_dict()
                if data.get('status') == 'Borrador':
                    continue
                stats['sandbox_total'] += 1
                doc_date = parse_date(data.get('date') or data.get('createdAt'))
                if doc_date and start_date <= doc_date <= end_date:
                    stats['sandbox_current_cycle'] += 1
        except Exception as e:
            print(f"⚠️ Error counting sandbox invoices for {owner_uid}: {e}")
            
        return stats

    @classmethod
    def create_company(cls, email, password, name, plan_id, pos_enabled):
        """Registra un nuevo usuario owner en Firebase Auth y crea sus perfiles en Firestore."""
        db = cls.get_db()
        from firebase_admin import auth
        import datetime

        try:
            # 1. Registrar usuario en Firebase Auth
            user_record = auth.create_user(
                email=email,
                password=password,
                display_name=name
            )
            uid = user_record.uid

            # 2. Cargar límites por defecto del plan
            plan_data = {}
            if plan_id:
                try:
                    plan_doc = db.collection('plans').document(plan_id).get()
                    if plan_doc.exists:
                        plan_data = plan_doc.to_dict()
                except Exception as e:
                    print(f"⚠️ Error cargando plan {plan_id}: {e}")

            # 3. Crear user_profile en Firestore
            user_profile_data = {
                "uid": uid,
                "ownerUID": uid,
                "role": "owner",
                "name": name,
                "email": email,
                "phone": "",
                "address": "",
                "permissions": {
                    "canInvoice": True,
                    "canExpenses": True,
                    "canClients": True,
                    "canModifySettings": True,
                    "canManageInventory": True,
                    "canManagePOS": True,
                    "canViewDashboard": True,
                    "canManageCXC": True,
                    "canManageCXP": True,
                    "canManageContracts": True,
                    "canManageCommissions": True,
                    "canViewBI": True,
                    "canViewAuditLog": False
                },
                "createdAt": datetime.datetime.utcnow().isoformat()
            }
            db.collection('users').document(uid).collection('config').document('user_profile').set(user_profile_data)

            # 4. Crear profile de la empresa en Firestore
            company_profile_data = {
                "ownerUID": uid,
                "companyName": "Mi Empresa",
                "tradeName": "Mi Empresa",
                "companyRNC": "",
                "companyType": "associated",
                "companyAddress": "",
                "province": "",
                "municipality": "",
                "companyPhone": "",
                "companyEmail": email,
                "colorMarca": "#10b981",
                "gradientEnabled": True,
                "logoUrl": "",
                "logoBase64": "",
                "regimenFiscal": "General",
                "status": "Activo",
                "planId": plan_id,
                "documentLimit": plan_data.get('documentLimit', 100),
                "storageLimitMB": plan_data.get('storageLimitMB', 512),
                "monthlyPayment": plan_data.get('monthlyPrice', 0.0),
                "additionalDocumentCost": plan_data.get('additionalDocumentCost', 0.0),
                "userLimit": plan_data.get('userLimit', 2),
                "additionalUserCost": plan_data.get('additionalUserCost', 0.0),
                "boxLimit": plan_data.get('boxLimit', 0),
                "additionalBoxCost": plan_data.get('additionalBoxCost', 0.0),
                "billingDay": 1,
                "posEnabled": pos_enabled,
                "configured": False
            }
            db.collection('users').document(uid).collection('config').document('profile').set(company_profile_data)

            return True, uid
        except Exception as e:
            print(f"❌ Error en create_company: {e}")
            return False, str(e)
