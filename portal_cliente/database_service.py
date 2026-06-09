# portal_cliente/database_service.py
import os
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime

class DatabaseService:
    _db = None

    @classmethod
    def get_db(cls):
        if cls._db is None:
            if not firebase_admin._apps:
                # Buscar certificado SDK local de Firebase
                cred_path = os.path.join(os.path.dirname(__file__), 'firebase-adminsdk.json')
                # Si no está en portal_cliente, buscar en la carpeta e-FacturaWeb principal
                if not os.path.exists(cred_path):
                    cred_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'firebase-adminsdk.json')
                
                if os.path.exists(cred_path):
                    cred = credentials.Certificate(cred_path)
                    firebase_admin.initialize_app(cred)
                else:
                    firebase_admin.initialize_app()
            cls._db = firestore.client()
        return cls._db

    @classmethod
    def get_client_by_id(cls, owner_uid, client_id, sandbox=True):
        """Busca y retorna la información de un cliente por su ID."""
        db = cls.get_db()
        try:
            coll_name = "sandbox_clients" if sandbox else "clients"
            doc = db.collection('users').document(owner_uid).collection(coll_name).document(client_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                return data
        except Exception as e:
            print(f"Error en get_client_by_id: {e}")
        return None

    @classmethod
    def get_client_invoices(cls, owner_uid, client_id, sandbox=True):
        """Retorna las facturas y cotizaciones de un cliente específico."""
        db = cls.get_db()
        invoices = []
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            docs = db.collection('users').document(owner_uid).collection(coll_name)\
                .where(filter=firestore.FieldFilter('clientId', '==', client_id)).get()
            for doc in docs:
                data = doc.to_dict()
                data['id'] = doc.id
                
                # Evaluar vencimiento de facturas
                status = data.get("status", "Borrador")
                due_date_str = data.get("dueDate")
                if status in ["Emitida", "Parcialmente Cobrada"] and due_date_str:
                    due_date_clean = due_date_str[:10]
                    today_str = datetime.utcnow().strftime("%Y-%m-%d")
                    if due_date_clean < today_str:
                        status = "Vencida"
                data['status'] = status
                
                # Normalizar montos
                data['netPayable'] = float(data.get('netPayable', data.get('total', 0.0)))
                data['remainingBalance'] = float(data.get('remainingBalance', 0.0 if status == 'Cobrada' else data['netPayable']))
                data['total'] = float(data.get('total', data['netPayable']))
                
                invoices.append(data)
            # Ordenar por fecha de emisión descendente
            invoices.sort(key=lambda x: x.get('date', ''), reverse=True)
        except Exception as e:
            print(f"Error en get_client_invoices: {e}")
        return invoices

    @classmethod
    def get_company_profile(cls, owner_uid):
        """Retorna la información y marca de la empresa emisora."""
        db = cls.get_db()
        try:
            doc = db.collection('users').document(owner_uid).collection('config').document('profile').get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"Error en get_company_profile: {e}")
        return {}

    @classmethod
    def get_invoice(cls, owner_uid, invoice_id, sandbox=True):
        db = cls.get_db()
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            doc = db.collection('users').document(owner_uid).collection(coll_name).document(invoice_id).get()
            if doc.exists:
                data = doc.to_dict()
                data['id'] = doc.id
                data['netPayable'] = float(data.get('netPayable', data.get('total', 0.0)))
                status = data.get('status', 'Borrador')
                data['remainingBalance'] = float(data.get('remainingBalance', 0.0 if status == 'Cobrada' else data['netPayable']))
                data['total'] = float(data.get('total', data['netPayable']))
                return data
        except Exception as e:
            print(f"Error en get_invoice: {e}")
        return None

    @classmethod
    def save_invoice(cls, owner_uid, invoice_id, inv_dict, sandbox=True):
        db = cls.get_db()
        try:
            coll_name = "sandbox_invoices" if sandbox else "invoices"
            db.collection('users').document(owner_uid).collection(coll_name).document(invoice_id).set(inv_dict)
            return True
        except Exception as e:
            print(f"Error en save_invoice: {e}")
        return False
