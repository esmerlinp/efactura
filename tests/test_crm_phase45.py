"""
Pruebas de Fase 4 (F4.3 Métricas Comerciales + F4.5 Snapshots Históricos + F4.4 Lead Scoring Explicable).

Cubre 30 escenarios de validación:
Métricas comerciales:
  1. Pipeline nominal (excluye ganada, perdida, soft-deleted)
  2. Pipeline ponderado (probabilidad 0-100, manejo de None y valores extremos)
  3. Win Rate (won / (won + lost))
  4. División por cero segura (win rate = 0 si won+lost == 0)
  5. Embudo de conversión (funnel de etapas)
  6. Conversión por etapa (prospect_to_contacted, etc. con denominador correcto)
  7. Ciclo promedio de venta (días reales creación -> Ganada)
  8. Ticket promedio (average won amount sobre ganadas)
  9. Filtro de métricas por branch
  10. Filtro de métricas por project
  11. Filtro de métricas por responsable (vendedor)
  12. Aislamiento multi-tenant de métricas

Stage History:
  13. Funnel utiliza stageHistory y no solo etapa actual
  14. Ciclo de venta utiliza fecha real de transición a Ganada en stageHistory
  15. Historial incompleto o corrupto no rompe el cálculo

Snapshots históricos:
  16. Creación de snapshot con métricas completas
  17. Snapshot tenant-aware (almacenamiento aislado)
  18. Idempotencia y deduplicación de snapshots (misma clave lógica)
  19. Snapshots para diferentes períodos (daily, weekly, monthly)
  20. Snapshots para diferentes branches
  21. Recuperación histórica y ordenamiento con get_metric_snapshots

Lead scoring contextual y explicable:
  22. Score siempre normalizado en rango 0–100
  23. Desglose explicable (scoreBreakdown) consistente y transparente
  24. Interacción reciente incrementa el score
  25. Oportunidad abierta incrementa el score
  26. Etapa avanzada (Negociación/Propuesta) puntúa más que etapa inicial
  27. Cotización comercial activa incrementa el score
  28. Historial de facturación real incrementa el score
  29. Cliente consolidado/activo no se clasifica erróneamente como lead frío
  30. Aislamiento multi-tenant en lead scoring
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest

from app.models.crm import CRMMetricSnapshot, LEAD_SCORE_WEIGHTS
from app.services.crm_service import CRMService


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Firestore Helper for Tests
# ─────────────────────────────────────────────────────────────────────────────

class InMemoryFirestore:
    def __init__(self):
        self.store = {}

    def get_collection(self, company_id, coll_name):
        store = self.store

        class MockDocRef:
            def __init__(self, doc_id):
                self.doc_id = doc_id

            def get(self):
                key = (company_id, coll_name, self.doc_id)
                exists = key in store
                doc_mock = MagicMock()
                doc_mock.exists = exists
                doc_mock.id = self.doc_id
                doc_mock.to_dict.return_value = store.get(key)
                return doc_mock

            def set(self, data):
                store[(company_id, coll_name, self.doc_id)] = dict(data)

            def delete(self):
                store.pop((company_id, coll_name, self.doc_id), None)

        class MockCollRef:
            def document(self, doc_id):
                return MockDocRef(doc_id)

            def get(self):
                docs = []
                for (cid, cname, did), data in list(store.items()):
                    if cid == company_id and cname == coll_name:
                        dm = MagicMock()
                        dm.id = did
                        dm.to_dict.return_value = dict(data)
                        docs.append(dm)
                return docs

        return MockCollRef()


# ─────────────────────────────────────────────────────────────────────────────
# 1-12: F4.3 Métricas Comerciales y Conversión
# ─────────────────────────────────────────────────────────────────────────────

def test_pipeline_nominal_calculation():
    """1. Pipeline nominal suma solo oportunidades abiertas, excluyendo ganadas, perdidas y soft-deleted."""
    company_id = "comp_metrics_1"
    opps = [
        {"id": "o1", "companyId": company_id, "status": "abierta", "stage": "Prospecto", "amount": 10000.0, "isDeleted": False},
        {"id": "o2", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 25000.0, "isDeleted": False},
        {"id": "o3", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 50000.0, "isDeleted": False},
        {"id": "o4", "companyId": company_id, "status": "perdida", "stage": "Perdida", "amount": 15000.0, "isDeleted": False},
        {"id": "o5", "companyId": company_id, "status": "abierta", "stage": "Calificado", "amount": 8000.0, "isDeleted": True},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["openOpportunities"] == 2
        assert metrics["pipelineValue"] == 35000.0  # 10,000 + 25,000
        assert metrics["wonOpportunities"] == 1
        assert metrics["lostOpportunities"] == 1


def test_pipeline_weighted_calculation():
    """2. Pipeline ponderado multiplica amount * probability/100, tolerando None, 0, >100 y negativos."""
    company_id = "comp_metrics_2"
    opps = [
        {"id": "o1", "companyId": company_id, "status": "abierta", "stage": "Prospecto", "amount": 10000.0, "probability": 10, "isDeleted": False},   # 1,000
        {"id": "o2", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 20000.0, "probability": 60, "isDeleted": False},   # 12,000
        {"id": "o3", "companyId": company_id, "status": "abierta", "stage": "Calificado", "amount": 5000.0, "probability": None, "isDeleted": False},  # fallback default 10% -> 500
        {"id": "o4", "companyId": company_id, "status": "abierta", "stage": "Negociación", "amount": 10000.0, "probability": 150, "isDeleted": False},# clamp 100% -> 10,000
        {"id": "o5", "companyId": company_id, "status": "abierta", "stage": "Negociación", "amount": -100.0, "probability": 80, "isDeleted": False},  # excluded negative
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["weightedPipelineValue"] == 23500.0  # 1000 + 12000 + 500 + 10000


def test_win_rate_calculation():
    """3. Win Rate = won / (won + lost) * 100."""
    company_id = "comp_metrics_3"
    opps = [
        {"id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 1000.0, "isDeleted": False},
        {"id": "o2", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 2000.0, "isDeleted": False},
        {"id": "o3", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 3000.0, "isDeleted": False},
        {"id": "o4", "companyId": company_id, "status": "perdida", "stage": "Perdida", "amount": 1500.0, "isDeleted": False},
        {"id": "o5", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 5000.0, "isDeleted": False},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        # 3 ganadas, 1 perdida -> 3 / 4 = 75.0%
        assert metrics["winRate"] == 75.0


def test_win_rate_division_by_zero():
    """4. Win rate retorna 0.0 sin excepción cuando won + lost == 0."""
    company_id = "comp_metrics_4"
    opps = [
        {"id": "o1", "companyId": company_id, "status": "abierta", "stage": "Prospecto", "amount": 1000.0, "isDeleted": False},
        {"id": "o2", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 2000.0, "isDeleted": False},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["winRate"] == 0.0


def test_funnel_reconstruction():
    """5. Embudo de conversión reconstruye etapas alcanzadas."""
    company_id = "comp_metrics_5"
    opps = [
        {
            "id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "stageHistory": [
                {"from": "Prospecto", "to": "Contactado", "timestamp": "2026-09-01T10:00:00Z"},
                {"from": "Contactado", "to": "Calificado", "timestamp": "2026-09-05T10:00:00Z"},
                {"from": "Calificado", "to": "Propuesta", "timestamp": "2026-09-10T10:00:00Z"},
                {"from": "Propuesta", "to": "Negociación", "timestamp": "2026-09-15T10:00:00Z"},
                {"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-20T10:00:00Z"},
            ],
            "isDeleted": False,
        },
        {
            "id": "o2", "companyId": company_id, "status": "abierta", "stage": "Propuesta",
            "stageHistory": [
                {"from": "Prospecto", "to": "Contactado", "timestamp": "2026-09-10T10:00:00Z"},
                {"from": "Contactado", "to": "Calificado", "timestamp": "2026-09-12T10:00:00Z"},
                {"from": "Calificado", "to": "Propuesta", "timestamp": "2026-09-15T10:00:00Z"},
            ],
            "isDeleted": False,
        },
        {
            "id": "o3", "companyId": company_id, "status": "abierta", "stage": "Prospecto",
            "stageHistory": [],
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        funnel = metrics["funnel"]
        assert funnel["Prospecto"] == 3
        assert funnel["Contactado"] == 2
        assert funnel["Calificado"] == 2
        assert funnel["Propuesta"] == 2
        assert funnel["Negociación"] == 1
        assert funnel["Ganada"] == 1


def test_conversion_rates_per_stage():
    """6. Conversión por etapa con denominadores correctos y claves canónicas."""
    company_id = "comp_metrics_6"
    opps = [
        {
            "id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "stageHistory": [
                {"from": "Prospecto", "to": "Contactado"},
                {"from": "Contactado", "to": "Calificado"},
                {"from": "Calificado", "to": "Propuesta"},
                {"from": "Propuesta", "to": "Negociación"},
                {"from": "Negociación", "to": "Ganada"},
            ],
            "isDeleted": False,
        },
        {
            "id": "o2", "companyId": company_id, "status": "abierta", "stage": "Contactado",
            "stageHistory": [{"from": "Prospecto", "to": "Contactado"}],
            "isDeleted": False,
        },
        {
            "id": "o3", "companyId": company_id, "status": "abierta", "stage": "Prospecto",
            "stageHistory": [],
            "isDeleted": False,
        },
        {
            "id": "o4", "companyId": company_id, "status": "abierta", "stage": "Prospecto",
            "stageHistory": [],
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        rates = metrics["conversionRates"]
        # Prospecto = 4, Contactado = 2 -> 2/4 = 50.0%
        assert rates["prospect_to_contacted"] == 50.0
        # Contactado = 2, Calificado = 1 -> 1/2 = 50.0%
        assert rates["contacted_to_qualified"] == 50.0
        # Calificado = 1, Propuesta = 1 -> 1/1 = 100.0%
        assert rates["qualified_to_proposal"] == 100.0
        # Propuesta = 1, Negociación = 1 -> 1/1 = 100.0%
        assert rates["proposal_to_negotiation"] == 100.0
        # Negociación = 1, Ganada = 1 -> 1/1 = 100.0%
        assert rates["negotiation_to_won"] == 100.0


def test_average_sales_cycle_days():
    """7. Ciclo promedio de venta calcula los días reales entre creación y entrada a Ganada."""
    company_id = "comp_metrics_7"
    opps = [
        {
            "id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "createdAt": "2026-09-01T10:00:00Z",
            "stageHistory": [{"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-11T10:00:00Z"}],  # 10 days
            "amount": 10000.0,
            "isDeleted": False,
        },
        {
            "id": "o2", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "createdAt": "2026-09-01T10:00:00Z",
            "stageHistory": [{"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-21T10:00:00Z"}],  # 20 days
            "amount": 20000.0,
            "isDeleted": False,
        },
        {
            "id": "o3", "companyId": company_id, "status": "abierta", "stage": "Negociación",
            "createdAt": "2026-08-01T10:00:00Z",
            "amount": 5000.0,
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        # (10 + 20) / 2 = 15.0 days
        assert metrics["avgSalesCycleDays"] == 15.0


def test_average_won_amount():
    """8. Ticket promedio (average won amount) solo sobre oportunidades Ganadas."""
    company_id = "comp_metrics_8"
    opps = [
        {"id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 15000.0, "isDeleted": False},
        {"id": "o2", "companyId": company_id, "status": "ganada", "stage": "Ganada", "amount": 35000.0, "isDeleted": False},
        {"id": "o3", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 100000.0, "isDeleted": False},
        {"id": "o4", "companyId": company_id, "status": "perdida", "stage": "Perdida", "amount": 50000.0, "isDeleted": False},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        # (15000 + 35000) / 2 = 25000.0
        assert metrics["avgWonAmount"] == 25000.0


def test_metrics_filter_by_branch():
    """9. Filtro de métricas por branchId delega y respeta la sucursal."""
    company_id = "comp_metrics_9"
    with patch.object(CRMService, "get_opportunities") as mock_opps:
        mock_opps.return_value = [
            {"id": "o1", "companyId": company_id, "branchId": "br_santiago", "status": "abierta", "stage": "Propuesta", "amount": 10000.0, "isDeleted": False}
        ]
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id, branch_id="br_santiago")
        mock_opps.assert_called_once_with("owner1", sandbox=True, company_id=company_id, include_closed=True, branch_id="br_santiago", project_id=None)
        assert metrics["pipelineValue"] == 10000.0


def test_metrics_filter_by_project():
    """10. Filtro de métricas por projectId delega y respeta el proyecto."""
    company_id = "comp_metrics_10"
    with patch.object(CRMService, "get_opportunities") as mock_opps:
        mock_opps.return_value = [
            {"id": "o1", "companyId": company_id, "projectId": "proj_torre", "status": "abierta", "stage": "Propuesta", "amount": 50000.0, "isDeleted": False}
        ]
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id, project_id="proj_torre")
        mock_opps.assert_called_once_with("owner1", sandbox=True, company_id=company_id, include_closed=True, branch_id=None, project_id="proj_torre")
        assert metrics["pipelineValue"] == 50000.0


def test_metrics_filter_by_responsible():
    """11. Filtro de métricas por responsable (vendedor assignedTo)."""
    company_id = "comp_metrics_11"
    opps = [
        {"id": "o1", "companyId": company_id, "assignedTo": "user_ana", "assignedToName": "Ana", "status": "abierta", "stage": "Propuesta", "amount": 20000.0, "isDeleted": False},
        {"id": "o2", "companyId": company_id, "assignedTo": "user_carlos", "assignedToName": "Carlos", "status": "abierta", "stage": "Propuesta", "amount": 40000.0, "isDeleted": False},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id, assigned_to="user_ana")
        assert metrics["openOpportunities"] == 1
        assert metrics["pipelineValue"] == 20000.0


def test_metrics_tenant_isolation():
    """12. Aislamiento multi-tenant de métricas: Company A nunca ve datos de Company B."""
    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_sales_metrics("owner1", sandbox=True, company_id="")

    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.get_sales_metrics("owner1", sandbox=True, company_id=None)


# ─────────────────────────────────────────────────────────────────────────────
# 13-15: Stage History y Resiliencia
# ─────────────────────────────────────────────────────────────────────────────

def test_funnel_uses_stage_history_not_only_current_stage():
    """13. Oportunidad actualmente Ganada se cuenta en todas las etapas que recorrió."""
    company_id = "comp_hist_13"
    opps = [
        {
            "id": "o_won", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "stageHistory": [
                {"from": "Prospecto", "to": "Contactado"},
                {"from": "Contactado", "to": "Calificado"},
                {"from": "Calificado", "to": "Propuesta"},
                {"from": "Propuesta", "to": "Negociación"},
                {"from": "Negociación", "to": "Ganada"},
            ],
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        funnel = metrics["funnel"]
        assert funnel["Prospecto"] == 1
        assert funnel["Contactado"] == 1
        assert funnel["Calificado"] == 1
        assert funnel["Propuesta"] == 1
        assert funnel["Negociación"] == 1
        assert funnel["Ganada"] == 1


def test_sales_cycle_uses_real_stage_history_timestamp():
    """14. Ciclo de venta usa la marca de tiempo de entrada a Ganada en stageHistory."""
    company_id = "comp_hist_14"
    opps = [
        {
            "id": "o1", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "createdAt": "2026-09-01T08:00:00Z",
            "updatedAt": "2026-10-05T12:00:00Z",  # Modificada semanas después
            "stageHistory": [
                {"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-06T18:00:00Z"}  # Ganada en 5 días
            ],
            "amount": 10000.0,
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["avgSalesCycleDays"] == 5.0  # 5 días, no 34 días de updatedAt


def test_sales_cycle_and_funnel_resilient_to_incomplete_history():
    """15. Historial corrupto o vacío no genera excepciones y usa fallbacks seguros."""
    company_id = "comp_hist_15"
    opps = [
        {
            "id": "o_corrupt", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "createdAt": None,
            "stageHistory": [{"invalid": 123}],
            "amount": None,
            "isDeleted": False,
        },
        {
            "id": "o_empty", "companyId": company_id, "status": "abierta", "stage": "InvalidStage",
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["avgSalesCycleDays"] == 0.0
        assert isinstance(metrics["funnel"], dict)
        assert metrics["pipelineValue"] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 16-21: Snapshots Históricos (CRMMetricSnapshot)
# ─────────────────────────────────────────────────────────────────────────────

def test_create_metric_snapshot():
    """16. Creación de snapshot con estructura de modelo completa y métricas consolidadas."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_snap_16"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics") as mock_metrics, \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        mock_metrics.return_value = {
            "openOpportunities": 4, "wonOpportunities": 2, "lostOpportunities": 1,
            "pipelineValue": 120000.0, "weightedPipelineValue": 75000.0,
            "winRate": 66.67, "avgWonAmount": 30000.0, "avgSalesCycleDays": 12.5,
            "funnel": {"Prospecto": 5, "Ganada": 2}, "conversionRates": {"prospect_to_contacted": 80.0},
            "bySalesperson": [], "byBranch": [], "byProject": [],
        }

        snap = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period="daily", period_start="2026-10-07")
        assert snap["companyId"] == company_id
        assert snap["period"] == "daily"
        assert snap["periodStart"] == "2026-10-07"
        assert snap["pipelineValue"] == 120000.0
        assert snap["winRate"] == 66.67
        assert snap["avgSalesCycleDays"] == 12.5
        assert "snap_comp_snap_16_all_all_daily_2026-10-07" in snap["id"]


def test_snapshot_tenant_aware():
    """17. Snapshot se guarda exclusivamente en la colección del tenant correspondiente."""
    mock_fs = InMemoryFirestore()
    company_a = "comp_snap_a"
    company_b = "comp_snap_b"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 1, "wonOpportunities": 0, "lostOpportunities": 0, "pipelineValue": 1000.0, "weightedPipelineValue": 100.0, "winRate": 0.0, "avgWonAmount": 0.0, "avgSalesCycleDays": 0.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        snap_a = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_a, period_start="2026-10-07")
        snapshots_b = CRMService.get_metric_snapshots("owner1", sandbox=True, company_id=company_b)
        assert len(snapshots_b) == 0


def test_snapshot_idempotency_no_duplicates():
    """18. Generar el snapshot múltiples veces para la misma clave no crea duplicados."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_snap_18"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 2, "wonOpportunities": 1, "lostOpportunities": 0, "pipelineValue": 5000.0, "weightedPipelineValue": 2500.0, "winRate": 100.0, "avgWonAmount": 5000.0, "avgSalesCycleDays": 3.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        snap1 = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period="daily", period_start="2026-10-07")
        snap2 = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period="daily", period_start="2026-10-07")
        assert snap1["id"] == snap2["id"]

        snapshots = CRMService.get_metric_snapshots("owner1", sandbox=True, company_id=company_id)
        assert len(snapshots) == 1


def test_snapshots_different_periods():
    """19. Diferentes períodos (daily, weekly, monthly) generan snapshots distintos."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_snap_19"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 1, "wonOpportunities": 0, "lostOpportunities": 0, "pipelineValue": 100.0, "weightedPipelineValue": 10.0, "winRate": 0.0, "avgWonAmount": 0.0, "avgSalesCycleDays": 0.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        snap_daily = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period="daily", period_start="2026-10-07")
        snap_monthly = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period="monthly", period_start="2026-10-01", period_end="2026-10-31")
        assert snap_daily["id"] != snap_monthly["id"]

        snapshots = CRMService.get_metric_snapshots("owner1", sandbox=True, company_id=company_id)
        assert len(snapshots) == 2


def test_snapshots_different_branches():
    """20. Diferentes sucursales generan snapshots independientes."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_snap_20"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 1, "wonOpportunities": 0, "lostOpportunities": 0, "pipelineValue": 100.0, "weightedPipelineValue": 10.0, "winRate": 0.0, "avgWonAmount": 0.0, "avgSalesCycleDays": 0.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        snap_br1 = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, branch_id="br_principal", period_start="2026-10-07")
        snap_br2 = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, branch_id="br_santiago", period_start="2026-10-07")
        assert snap_br1["id"] != snap_br2["id"]

        snaps_santiago = CRMService.get_metric_snapshots("owner1", sandbox=True, company_id=company_id, branch_id="br_santiago")
        assert len(snaps_santiago) == 1
        assert snaps_santiago[0]["branchId"] == "br_santiago"


def test_get_metric_snapshots_recovery():
    """21. Recuperación histórica de snapshots ordenada descendentemente por fecha."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_snap_21"

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 1, "wonOpportunities": 0, "lostOpportunities": 0, "pipelineValue": 100.0, "weightedPipelineValue": 10.0, "winRate": 0.0, "avgWonAmount": 0.0, "avgSalesCycleDays": 0.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period_start="2026-10-05")
        CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period_start="2026-10-07")
        CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period_start="2026-10-06")

        recovered = CRMService.get_metric_snapshots("owner1", sandbox=True, company_id=company_id)
        assert len(recovered) == 3
        assert recovered[0]["periodStart"] == "2026-10-07"
        assert recovered[1]["periodStart"] == "2026-10-06"
        assert recovered[2]["periodStart"] == "2026-10-05"


# ─────────────────────────────────────────────────────────────────────────────
# 22-30: F4.4 Lead Scoring Contextual y Explicable
# ─────────────────────────────────────────────────────────────────────────────

def test_lead_score_always_bounded_0_to_100():
    """22. El lead score siempre se mantiene en el rango [0, 100]."""
    company_id = "comp_score_22"
    contact = {"id": "c1", "razonSocial": "Empresa VIP", "email": "vip@corp.com", "telefono": "8095550000", "responsibleId": "u1", "types": ["cliente"]}
    # Simular acumulación extrema de puntos
    opps = [{"contactId": "c1", "status": "abierta", "stage": "Negociación"}]
    quotes = [{"clientId": "c1", "status": "Aprobada"}]
    invoices = [{"clientId": "c1", "status": "Emitida", "total": 500000.0}]
    activities = [{"contactId": "c1", "status": "completada", "completedAt": "2026-10-07T10:00:00Z"}]

    res = CRMService.calculate_lead_score(
        "owner1",
        contact=contact,
        opportunities=opps,
        activities=activities,
        quotations=quotes,
        invoices=invoices,
        company_id=company_id,
        today_date=datetime(2026, 10, 7).date()
    )
    assert 0 <= res["score"] <= 100
    assert res["score"] == 100  # clamped at max 100


def test_lead_score_breakdown_consistent():
    """23. El desglose scoreBreakdown contiene factores claros y explicables."""
    company_id = "comp_score_23"
    contact = {"id": "c1", "razonSocial": "Lead Test", "email": "lead@test.com"}
    res = CRMService.calculate_lead_score(
        "owner1",
        contact=contact,
        opportunities=[],
        activities=[],
        quotations=[],
        invoices=[],
        company_id=company_id
    )
    breakdown = res["scoreBreakdown"]
    assert len(breakdown) > 0
    factors = [b["factor"] for b in breakdown]
    assert "base" in factors
    assert "has_email" in factors
    assert all("points" in b and "description" in b for b in breakdown)


def test_lead_score_recent_interaction_increases_score():
    """24. Interacción reciente (<= 7d) otorga mayor puntaje que (<= 30d) o sin interacción."""
    company_id = "comp_score_24"
    contact = {"id": "c1", "razonSocial": "Lead Contacto"}
    today = datetime(2026, 10, 7).date()

    act_7d = [{"contactId": "c1", "completedAt": "2026-10-05T10:00:00Z"}]  # 2 days ago
    act_20d = [{"contactId": "c1", "completedAt": "2026-09-20T10:00:00Z"}] # 17 days ago
    act_none = []

    res_7d = CRMService.calculate_lead_score("owner1", contact=contact, activities=act_7d, opportunities=[], quotations=[], invoices=[], company_id=company_id, today_date=today)
    res_20d = CRMService.calculate_lead_score("owner1", contact=contact, activities=act_20d, opportunities=[], quotations=[], invoices=[], company_id=company_id, today_date=today)
    res_none = CRMService.calculate_lead_score("owner1", contact=contact, activities=act_none, opportunities=[], quotations=[], invoices=[], company_id=company_id, today_date=today)

    assert res_7d["score"] > res_20d["score"]
    assert res_20d["score"] > res_none["score"]


def test_lead_score_open_opportunity_increases_score():
    """25. Oportunidad abierta incrementa el puntaje del lead."""
    company_id = "comp_score_25"
    contact = {"id": "c1", "razonSocial": "Lead Opp"}

    opp_open = [{"contactId": "c1", "status": "abierta", "stage": "Prospecto", "isDeleted": False}]
    res_with_opp = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=opp_open, activities=[], quotations=[], invoices=[], company_id=company_id)
    res_no_opp = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=[], activities=[], quotations=[], invoices=[], company_id=company_id)

    assert res_with_opp["score"] > res_no_opp["score"]


def test_lead_score_stage_weights():
    """26. Etapa avanzada (Negociación/Propuesta) puntúa más que etapa temprana (Contactado/Calificado)."""
    company_id = "comp_score_26"
    contact = {"id": "c1", "razonSocial": "Lead Stages"}

    opp_advanced = [{"contactId": "c1", "status": "abierta", "stage": "Negociación", "isDeleted": False}]
    opp_early = [{"contactId": "c1", "status": "abierta", "stage": "Contactado", "isDeleted": False}]

    res_adv = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=opp_advanced, activities=[], quotations=[], invoices=[], company_id=company_id)
    res_early = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=opp_early, activities=[], quotations=[], invoices=[], company_id=company_id)

    assert res_adv["score"] > res_early["score"]


def test_lead_score_active_quotation_increases_score():
    """27. Cotización comercial activa incrementa el score del lead."""
    company_id = "comp_score_27"
    contact = {"id": "c1", "razonSocial": "Lead Cotizacion"}

    quotes = [{"clientId": "c1", "status": "Emitida"}]
    res_quote = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=[], activities=[], quotations=quotes, invoices=[], company_id=company_id)
    res_no_quote = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=[], activities=[], quotations=[], invoices=[], company_id=company_id)

    assert res_quote["score"] > res_no_quote["score"]


def test_lead_score_billing_history_influences_score():
    """28. Historial de facturación real acumulada incrementa el score."""
    company_id = "comp_score_28"
    contact = {"id": "c1", "razonSocial": "Cliente Facturado", "types": ["cliente"]}

    invs_high = [{"clientId": "c1", "status": "Emitida", "total": 150000.0}]
    invs_none = []

    res_high = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=[], activities=[], quotations=[], invoices=invs_high, company_id=company_id)
    res_none = CRMService.calculate_lead_score("owner1", contact=contact, opportunities=[], activities=[], quotations=[], invoices=invs_none, company_id=company_id)

    assert res_high["score"] > res_none["score"]
    assert res_high["totalInvoiced"] == 150000.0


def test_consolidated_customer_not_classified_as_cold_lead():
    """29. Cliente consolidado con facturación histórica se clasifica como active_customer o dormant_customer, NO como cold_lead."""
    company_id = "comp_score_29"
    today = datetime(2026, 10, 7).date()

    # Cliente activo con compra hace 20 días
    contact_active = {"id": "c_active", "razonSocial": "Cliente Activo SRL", "types": ["cliente"]}
    invoices_recent = [{"clientId": "c_active", "status": "Emitida", "total": 50000.0, "date": "2026-09-20"}]
    res_active = CRMService.calculate_lead_score("owner1", contact=contact_active, invoices=invoices_recent, opportunities=[], activities=[], quotations=[], company_id=company_id, today_date=today)
    assert res_active["classification"] == "active_customer"
    assert res_active["classificationLabel"] == "Cliente Activo"

    # Cliente dormido con última compra hace 180 días
    contact_dormant = {"id": "c_dormant", "razonSocial": "Cliente Dormido SRL", "types": ["cliente"]}
    invoices_old = [{"clientId": "c_dormant", "status": "Emitida", "total": 80000.0, "date": "2026-04-01"}]
    res_dormant = CRMService.calculate_lead_score("owner1", contact=contact_dormant, invoices=invoices_old, opportunities=[], activities=[], quotations=[], company_id=company_id, today_date=today)
    assert res_dormant["classification"] == "dormant_customer"
    assert res_dormant["classificationLabel"] == "Cliente Inactivo/Dormido"
    assert res_dormant["classification"] != "cold_lead"


def test_lead_scoring_tenant_isolation():
    """30. Aislamiento multi-tenant en lead scoring."""
    with pytest.raises(ValueError, match="company_id es requerido"):
        CRMService.calculate_lead_score("owner1", contact={"id": "c1"}, company_id="")


# ─────────────────────────────────────────────────────────────────────────────
# 31-36: F4.6 Validación de Negocio y Casos Límite
# ─────────────────────────────────────────────────────────────────────────────

def test_funnel_skipped_stages_exposes_anomaly_without_clamping():
    """31. Embudo expone anomalías reales sin enmascarar con min(100) si una etapa posterior supera a la anterior."""
    company_id = "comp_f46_31"
    # Simular 100 en Propuesta y 120 en Negociación (ej. importación o salto de etapa)
    opps = []
    for i in range(100):
        opps.append({
            "id": f"op_p_{i}", "companyId": company_id, "status": "abierta", "stage": "Propuesta",
            "stageHistory": [{"from": "Calificado", "to": "Propuesta"}], "isDeleted": False,
        })
    for i in range(120):
        opps.append({
            "id": f"op_n_{i}", "companyId": company_id, "status": "abierta", "stage": "Negociación",
            "stageHistory": [{"from": "Calificado", "to": "Negociación"}], "isDeleted": False,
        })

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        # Propuesta = 100, Negociación = 120 -> 120/100 = 120.0% (no clamped at 100%)
        assert metrics["funnel"]["Propuesta"] == 100
        assert metrics["funnel"]["Negociación"] == 120
        assert metrics["conversionRates"]["proposal_to_negotiation"] == 120.0


def test_funnel_opportunity_created_in_advanced_stage_does_not_assume_prospecto():
    """32. Oportunidad creada directamente en etapa avanzada sin historial no incrementa falsamente Prospecto."""
    company_id = "comp_f46_32"
    opps = [
        {"id": "o_direct_cal", "companyId": company_id, "status": "abierta", "stage": "Calificado", "stageHistory": [], "isDeleted": False},
        {"id": "o_direct_prop", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "stageHistory": [], "isDeleted": False},
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        assert metrics["funnel"]["Prospecto"] == 0
        assert metrics["funnel"]["Contactado"] == 0
        assert metrics["funnel"]["Calificado"] == 1
        assert metrics["funnel"]["Propuesta"] == 1


def test_reopened_opportunity_sales_cycle_uses_final_closure_date():
    """33. Oportunidad Ganada -> Reabierta -> Ganada nuevamente usa la fecha de cierre final."""
    company_id = "comp_f46_33"
    opps = [
        {
            "id": "o_reopened", "companyId": company_id, "status": "ganada", "stage": "Ganada",
            "createdAt": "2026-09-01T10:00:00Z",
            "stageHistory": [
                {"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-06T10:00:00Z"},      # Ganada inicial en 5 días
                {"from": "Ganada", "to": "Negociación", "timestamp": "2026-09-10T10:00:00Z"},     # Reabierta
                {"from": "Negociación", "to": "Ganada", "timestamp": "2026-09-26T10:00:00Z"},     # Ganada definitiva en 25 días
            ],
            "amount": 25000.0,
            "isDeleted": False,
        }
    ]

    with patch.object(CRMService, "get_opportunities", return_value=opps):
        metrics = CRMService.get_sales_metrics("owner1", sandbox=True, company_id=company_id)
        # El ciclo debe reflejar el cierre definitivo (2026-09-26 - 2026-09-01 = 25 días)
        assert metrics["avgSalesCycleDays"] == 25.0


def test_lead_scoring_distribution_no_artificial_saturation():
    """34. Distribución del score calibrada en escala 0–100 sin saturación artificial."""
    company_id = "comp_f46_34"
    today = datetime(2026, 10, 7).date()

    # 1. Lead frío básico (solo datos de contacto básicos)
    contact_cold = {"id": "c_cold", "razonSocial": "Lead Frío"}
    score_cold = CRMService.calculate_lead_score("owner1", contact=contact_cold, opportunities=[], activities=[], quotations=[], invoices=[], company_id=company_id, today_date=today)
    assert score_cold["score"] == 5  # solo base (5 pts)
    assert score_cold["classification"] == "cold_lead"

    # 2. Lead templado (datos completos + contacto reciente 30d + opp inicial)
    contact_warm = {"id": "c_warm", "razonSocial": "Lead Templado", "email": "w@test.com", "telefono": "8095551234", "responsibleId": "u1"}
    act_warm = [{"contactId": "c_warm", "completedAt": "2026-09-25T10:00:00Z"}]  # 12d ago -> 10 pts
    opp_warm = [{"contactId": "c_warm", "status": "abierta", "stage": "Contactado"}]  # 15 + 5 = 20 pts
    # Total: 5(base) + 5(email) + 5(tel) + 5(resp) + 10(interac 30d) + 15(opp) + 5(stage) = 50 pts
    score_warm = CRMService.calculate_lead_score("owner1", contact=contact_warm, activities=act_warm, opportunities=opp_warm, quotations=[], invoices=[], company_id=company_id, today_date=today)
    assert score_warm["score"] == 50
    assert score_warm["classification"] == "warm_lead"

    # 3. Lead caliente (datos completos + interacción <=7d + opp avanzada + cotización activa)
    contact_hot = {"id": "c_hot", "razonSocial": "Lead Caliente", "email": "h@test.com", "telefono": "8095554321", "responsibleId": "u1"}
    act_hot = [{"contactId": "c_hot", "completedAt": "2026-10-06T10:00:00Z"}]  # 1d ago -> 20 pts
    opp_hot = [{"contactId": "c_hot", "status": "abierta", "stage": "Negociación"}]  # 15 + 15 = 30 pts
    quotes_hot = [{"clientId": "c_hot", "status": "Emitida"}]  # 15 pts
    # Total: 20(profile) + 20(interac 7d) + 15(opp) + 15(stage negoc) + 15(quote) = 85 pts
    score_hot = CRMService.calculate_lead_score("owner1", contact=contact_hot, activities=act_hot, opportunities=opp_hot, quotations=quotes_hot, invoices=[], company_id=company_id, today_date=today)
    assert score_hot["score"] == 85
    assert score_hot["classification"] == "hot_lead"

    # 4. Cliente consolidado con score 100 exacto
    inv_high = [{"clientId": "c_hot", "status": "Emitida", "total": 120000.0, "date": "2026-10-05"}]  # 10 + 5 = 15 pts
    score_100 = CRMService.calculate_lead_score("owner1", contact=contact_hot, activities=act_hot, opportunities=opp_hot, quotations=quotes_hot, invoices=inv_high, company_id=company_id, today_date=today)
    assert score_100["score"] == 100  # 85 + 15 = 100 exactamente, sin rebasar ni saturar


def test_dashboard_metrics_are_live_and_independent_of_snapshots():
    """35. El dashboard CRM siempre calcula métricas en tiempo real de forma dinámica y no a partir de snapshots congelados."""
    company_id = "comp_f46_35"
    with patch.object(CRMService, "get_sales_metrics") as mock_metrics, \
         patch.object(CRMService, "get_opportunities", return_value=[]), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]), \
         patch.object(CRMService, "get_pipeline", return_value=[]), \
         patch.object(CRMService, "get_stale_opportunities", return_value=[]), \
         patch.object(CRMService, "get_next_action_suggestions", return_value=[]):

        mock_metrics.return_value = {
            "openOpportunities": 10, "wonOpportunities": 5, "lostOpportunities": 2,
            "pipelineValue": 250000.0, "weightedPipelineValue": 150000.0,
            "winRate": 71.4, "avgWonAmount": 50000.0, "avgSalesCycleDays": 8.0,
            "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []
        }

        dashboard = CRMService.get_dashboard("owner1", sandbox=True, company_id=company_id, date_range="30d")
        # Confirma que se llamó directamente el cálculo en vivo con el rango
        assert mock_metrics.called
        assert dashboard["metrics"]["pipelineValue"] == 250000.0
        assert dashboard["metrics"]["winRate"] == 71.4
        assert dashboard["selectedDateRange"] == "30d"


def test_metric_snapshot_does_not_corrupt_or_overwrite_live_opportunities():
    """36. Generar un snapshot persiste exclusivamente en la colección de snapshots sin modificar las oportunidades operativas."""
    mock_fs = InMemoryFirestore()
    company_id = "comp_f46_36"

    # Insertar oportunidad en el store
    mock_fs.store[(company_id, "sandbox_crm_opportunities", "opp_1")] = {
        "id": "opp_1", "companyId": company_id, "status": "abierta", "stage": "Propuesta", "amount": 10000.0
    }

    with patch("app.services.crm_service.firebase_initialized", True), \
         patch("app.services.crm_service._company_coll", side_effect=lambda company_id, owner_uid, coll_name: mock_fs.get_collection(company_id, coll_name)), \
         patch.object(CRMService, "get_sales_metrics", return_value={"openOpportunities": 1, "wonOpportunities": 0, "lostOpportunities": 0, "pipelineValue": 10000.0, "weightedPipelineValue": 5500.0, "winRate": 0.0, "avgWonAmount": 0.0, "avgSalesCycleDays": 0.0, "funnel": {}, "conversionRates": {}, "bySalesperson": [], "byBranch": [], "byProject": []}), \
         patch.object(CRMService, "get_activities", return_value=[]), \
         patch.object(CRMService, "get_leads", return_value=[]):

        snap = CRMService.create_metric_snapshot("owner1", sandbox=True, company_id=company_id, period_start="2026-10-07")
        assert snap["pipelineValue"] == 10000.0

        # Verificar que la oportunidad original sigue intacta
        opp_doc = mock_fs.get_collection(company_id, "sandbox_crm_opportunities").document("opp_1").get()
        assert opp_doc.exists is True
        assert opp_doc.to_dict()["amount"] == 10000.0
