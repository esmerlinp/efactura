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
            next_date = current_date + timedelta(days=30)
        elif interval == "trimestral":
            next_date = current_date + timedelta(days=90)
        elif interval == "semestral":
            next_date = current_date + timedelta(days=180)
        elif interval == "anual":
            next_date = current_date + timedelta(days=365)
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

    # =========================================================================
    # CONTRATOS RECURRENTES — Facturación automática (APScheduler)
    # =========================================================================

    @classmethod
    def _build_invoice_from_contract(cls, owner_uid, contract, sandbox=True):
        """
        Construye y guarda una factura a partir de un contrato recurrente.
        Soporta contratos multi-línea (contractLines) y de ítem único (Fase 1).
        Retorna el invoice_id generado o None si falla.
        """
        import uuid
        import random
        from datetime import datetime, timedelta
        from app.services.db_service import DatabaseService

        try:
            random_num    = f"{random.randint(1, 999999):06d}"
            invoice_id    = str(uuid.uuid4())
            invoice_number = f"FAC-{random_num}"
            today_str     = datetime.utcnow().strftime("%Y-%m-%d")
            due_date_str  = (datetime.utcnow() + timedelta(days=30)).strftime("%Y-%m-%d")

            contract_lines = contract.get("contractLines", [])

            if contract_lines:
                # ── Multi-línea (Fase 2+) ────────────────────────────────────
                items         = []
                subtotal      = 0.0
                itbis_amount  = 0.0
                total_invoice = 0.0
                for line in contract_lines:
                    qty        = float(line.get("quantity", 1))
                    unit_price = float(line.get("unitPrice", 0))
                    itbis_rate = float(line.get("itbisRate", 0.18))
                    line_sub   = round(qty * unit_price, 2)
                    line_itbis = round(line_sub * itbis_rate, 2)
                    line_total = round(line_sub + line_itbis, 2)
                    items.append({
                        "id":           str(uuid.uuid4()),
                        "code":         line.get("code", "SERV-REC"),
                        "type":         line.get("type", "Servicio"),
                        "name":         f"{line.get('name', 'Servicio')} — {contract.get('contractNumber', '')}",
                        "price":        unit_price,
                        "quantity":     qty,
                        "itbisRate":    itbis_rate,
                        "discountRate": 0.0,
                        "subtotal":     line_sub,
                        "itbis_amount": line_itbis,
                        "total":        line_total,
                    })
                    subtotal      += line_sub
                    itbis_amount  += line_itbis
                    total_invoice += line_total
            else:
                # ── Ítem único (Fase 1 — compatibilidad) ─────────────────────
                contract_item_id = contract.get("itemId")
                selected_item    = None
                if contract_item_id:
                    all_items     = DatabaseService.get_items(owner_uid, sandbox=sandbox)
                    selected_item = next(
                        (it for it in all_items if it["id"] == contract_item_id), None
                    )
                itbis_rate    = selected_item.get("itbisRate", 0.18) if selected_item else 0.18
                total_invoice = float(contract.get("amount", 0))
                subtotal      = round(total_invoice / (1 + itbis_rate), 2)
                itbis_amount  = round(total_invoice - subtotal, 2)
                item_name     = (
                    selected_item.get("name", "Servicio Contratado")
                    if selected_item else "Servicio Contratado"
                )
                item_code     = selected_item.get("code", "SERV-REC") if selected_item else "SERV-REC"
                item_type     = selected_item.get("type", "Servicio") if selected_item else "Servicio"
                items = [{
                    "id":           str(uuid.uuid4()),
                    "code":         item_code,
                    "type":         item_type,
                    "name":         f"{item_name} ({contract.get('contractNumber', '')})",
                    "price":        subtotal,
                    "quantity":     1,
                    "itbisRate":    itbis_rate,
                    "discountRate": 0.0,
                    "subtotal":     subtotal,
                    "itbis_amount": itbis_amount,
                    "total":        total_invoice,
                }]

            invoice_dict = {
                "id":                invoice_id,
                "invoiceNumber":     invoice_number,
                "date":              today_str,
                "dueDate":           due_date_str,
                "clientId":          contract.get("clientId", ""),
                "clientName":        contract.get("clientName", ""),
                "clientRNC":         contract.get("clientRNC", ""),
                "status":            "Emitida",
                "ecfType":           "Factura de Consumo (E32)",
                "encf":              "E32PENDIENTE",
                "xmlSignature":      "",
                "qrCodeURL":         "",
                "isSyncedWithDGII":  False,
                "creditedAmount":    0.0,
                "retainedISR":       0.0,
                "retainedITBIS":     0.0,
                "netPayable":        round(total_invoice, 2),
                "subtotal":          round(subtotal, 2),
                "totalITBIS":        round(itbis_amount, 2),
                "total":             round(total_invoice, 2),
                "isQuotation":       False,
                "isConvertedToInvoice": False,
                "notes":             f"Generado automáticamente desde Contrato {contract.get('contractNumber', '')}",
                "comentario":        contract.get("notes", ""),
                "isRecurring":       False,
                "firebasePDFURL":    "",
                "firebaseXMLURL":    "",
                "currency":          "DOP",
                "paymentType":       "Contado",
                "paymentMethod":     "Efectivo",
                "incomeType":        "01 - Ingresos por operaciones",
                "exchangeRate":      1.0,
                "registeredBy":      "Sistema (APScheduler)",
                "contractId":        contract.get("id", ""),
                "contractNumber":    contract.get("contractNumber", ""),
                "items":             items,
            }

            DatabaseService.save_invoice(owner_uid, invoice_id, invoice_dict, sandbox=sandbox)
            return invoice_id

        except Exception as exc:
            print(f"❌ Error generando factura para contrato {contract.get('contractNumber')}: {exc}")
            return None

    @classmethod
    def _send_contract_invoice_email_bg(cls, app_instance, owner_uid, invoice_id, sandbox=True):
        """
        Envía por email la factura generada desde un contrato, en un hilo separado.
        Requiere la instancia Flask para crear el contexto de aplicación.
        """
        import threading
        from app.services.db_service import DatabaseService

        def _send(app, o_uid, inv_id, sb):
            with app.app_context():
                try:
                    invoice = DatabaseService.get_invoice(o_uid, inv_id, sandbox=sb)
                    if not invoice:
                        return
                    client = DatabaseService.get_client(o_uid, invoice.get("clientId", ""), sandbox=sb)
                    if not client:
                        return
                    recipient = (client.get("email") or "").strip()
                    if not recipient:
                        return
                    from app.web.invoices import send_invoice_email
                    ok, msg = send_invoice_email(o_uid, invoice, recipient, sandbox=sb)
                    status = "✅" if ok else "⚠️"
                    print(f"{status} Email contrato [{inv_id}] → {recipient}: {msg}")
                except Exception as exc:
                    print(f"❌ Error enviando email del contrato {inv_id}: {exc}")

        t = threading.Thread(
            target=_send,
            args=(app_instance, owner_uid, invoice_id, sandbox),
            daemon=True,
        )
        t.start()

    @classmethod
    def process_pending_contracts(cls, owner_uid, sandbox=True, app_instance=None):
        """
        Recorre todos los contratos Activos del owner cuya nextBillingDate <= hoy
        y genera las facturas automáticamente.

        Args:
            owner_uid:    UID del propietario de la empresa.
            sandbox:      True si es entorno sandbox, False si es producción.
            app_instance: Instancia Flask (necesaria para envío de email en hilo).
                          Si es None, el envío de email se omite.

        Returns:
            int: Número de contratos facturados exitosamente.
        """
        from app.services.db_service import DatabaseService
        from datetime import datetime

        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        processed_count = 0

        contracts = DatabaseService.get_contracts(owner_uid, sandbox=sandbox)
        pending = [
            c for c in contracts
            if c.get("status") == "Activo"
            and (c.get("nextBillingDate") or "")[:10] <= today_str
        ]

        for contract in pending:
            try:
                contract_id = contract["id"]

                # ── 0. Verificar si se solicitó la cancelación (no renovación) ──
                if contract.get("cancelRequest") is True:
                    contract["status"] = "Cancelado"
                    contract["nextBillingDate"] = None
                    DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
                    print(f"⏹️ Contrato {contract.get('contractNumber')} cancelado definitivamente por solicitud del cliente (cancelRequest).")
                    continue

                # ── 1. Verificar expiración por endDate ───────────────────────
                end_date     = (contract.get("endDate") or "")[:10]
                next_billing = (contract.get("nextBillingDate") or "")[:10]

                if end_date and next_billing > end_date:
                    if contract.get("autoRenew"):
                        new_end = cls.calculate_next_date(
                            end_date, contract.get("frequency") or contract.get("recurrenceInterval", "mensual")
                        )
                        contract["endDate"] = new_end
                        print(f"🔄 Contrato {contract.get('contractNumber')} renovado automáticamente hasta {new_end}")
                    else:
                        contract["status"] = "Expirado"
                        DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)
                        print(f"⏹️ Contrato {contract.get('contractNumber')} marcado como Expirado")
                        continue

                # ── 2. Generar factura ────────────────────────────────────────
                invoice_id = cls._build_invoice_from_contract(owner_uid, contract, sandbox=sandbox)
                if not invoice_id:
                    continue

                # ── 3. Reprogramar nextBillingDate ────────────────────────────
                freq = contract.get("frequency") or contract.get("recurrenceInterval", "mensual")
                new_billing = cls.calculate_next_date(next_billing, freq)

                # ── 4. Verificar si la PRÓXIMA fecha supera endDate ───────────
                if end_date and new_billing > end_date:
                    if contract.get("autoRenew"):
                        new_end = cls.calculate_next_date(end_date, freq)
                        contract["endDate"] = new_end
                        print(f"🔄 Contrato {contract.get('contractNumber')} renovado hasta {new_end}")
                    else:
                        contract["status"] = "Expirado"
                        print(f"⏹️ Contrato {contract.get('contractNumber')} expirará tras esta factura")

                contract["nextBillingDate"] = new_billing
                DatabaseService.save_contract(owner_uid, contract_id, contract, sandbox=sandbox)

                print(f"✅ Factura {invoice_id} generada para contrato {contract.get('contractNumber')} — próxima: {new_billing}")

                # ── 5. Enviar email si está configurado ───────────────────────
                if contract.get("autoSendEmail") and app_instance:
                    cls._send_contract_invoice_email_bg(app_instance, owner_uid, invoice_id, sandbox=sandbox)

                processed_count += 1

            except Exception as exc:
                print(f"❌ Error procesando contrato {contract.get('contractNumber', contract.get('id'))}: {exc}")

        return processed_count

