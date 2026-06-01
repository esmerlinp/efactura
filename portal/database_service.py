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
                        }
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

            return {
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
            }
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
