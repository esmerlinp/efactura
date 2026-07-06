MUNICIPIOS_RD = [
    "Distrito Nacional", "Santo Domingo Este", "Santo Domingo Oeste", "Santo Domingo Norte",
    "Los Alcarrizos", "Boca Chica", "Pedro Brand", "San Antonio de Guerra",
    "Santiago de los Caballeros", "Baitoa", "Jánico", "Licey al Medio",
    "Puñal", "Sabana Iglesia", "San José de las Matas", "Tamboril", "Villa Bisonó", "Villa González",
    "La Vega", "Constanza", "Jarabacoa", "Jima Abajo",
    "San Cristóbal", "Bajos de Haina", "Cambita Garabito", "Los Cacaos", "Sabana Grande de Palenque",
    "San Gregorio de Nigua", "Villa Altagracia", "Yaguate",
    "San Pedro de Macorís", "Consuelo", "Guayacanes", "Quisqueya", "Ramón Santana", "San José de los Llanos",
    "La Romana", "Guaymate", "Villa Hermosa",
    "San Francisco de Macorís", "Arenoso", "Castillo", "Eugenio María de Hostos", "Las Guáranas",
    "Pimentel", "Villa Riva",
    "Puerto Plata", "Altamira", "Guananico", "Imbert", "Los Hidalgos", "Luperón",
    "Sosúa", "Villa Isabela", "Villa Montellano",
    "Moca", "Cayetano Germosén", "Gaspar Hernández", "San Víctor",
    "Duarte", "Las Terrenas", "Samaná", "Sánchez",
    "Higüey", "San Rafael del Yuma", "La Altagracia",
    "Barahona", "Cabral", "El Peñón", "Enriquillo", "Fundación", "Jaquimeyes", "La Ciénaga",
    "Las Salinas", "Polo", "Paraíso", "Vicente Noble",
    "Azua", "Estebanía", "Guayabal", "Las Charcas", "Padre Las Casas", "Peralta", "Pueblo Viejo",
    "Sabana Yegua", "Tábara Arriba",
    "Mao", "Esperanza", "Laguna Salada", "Jaime Molina (Los Jíbaros)",
    "Monte Cristi", "Castañuelas", "Guayubín", "Las Matas de Santa Cruz", "Pepillo Salcedo (Manzanillo)",
    "San Fernando de Monte Cristi", "Villa Vásquez",
    "Baní", "Matanzas", "Nizao", "Peravia",
    "Cotuy", "Cevicos", "Fantino", "Villa La Mata", "Sabana del Puerto",
    "San Juan de la Maguana", "Bohechío", "El Cercado", "Juan de Herrera", "Las Matas de Farfán",
    "San Juan de la Maguana", "Vallejuelo",
    "Comendador", "Bánica", "El Llano", "Hondo Valle", "Juan Santiago", "Pedro Santana",
    "San José de Ocoa", "Rancho Arriba", "Sabana Larga",
    "Salcedo", "Tenares", "Villa Tapia",
    "Nagua", "Cabrera", "El Factor", "Río San Juan",
    "Monte Plata", "Bayaguana", "Peralvillo", "Sabana Grande de Boyá", "Yamasá",
    "Hato Mayor", "El Valle", "Sabana de la Mar",
    "El Seibo", "Miches",
    "Pedernales", "Oviedo",
    "Dajabón", "El Pino", "Loma de Cabrera", "Partido", "Restauración",
    "Santiago Rodríguez (Sabaneta)", "San Ignacio de Sabaneta", "Monción", "Cepillo",
    "San Rafael de El Cercado", "Jimaní", "La Descubierta", "Postrer Río", "Río Limpio", "Cristóbal",
]

ID_TYPES = [
    {"value": "cedula", "label": "Cédula"},
    {"value": "rnc", "label": "RNC"},
    {"value": "pasaporte", "label": "Pasaporte"},
]

CONTRACT_TYPES = [
    {"value": "tiempo_indefinido", "label": "Tiempo indefinido"},
    {"value": "tiempo_definido", "label": "Tiempo definido"},
    {"value": "obra_o_servicio", "label": "Por obra o servicio"},
    {"value": "temporal", "label": "Temporal"},
    {"value": "practicante", "label": "Practicante"},
]

AREAS = [
    {"value": "administrativa", "label": "Administrativa"},
    {"value": "operativa", "label": "Operativa"},
    {"value": "ventas", "label": "Ventas"},
    {"value": "financiera", "label": "Financiera"},
    {"value": "contabilidad", "label": "Contabilidad"},
    {"value": "produccion", "label": "Producción"},
    {"value": "logistica", "label": "Logística"},
    {"value": "recursos_humanos", "label": "Recursos Humanos"},
    {"value": "sistemas", "label": "Sistemas / TI"},
    {"value": "marketing", "label": "Marketing"},
    {"value": "gerencia", "label": "Gerencia"},
]

WORKDAYS = [
    {"value": "completa", "label": "Completa"},
    {"value": "media_jornada", "label": "Media jornada"},
    {"value": "reducida", "label": "Reducida"},
    {"value": "por_turnos", "label": "Por turnos"},
]

PAYMENT_METHODS = [
    {"value": "transferencia", "label": "Transferencia bancaria"},
    {"value": "cheque", "label": "Cheque"},
    {"value": "efectivo", "label": "Efectivo"},
    {"value": "deposito", "label": "Depósito en cuenta"},
]

BANCOS_RD = [
    "Banco Popular Dominicano",
    "Banco de Reservas",
    "Banco BHD",
    "Banco Caribe",
    "Banco BDI",
    "Banco Scotiabank",
    "Banco General",
    "Banco Vimenca",
    "Banco López de Haro",
    "Banco Atlántico",
    "Banco de Ahorro y Crédito ADEMI",
    "Banco de Ahorro y Crédito La Nacional",
    "Banco de Ahorro y Crédito Union",
    "Banco de Ahorro y Crédito JMMB",
    "Banco de Ahorro y Crédito Fihogar",
    "Banco de Ahorro y Crédito Caribería",
    "Banco de Ahorro y Crédito Associados",
    "Banco Múltiple Santa Cruz",
    "Banco Múltiple Activo Dominicana",
    "Banco Múltiple Bell Bank",
]

ACCOUNT_TYPES = [
    {"value": "ahorro", "label": "Ahorro"},
    {"value": "corriente", "label": "Corriente"},
]

PAYROLL_FREQUENCIES = [
    {"value": "quincenal", "label": "Quincenal"},
    {"value": "mensual", "label": "Mensual"},
]

DEFAULT_REFERENCE_DATA = {
    "contractTypes": CONTRACT_TYPES,
    "areas": AREAS,
}

DEFAULT_PAYROLL_CONFIG = {
    "payrollFrequency": "",
    "onboardingCompleted": False,
    "minSalary": 23223.00,
    "afpTotal": 464460.00,
    "sfsTotal": 232230.00,
    "srlTotal": 92892.40,
    "year": 2026,
}
