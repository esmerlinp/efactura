from datetime import datetime, timedelta
import uuid
import random
from app.services.db_service import DatabaseService

class RecurrenceService:
    @staticmethod
    def calculate_next_date(current_date_str, interval):
        """Calcula la próxima fecha de recurrencia basándose en el intervalo."""
        if not current_date_str:
            return datetime.utcnow().strftime("%Y-%m-%d")
            
        try:
            current_date = datetime.strptime(current_date_str[:10], "%Y-%m-%d")
        except ValueError:
            current_date = datetime.utcnow()

        if interval == "semanal":
            next_date = current_date + timedelta(days=7)
        elif interval == "quincenal":
            next_date = current_date + timedelta(days=15)
        elif interval == "mensual":
            # Sumar un mes de forma simple (30 días) o exacta
            # Para simplificar de forma robusta, sumamos 30 días
            next_date = current_date + timedelta(days=30)
        else:
            next_date = current_date + timedelta(days=30)
            
        return next_date.strftime("%Y-%m-%d")

    @classmethod
    def process_pending_recurrences(cls, owner_uid, sandbox=True):
        """
        Escanea y procesa todas las facturas y gastos recurrentes programados del owner
        cuya fecha de siguiente ocurrencia haya vencido (es decir, sea menor o igual a hoy).
        Duplica los registros correspondientes y actualiza la programación original.
        """
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        processed_count = 0

        # =====================================================================
        # 1. PROCESAR FACTURAS RECURRENTES
        # =====================================================================
        invoices = DatabaseService.get_invoices(owner_uid, sandbox=sandbox)
        recurring_invoices = [inv for inv in invoices if inv.get("isRecurring") and inv.get("nextOccurrenceDate")]

        for original in recurring_invoices:
            next_date_str = original["nextOccurrenceDate"][:10]
            if next_date_str <= today_str:
                # La recurrencia ha vencido, generamos un duplicado
                print(f"🔄 Procesando factura recurrente para: {original['clientName']} programada para {next_date_str}")
                
                # Generar número de factura/cotización nuevo aleatorio
                random_num = f"{random.randint(1, 999999):06d}"
                is_quotation = original.get("isQuotation", False)
                new_number = f"COT-{random_num}" if is_quotation else f"FAC-{random_num}"
                
                # Calcular plazos
                orig_date = datetime.strptime(original["date"][:10], "%Y-%m-%d")
                orig_due = datetime.strptime(original["dueDate"][:10], "%Y-%m-%d")
                days_offset = (orig_due - orig_date).days
                
                occurrence_date = datetime.strptime(next_date_str, "%Y-%m-%d")
                new_due_date = occurrence_date + timedelta(days=days_offset)
                
                new_id = str(uuid.uuid4())
                
                # Duplicar partidas
                duplicated_items = []
                for item in original.get("items", []):
                    duplicated_items.append({
                        "id": str(uuid.uuid4()),
                        "code": item.get("code", ""),
                        "type": item.get("type", "Bien"),
                        "name": item["name"],
                        "price": item["price"],
                        "quantity": item["quantity"],
                        "itbisRate": item.get("itbisRate", 0.18),
                        "discountRate": item.get("discountRate", 0.0),
                        "subtotal": item["subtotal"],
                        "itbis_amount": item["itbisAmount"],
                        "total": item["total"]
                    })

                new_invoice = {
                    "id": new_id,
                    "invoiceNumber": new_number,
                    "date": occurrence_date.strftime("%Y-%m-%d"),
                    "dueDate": new_due_date.strftime("%Y-%m-%d"),
                    "clientId": original.get("clientId"),
                    "clientName": original.get("clientName"),
                    "clientRNC": original.get("clientRNC"),
                    "status": "Emitida" if not is_quotation else "Borrador",
                    "ecfType": original.get("ecfType", "Factura de Consumo (E32)"),
                    "encf": f"{original.get('ecfType', 'E32')[:3]}PENDIENTE" if not is_quotation else "",
                    "xmlSignature": "",
                    "qrCodeURL": "",
                    "isSyncedWithDGII": False,
                    "creditedAmount": 0.0,
                    "retainedISR": original.get("retainedISR", 0.0),
                    "retainedITBIS": original.get("retainedITBIS", 0.0),
                    "netPayable": original["netPayable"],
                    "subtotal": original["subtotal"],
                    "totalITBIS": original["totalITBIS"],
                    "total": original["total"],
                    "isQuotation": is_quotation,
                    "isConvertedToInvoice": False,
                    "notes": original.get("notes", ""),
                    "comentario": original.get("comentario", ""),
                    "isRecurring": False, # Las copias generadas no son programadoras principales
                    "recurrenceInterval": "mensual",
                    "nextOccurrenceDate": None,
                    "firebasePDFURL": "",
                    "firebaseXMLURL": "",
                    "currency": original.get("currency", "DOP"),
                    "paymentType": original.get("paymentType", "Contado"),
                    "paymentMethod": original.get("paymentMethod", "Efectivo"),
                    "incomeType": original.get("incomeType", "01 - Ingresos por operaciones"),
                    "customFields": original.get("customFields", []),
                    "exchangeRate": original.get("exchangeRate", 1.0),
                    "items": duplicated_items
                }
                
                # Guardar la nueva factura
                DatabaseService.save_invoice(owner_uid, new_id, new_invoice, sandbox=sandbox)
                
                # Calcular la próxima ocurrencia en la factura original y actualizarla
                next_occurrence = cls.calculate_next_date(next_date_str, original["recurrenceInterval"])
                original["nextOccurrenceDate"] = next_occurrence
                
                # Re-guardar la original con la nueva fecha programada
                DatabaseService.save_invoice(owner_uid, original["id"], original, sandbox=sandbox)
                processed_count += 1

        # =====================================================================
        # 2. PROCESAR GASTOS RECURRENTES
        # =====================================================================
        expenses = DatabaseService.get_expenses(owner_uid, sandbox=sandbox)
        recurring_expenses = [exp for exp in expenses if exp.get("isRecurring") and exp.get("nextOccurrenceDate")]

        for original in recurring_expenses:
            next_date_str = original["nextOccurrenceDate"][:10]
            if next_date_str <= today_str:
                # Verificar fecha límite/finalización
                end_date = original.get("recurrenceEndDate")
                if end_date and next_date_str > end_date[:10]:
                    print(f"🚫 Recurrencia de gasto {original['concept']} finalizada por fecha límite: {end_date}")
                    original["isRecurring"] = False
                    original["nextOccurrenceDate"] = None
                    DatabaseService.save_expense(owner_uid, original["id"], original, sandbox=sandbox)
                    continue

                print(f"🔄 Procesando gasto recurrente: {original['concept']} programado para {next_date_str}")
                
                new_id = str(uuid.uuid4())
                
                # Por solicitud del usuario: Todos los gastos recurrentes deben crearse como No Pagados (Crédito/Pendiente)
                # para obligar al usuario a marcarlos manualmente.
                payment_type = "Crédito"
                cxp_status = "Pendiente"
                
                orig_date_str = original.get("date", "")[:10]
                orig_due_str = original.get("dueDate", "")[:10]
                due_date = next_date_str
                if orig_date_str and orig_due_str:
                    try:
                        orig_date = datetime.strptime(orig_date_str, "%Y-%m-%d")
                        orig_due = datetime.strptime(orig_due_str, "%Y-%m-%d")
                        days_offset = (orig_due - orig_date).days
                        occurrence_date = datetime.strptime(next_date_str, "%Y-%m-%d")
                        due_date = (occurrence_date + timedelta(days=days_offset)).strftime("%Y-%m-%d")
                    except Exception:
                        pass

                new_expense = {
                    "id": new_id,
                    "concept": original["concept"],
                    "category": original["category"],
                    "amount": original["amount"],
                    "date": next_date_str,
                    "rncEmisor": original.get("rncEmisor", ""),
                    "ncf": original.get("ncf", ""),
                    "isMinorExpense": original.get("isMinorExpense", False),
                    "isSyncedWithDGII": False,
                    "qrCodeURL": "",
                    "xmlSignature": "",
                    "notes": original.get("notes", ""),
                    "isRecurring": False, # Las copias generadas no son programadoras
                    "recurrenceInterval": "mensual",
                    "nextOccurrenceDate": None,
                    "associatedInvoiceId": original.get("associatedInvoiceId", ""),
                    "itbisAmount": original.get("itbisAmount", 0.0),
                    "isITBISDeductible": original.get("isITBISDeductible", True),
                    "isDeductible": original.get("isDeductible", True),
                    "firebaseAttachmentURLs": [],
                    # Campos de e-CF y CxP copiados:
                    "ecfType": original.get("ecfType", "E31"),
                    "ecfNumber": original.get("ecfNumber", ""),
                    "cne": original.get("cne", ""),
                    "tipoGastoDGII": original.get("tipoGastoDGII", "02"),
                    "paymentType": payment_type,
                    "cxpStatus": cxp_status,
                    "cxpRemainingBalance": 0.0 if payment_type == 'Contado' else original["amount"],
                    "approvalStatus": original.get("approvalStatus", "Aprobado"),
                    "requestedBy": original.get("requestedBy", "Sistema"),
                    "approvedBy": original.get("approvedBy", "Sistema") if original.get("approvalStatus", "Aprobado") == "Aprobado" else "",
                    "dueDate": due_date
                }
                
                # Guardar el nuevo gasto
                DatabaseService.save_expense(owner_uid, new_id, new_expense, sandbox=sandbox)
                
                # Calcular la próxima ocurrencia en el gasto original y actualizarlo
                next_occurrence = cls.calculate_next_date(next_date_str, original["recurrenceInterval"])
                if end_date and next_occurrence > end_date[:10]:
                    original["isRecurring"] = False
                    original["nextOccurrenceDate"] = None
                else:
                    original["nextOccurrenceDate"] = next_occurrence
                
                # Re-guardar el original con la nueva fecha programada
                DatabaseService.save_expense(owner_uid, original["id"], original, sandbox=sandbox)
                processed_count += 1

        return processed_count
