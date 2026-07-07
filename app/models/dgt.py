"""Modelos para formularios DGT (Dirección General de Trabajo — Ministerio de Trabajo RD)."""

from datetime import date
from typing import Optional, List
from pydantic import BaseModel


class DGTLine(BaseModel):
    """Una línea/fila en el archivo plano SIRLA (22 campos)."""
    tipoDocumento: int = 1           # 1=Cédula, 2=Pasaporte
    documento: str = ""              # 11 dígitos sin guiones
    nombres: str = ""                # Max 40 caracteres
    apellidos: str = ""              # Max 40 caracteres
    nacionalidad: int = 1            # 1=Dominicana
    sexo: str = ""                   # M/F
    fechaNacimiento: str = ""        # DD/MM/AAAA
    estadoCivil: str = ""            # S/C/U/D/V
    salario: float = 0.0            # 000000.00
    tipoMoneda: int = 1              # 1=DOP
    frecuenciaPago: int = 1          # 1=Mensual, 2=Quincenal, 3=Semanal, 4=Diario
    ocupacionCodigo: str = ""        # Código CNO-2019 (4 dígitos)
    ocupacionTexto: str = ""         # Descripción
    fechaIngreso: str = ""           # DD/MM/AAAA
    tipoContrato: int = 1            # 1=Indefinido, 2=Limitado
    horasSemanales: int = 44         # Max 44
    turnoTrabajo: int = 1            # 1=Diurno, 2=Nocturno, 3=Mixto
    estadoTrabajador: int = 1        # 1=Activo
    tipoNovedad: int = 0             # 0=Ninguno(DGT-3), 1=Alta, 2=Baja, 3=Modificación
    fechaNovedad: str = ""           # DD/MM/AAAA (opcional)
    gradoInstruccion: int = 0        # 1-6
    concesionVacaciones: int = 1     # 1=Tomará, 2=Ya tomó


class DGT3Report(BaseModel):
    """Reporte DGT-3: Planilla de Personal Fijo."""
    year: int = 0
    companyRnc: str = ""
    companyName: str = ""
    establishmentCode: str = ""
    totalEmployees: int = 0
    totalSalary: float = 0.0
    lines: List[DGTLine] = []


class DGT4Change(BaseModel):
    """Un cambio detectado para DGT-4."""
    tipo: str = ""                   # "alta" | "baja" | "modificacion"
    empleadoId: str = ""
    documento: str = ""
    nombre: str = ""
    cambioAnterior: str = ""
    cambioNuevo: str = ""
    fechaCambio: str = ""
    lineaDGT: Optional[DGTLine] = None


class DGT4Report(BaseModel):
    """Reporte DGT-4: Cambios en Planilla de Personal Fijo."""
    year: int = 0
    month: int = 0
    companyRnc: str = ""
    totalCambios: int = 0
    altas: int = 0
    bajas: int = 0
    modificaciones: int = 0
    lines: List[DGT4Change] = []


class DGT2Schedule(BaseModel):
    """DGT-2: Cartel de Horas y Vacaciones."""
    year: int = 0
    workdayStart: str = ""           # Inicio jornada (HH:MM)
    workdayEnd: str = ""             # Fin jornada (HH:MM)
    lunchStart: str = ""             # Inicio almuerzo
    lunchEnd: str = ""               # Fin almuerzo
    workDays: List[str] = []         # Días laborables (L,M,Mi,J,V,S,D)
    restDays: List[str] = []         # Días de descanso
    saturdayHours: str = ""          # Horario sábado si aplica
    totalOvertimeHours: float = 0.0  # HE acumuladas en el año
    workersOnVacation: List[dict] = []  # [{name, desde, hasta, days}]


class DGT5Worker(BaseModel):
    """Trabajador ocasional/temporal para DGT-5."""
    tipoDocumento: int = 1
    documento: str = ""
    nombres: str = ""
    apellidos: str = ""
    ocupacion: str = ""
    fechaInicio: str = ""
    fechaFin: str = ""
    salario: float = 0.0
    motivo: str = ""


class DGT9Suspension(BaseModel):
    """DGT-9: Suspensión de Contratos."""
    id: str = ""
    establishmentId: str = ""
    fechaSolicitud: str = ""
    causa: str = ""                  # fuerza_mayor | falta_materia_prima | ...
    fechaInicio: str = ""
    fechaFinPrevista: str = ""
    trabajadores: List[dict] = []    # [{doc, nombre, cargo}]
    estado: str = "activa"           # activa | cesada


class DGT12Reinstatement(BaseModel):
    """DGT-12: Cese de Suspensión."""
    id: str = ""
    suspensionId: str = ""           # Referencia al DGT-9
    fechaCese: str = ""
    trabajadores: List[dict] = []    # [{doc, nombre, fechaReincorporacion}]
