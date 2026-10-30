"""Genera la presentación PowerPoint profesional de VykCore y VykOne ERP."""

import os
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_FILE = ROOT / "docs" / "comercial" / "VykCore_VykOne_Certificacion_eCF_DGII.pptx"
LOGO_PATH = ROOT / "static" / "images" / "logo.png"

# Paleta de colores institucional VykCore / VykOne
COLOR_BG_DARK = RGBColor(10, 14, 26)       # #0A0E1A
COLOR_BG_LIGHT = RGBColor(248, 250, 252)   # #F8FAFC
COLOR_CARD_DARK = RGBColor(22, 30, 49)     # #161E31
COLOR_CARD_LIGHT = RGBColor(255, 255, 255) # #FFFFFF
COLOR_BORDER_LIGHT = RGBColor(226, 232, 240) # #E2E8F0
COLOR_BORDER_DARK = RGBColor(45, 55, 72)

COLOR_ORANGE_MAIN = RGBColor(249, 115, 22) # #F97316 (Naranja corporativo)
COLOR_ORANGE_DARK = RGBColor(234, 88, 12)  # #EA580C
COLOR_ORANGE_TINT = RGBColor(254, 242, 237)
COLOR_AMBER = RGBColor(217, 119, 6)        # #D97706
COLOR_EMERALD = RGBColor(5, 150, 105)      # #059669
COLOR_EMERALD_BG = RGBColor(240, 253, 244)
COLOR_BLUE = RGBColor(37, 99, 235)         # #2563EB
COLOR_BLUE_BG = RGBColor(239, 246, 255)

COLOR_TEXT_MAIN_DARK = RGBColor(15, 23, 42)  # #0F172A
COLOR_TEXT_MUTED_DARK = RGBColor(71, 85, 105) # #475569
COLOR_TEXT_MAIN_LIGHT = RGBColor(248, 250, 252) # #F8FAFC
COLOR_TEXT_MUTED_LIGHT = RGBColor(148, 163, 184) # #94A3B8

FONT_HEADING = "Arial"
FONT_BODY = "Arial"


def set_solid_background(slide, color):
    """Establece el fondo nativo de la diapositiva sin agregar formas rectangulares superpuestas."""
    background = slide.background
    fill = background.fill
    fill.solid()
    fill.fore_color.rgb = color


def add_header(slide, title, kicker=None, category=None, is_dark=False):
    """Agrega el encabezado unificado de la diapositiva."""
    # Logo pequeño en la esquina superior izquierda
    if LOGO_PATH.exists():
        try:
            slide.shapes.add_picture(str(LOGO_PATH), Inches(0.8), Inches(0.42), width=Inches(0.48), height=Inches(0.48))
        except Exception:
            pass

    # Marca y Categoría superior
    tb_brand = slide.shapes.add_textbox(Inches(1.38), Inches(0.42), Inches(8.0), Inches(0.3))
    tf_brand = tb_brand.text_frame
    tf_brand.word_wrap = True
    p_brand = tf_brand.paragraphs[0]
    p_brand.text = "VykOne ERP"
    p_brand.font.name = FONT_HEADING
    p_brand.font.size = Pt(10)
    p_brand.font.bold = True
    p_brand.font.color.rgb = COLOR_ORANGE_MAIN if not is_dark else COLOR_ORANGE_MAIN

    if category:
        run_cat = p_brand.add_run()
        run_cat.text = f"  ·  {category}"
        run_cat.font.name = FONT_BODY
        run_cat.font.size = Pt(9.5)
        run_cat.font.bold = False
        run_cat.font.color.rgb = COLOR_TEXT_MUTED_LIGHT if is_dark else COLOR_TEXT_MUTED_DARK

    # Título principal y Kicker
    tb_title = slide.shapes.add_textbox(Inches(0.8), Inches(0.95), Inches(11.7), Inches(0.9))
    tf_title = tb_title.text_frame
    tf_title.word_wrap = True
    tf_title.margin_left = tf_title.margin_top = tf_title.margin_right = tf_title.margin_bottom = 0

    if kicker:
        p_kicker = tf_title.paragraphs[0]
        p_kicker.text = kicker.upper()
        p_kicker.font.name = FONT_HEADING
        p_kicker.font.size = Pt(9)
        p_kicker.font.bold = True
        p_kicker.font.color.rgb = COLOR_ORANGE_MAIN
        p_kicker.space_after = Pt(2)
        p_title = tf_title.add_paragraph()
    else:
        p_title = tf_title.paragraphs[0]

    p_title.text = title
    p_title.font.name = FONT_HEADING
    p_title.font.size = Pt(22)
    p_title.font.bold = True
    p_title.font.color.rgb = COLOR_TEXT_MAIN_LIGHT if is_dark else COLOR_TEXT_MAIN_DARK


def add_footer(slide, current_slide, total_slides=12, is_dark=False):
    """Agrega pie de página estandarizado."""
    tb = slide.shapes.add_textbox(Inches(0.8), Inches(7.0), Inches(11.733), Inches(0.3))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_top = tf.margin_right = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.text = "VykCore Automation S.R.L.  ·  VykOne ERP  ·  Ley 32-23 Facturación Electrónica"
    p.font.name = FONT_BODY
    p.font.size = Pt(8)
    p.font.color.rgb = COLOR_TEXT_MUTED_LIGHT if is_dark else COLOR_TEXT_MUTED_DARK

    # Número de diapositiva a la derecha
    tb_num = slide.shapes.add_textbox(Inches(10.5), Inches(7.0), Inches(2.0), Inches(0.3))
    tf_num = tb_num.text_frame
    tf_num.word_wrap = True
    p_num = tf_num.paragraphs[0]
    p_num.alignment = PP_ALIGN.RIGHT
    p_num.text = f"{current_slide:02d} / {total_slides:02d}"
    p_num.font.name = FONT_BODY
    p_num.font.size = Pt(8.5)
    p_num.font.bold = True
    p_num.font.color.rgb = COLOR_ORANGE_MAIN if is_dark else COLOR_TEXT_MUTED_DARK


def add_card(slide, left, top, width, height, bg_color=COLOR_CARD_LIGHT, border_color=COLOR_BORDER_LIGHT):
    """Crea un contenedor tipo tarjeta con borde redondeado."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    shape.fill.solid()
    shape.fill.fore_color.rgb = bg_color
    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1)
    else:
        shape.line.fill.background()
    return shape


def set_notes(slide, notes_text):
    """Asigna notas del presentador a la diapositiva."""
    notes_slide = slide.notes_slide
    text_frame = notes_slide.notes_text_frame
    text_frame.text = notes_text


def build_presentation():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # =========================================================================
    # DIAPOSITIVA 1: PORTADA
    # =========================================================================
    s1 = prs.slides.add_slide(blank_layout)
    set_solid_background(s1, COLOR_BG_DARK)

    # Acento de diseño en la portada
    accent_circ = s1.shapes.add_shape(MSO_SHAPE.OVAL, Inches(9.5), Inches(-1.5), Inches(5.5), Inches(5.5))
    accent_circ.fill.solid()
    accent_circ.fill.fore_color.rgb = RGBColor(22, 78, 99) # Teal / Dark Cyan
    accent_circ.line.fill.background()

    # Logo
    if LOGO_PATH.exists():
        try:
            s1.shapes.add_picture(str(LOGO_PATH), Inches(1.2), Inches(1.2), width=Inches(1.0), height=Inches(1.0))
        except Exception:
            pass

    # Eyebrow
    tb_eye = s1.shapes.add_textbox(Inches(1.2), Inches(2.4), Inches(8.0), Inches(0.4))
    tf_eye = tb_eye.text_frame
    p_eye = tf_eye.paragraphs[0]
    p_eye.text = "SOLUCIONES TECNOLÓGICAS & GESTIÓN FISCAL"
    p_eye.font.name = FONT_HEADING
    p_eye.font.size = Pt(11)
    p_eye.font.bold = True
    p_eye.font.color.rgb = COLOR_ORANGE_MAIN

    # Título Principal
    tb_title = s1.shapes.add_textbox(Inches(1.2), Inches(2.8), Inches(10.0), Inches(1.8))
    tf_title = tb_title.text_frame
    tf_title.word_wrap = True
    p_t1 = tf_title.paragraphs[0]
    p_t1.text = "VykCore y VykOne ERP"
    p_t1.font.name = FONT_HEADING
    p_t1.font.size = Pt(40)
    p_t1.font.bold = True
    p_t1.font.color.rgb = COLOR_TEXT_MAIN_LIGHT

    p_sub = tf_title.add_paragraph()
    p_sub.text = "Soluciones empresariales y el camino hacia la facturación electrónica"
    p_sub.font.name = FONT_BODY
    p_sub.font.size = Pt(18)
    p_sub.font.color.rgb = RGBColor(203, 213, 225)
    p_sub.space_before = Pt(8)

    # Badges / Tarjetas inferiores en la portada
    card_meta = add_card(s1, Inches(1.2), Inches(5.0), Inches(10.8), Inches(1.2), bg_color=RGBColor(18, 24, 38), border_color=COLOR_BORDER_DARK)
    tb_meta = s1.shapes.add_textbox(Inches(1.4), Inches(5.1), Inches(10.4), Inches(1.0))
    tf_meta = tb_meta.text_frame
    tf_meta.word_wrap = True
    p_m = tf_meta.paragraphs[0]
    p_m.text = "MARCO REGULATORIO: LEY 32-23 (DGII)  ·  PLATAFORMA ERP EN LA NUBE  ·  REPÚBLICA DOMINICANA"
    p_m.font.name = FONT_HEADING
    p_m.font.size = Pt(9.5)
    p_m.font.bold = True
    p_m.font.color.rgb = COLOR_ORANGE_MAIN

    p_m2 = tf_meta.add_paragraph()
    p_m2.text = "Presentación ejecutiva para empresarios, contadores y directores de finanzas sobre la modernización de procesos y el proceso de acreditación como emisor electrónico ante la DGII."
    p_m2.font.name = FONT_BODY
    p_m2.font.size = Pt(11)
    p_m2.font.color.rgb = COLOR_TEXT_MUTED_LIGHT
    p_m2.space_before = Pt(4)

    add_footer(s1, 1, 12, is_dark=True)
    set_notes(s1, "Bienvenida a los asistentes. Hoy conoceremos a fondo qué es VykCore y su plataforma insignia VykOne ERP, cómo opera la facturación electrónica bajo la Ley 32-23 y el paso a paso detallado para que cualquier empresa dominicana logre su certificación oficial como emisor electrónico ante la DGII sin contratiempos técnicos.")

    # =========================================================================
    # DIAPOSITIVA 2: ¿QUÉ ES VYKCORE?
    # =========================================================================
    s2 = prs.slides.add_slide(blank_layout)
    set_solid_background(s2, COLOR_BG_LIGHT)
    add_header(s2, "¿Qué es VykCore?", kicker="Identidad Corporativa", category="La Empresa")

    # Tarjeta 1: Propuesta de valor
    add_card(s2, Inches(0.8), Inches(2.0), Inches(5.6), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_c1 = s2.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.2), Inches(3.2))
    tf_c1 = tb_c1.text_frame
    tf_c1.word_wrap = True
    p1 = tf_c1.paragraphs[0]
    p1.text = "Propuesta de Valor & Visión"
    p1.font.size = Pt(15)
    p1.font.bold = True
    p1.font.color.rgb = COLOR_TEXT_MAIN_DARK

    p1_desc = tf_c1.add_paragraph()
    p1_desc.text = "VykCore Automation S.R.L. es una empresa de tecnología y consultoría especializada en automatización operativa y desarrollo de soluciones de software empresarial adaptadas al entorno normativo dominicano.\n\nBusca resolver la fragmentación operativa y el rezago tecnológico de las empresas locales, reemplazando hojas de cálculo dispersas y sistemas aislados por soluciones integradas y seguras."
    p1_desc.font.size = Pt(10.5)
    p1_desc.font.color.rgb = COLOR_TEXT_MUTED_DARK
    p1_desc.space_before = Pt(8)

    # Tarjeta 2: Oferta de Soluciones Confirmadas
    add_card(s2, Inches(6.8), Inches(2.0), Inches(5.7), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_c2 = s2.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(3.2))
    tf_c2 = tb_c2.text_frame
    tf_c2.word_wrap = True
    p2 = tf_c2.paragraphs[0]
    p2.text = "Soluciones & Servicios Confirmados"
    p2.font.size = Pt(15)
    p2.font.bold = True
    p2.font.color.rgb = COLOR_TEXT_MAIN_DARK

    bullets = [
        ("VykOne ERP:", " Plataforma integral de gestión empresarial en la nube para control administrativo, fiscal y financiero."),
        ("Automatización de Procesos:", " Diseño e implementación de flujos de trabajo inteligentes para reducir costos y tiempos manuales."),
        ("Integraciones Cloud & Fiscales:", " Conexión directa y certificada con la DGII para emisión y recepción de comprobantes electrónicos.")
    ]
    for b_title, b_desc in bullets:
        pb = tf_c2.add_paragraph()
        pb.space_before = Pt(8)
        run_b1 = pb.add_run()
        run_b1.text = "• " + b_title
        run_b1.font.bold = True
        run_b1.font.size = Pt(10)
        run_b1.font.color.rgb = COLOR_ORANGE_DARK
        run_b2 = pb.add_run()
        run_b2.text = b_desc
        run_b2.font.size = Pt(10)
        run_b2.font.color.rgb = COLOR_TEXT_MUTED_DARK

    # Banner inferior de diferenciación y enlace oficial
    add_card(s2, Inches(0.8), Inches(5.8), Inches(11.7), Inches(0.95), bg_color=COLOR_BLUE_BG, border_color=RGBColor(191, 219, 254))
    tb_diff = s2.shapes.add_textbox(Inches(1.0), Inches(5.85), Inches(11.3), Inches(0.85))
    tf_diff = tb_diff.text_frame
    tf_diff.word_wrap = True
    p_diff = tf_diff.paragraphs[0]
    p_diff.text = "Diferenciación Clave:"
    p_diff.font.bold = True
    p_diff.font.size = Pt(9.5)
    p_diff.font.color.rgb = COLOR_BLUE
    run_d = p_diff.add_run()
    run_d.text = " VykCore es la empresa tecnológica matriz y desarrolladora. VykOne es su plataforma ERP insignia.\nSitio web oficial: https://vykcore.com"
    run_d.font.bold = False
    run_d.font.color.rgb = COLOR_TEXT_MAIN_DARK

    add_footer(s2, 2, 12)
    set_notes(s2, "Es fundamental entender la distinción entre VykCore y VykOne. VykCore Automation S.R.L. es la empresa tecnológica de base, creadora de soluciones de automatización empresarial en República Dominicana. Su principal producto es VykOne ERP, diseñado específicamente para dar respuesta a los desafíos operativos y normativos del país. Enlace oficial: https://vykcore.com")

    # =========================================================================
    # DIAPOSITIVA 3: ¿QUÉ ES VYKONE?
    # =========================================================================
    s3 = prs.slides.add_slide(blank_layout)
    set_solid_background(s3, COLOR_BG_LIGHT)
    add_header(s3, "¿Qué es VykOne ERP?", kicker="Plataforma de Gestión", category="Producto Insignia")

    cards_s3 = [
        ("Centralización Operativa", "Unifica en un solo entorno digital en la nube la facturación, los inventarios, las compras, la nómina, la contabilidad y el seguimiento de cobros, evitando sistemas aislados.", COLOR_ORANGE_MAIN),
        ("Cumplimiento Fiscal Nativo", "Construido específicamente para la normativa dominicana: preparado para la Ley 32-23 de facturación electrónica (e-CF), retenciones de TSS, retención de ISR y reportes 606/607.", COLOR_EMERALD),
        ("Control y Trazabilidad 360°", "Mantiene la historia completa de cada transacción comercial, con doble ambiente aislado (Sandbox de pruebas y Producción) y segregación de funciones por rol de usuario.", COLOR_BLUE)
    ]

    for idx, (title_c, desc_c, accent_c) in enumerate(cards_s3):
        col_left = Inches(0.8 + idx * 4.0)
        card_obj = add_card(s3, col_left, Inches(2.0), Inches(3.7), Inches(3.4), bg_color=COLOR_CARD_LIGHT)
        
        # Franja de color superior en la tarjeta
        strip = s3.shapes.add_shape(MSO_SHAPE.RECTANGLE, col_left, Inches(2.0), Inches(3.7), Inches(0.08))
        strip.fill.solid()
        strip.fill.fore_color.rgb = accent_c
        strip.line.fill.background()

        tb_card = s3.shapes.add_textbox(col_left + Inches(0.2), Inches(2.3), Inches(3.3), Inches(2.9))
        tf_card = tb_card.text_frame
        tf_card.word_wrap = True
        pt = tf_card.paragraphs[0]
        pt.text = title_c
        pt.font.size = Pt(14)
        pt.font.bold = True
        pt.font.color.rgb = COLOR_TEXT_MAIN_DARK

        pd = tf_card.add_paragraph()
        pd.text = desc_c
        pd.font.size = Pt(10)
        pd.font.color.rgb = COLOR_TEXT_MUTED_DARK
        pd.space_before = Pt(8)

    # Banner inferior con beneficios confirmados y link
    add_card(s3, Inches(0.8), Inches(5.65), Inches(11.7), Inches(1.1), bg_color=COLOR_CARD_LIGHT)
    tb_b3 = s3.shapes.add_textbox(Inches(1.0), Inches(5.75), Inches(11.3), Inches(0.95))
    tf_b3 = tb_b3.text_frame
    tf_b3.word_wrap = True
    pb3 = tf_b3.paragraphs[0]
    pb3.text = "Beneficios Confirmados: "
    pb3.font.bold = True
    pb3.font.size = Pt(10)
    pb3.font.color.rgb = COLOR_ORANGE_MAIN
    run_b3 = pb3.add_run()
    run_b3.text = "Plataforma multiempresa en la nube, acceso seguro sin instalaciones locales, visibilidad en tiempo real de ingresos y gastos, y reducción drástica de errores de cálculo fiscal.\nAcceso directo a la plataforma: https://one.vykcore.com"
    run_b3.font.bold = False
    run_b3.font.color.rgb = COLOR_TEXT_MAIN_DARK

    add_footer(s3, 3, 12)
    set_notes(s3, "VykOne no es un simple programa de facturación o una hoja de cálculo; es un ERP moderno y completo. Su mayor fortaleza radica en que nació pensado para las leyes dominicanas: cada venta registrada alimenta al inventario, genera el comprobante fiscal, actualiza las cuentas por cobrar y contabiliza el asiento sin trabajo manual repetitivo. Enlace: https://one.vykcore.com")

    # =========================================================================
    # DIAPOSITIVA 4: PRINCIPALES MÓDULOS DE VYKONE ERP
    # =========================================================================
    s4 = prs.slides.add_slide(blank_layout)
    set_solid_background(s4, COLOR_BG_LIGHT)
    add_header(s4, "Principales Módulos de VykOne ERP", kicker="Cobertura Funcional", category="Módulos")

    modules = [
        ("Facturación Electrónica (e-CF)", "Emisión, firma criptográfica y validación inmediata de comprobantes fiscales electrónicos ante la DGII en tiempo real.", COLOR_ORANGE_MAIN),
        ("Ventas y Cobros", "Ciclo comercial completo desde cotizaciones hasta cobros, estados de cuenta de clientes y control de cartera por cobrar.", COLOR_ORANGE_MAIN),
        ("Inventario y Almacenes", "Control de existencias multialmacén, transferencias entre depósitos, conteos físicos y costeo valorizado mediante Kardex.", COLOR_EMERALD),
        ("Compras y Bancos", "Gestión de órdenes de compra, cuentas por pagar a proveedores, tesorería y conciliación bancaria automatizada.", COLOR_EMERALD),
        ("Contabilidad", "Generación automática de asientos contables desde la operación, catálogo de cuentas formal y estados financieros al día.", COLOR_BLUE),
        ("Nómina y Recursos Humanos", "Cálculo de nómina con retenciones automáticas de TSS, retención de ISR y cumplimiento de la Ley Laboral 16-92.", COLOR_BLUE),
        ("CRM y Punto de Venta (POS)", "Terminal ágil para venta directa de mostrador con arqueo de caja por turnos y embudo comercial de prospectos.", COLOR_AMBER),
        ("Reportes e Inteligencia", "Tableros de indicadores clave en tiempo real y generación nativa de formatos regulatorios 606, 607 y 608.", COLOR_AMBER),
    ]

    card_w = Inches(2.78)
    card_h = Inches(2.15)
    for idx, (m_name, m_desc, m_color) in enumerate(modules):
        row = idx // 4
        col = idx % 4
        c_left = Inches(0.8 + col * 2.98)
        c_top = Inches(2.0 + row * 2.35)

        add_card(s4, c_left, c_top, card_w, card_h, bg_color=COLOR_CARD_LIGHT)

        # Franja lateral de color
        bar = s4.shapes.add_shape(MSO_SHAPE.RECTANGLE, c_left, c_top, Inches(0.08), card_h)
        bar.fill.solid()
        bar.fill.fore_color.rgb = m_color
        bar.line.fill.background()

        tb_m = s4.shapes.add_textbox(c_left + Inches(0.18), c_top + Inches(0.15), card_w - Inches(0.28), card_h - Inches(0.25))
        tf_m = tb_m.text_frame
        tf_m.word_wrap = True
        pm = tf_m.paragraphs[0]
        pm.text = m_name
        pm.font.size = Pt(11)
        pm.font.bold = True
        pm.font.color.rgb = COLOR_TEXT_MAIN_DARK

        pm_desc = tf_m.add_paragraph()
        pm_desc.text = m_desc
        pm_desc.font.size = Pt(8.5)
        pm_desc.font.color.rgb = COLOR_TEXT_MUTED_DARK
        pm_desc.space_before = Pt(4)

    add_footer(s4, 4, 12)
    set_notes(s4, "Cada módulo de VykOne resuelve un área neurálgica de la empresa. Facturación e Inventario operan como los motores centrales, mientras que Contabilidad y Nómina se alimentan de la misma información transaccional. Esto elimina el reproceso de digitar facturas en un sistema contable separado a final de mes.")

    # =========================================================================
    # DIAPOSITIVA 5: ¿CÓMO FUNCIONA LA FACTURACIÓN ELECTRÓNICA?
    # =========================================================================
    s5 = prs.slides.add_slide(blank_layout)
    set_solid_background(s5, COLOR_BG_LIGHT)
    add_header(s5, "¿Cómo Funciona la Facturación Electrónica?", kicker="Flujo de Emisión e-CF", category="Facturación")

    flow_steps = [
        ("01", "Registro del Cliente", "Captura de datos con validación en vivo del RNC o cédula ante la base de datos de la DGII."),
        ("02", "Cálculo Fiscal", "Desglose automático de bases gravadas, tasas de ITBIS (18%, 16%, exento) y retenciones de ley."),
        ("03", "Firma Digital XML", "Generación del XML oficial firmado criptográficamente con el certificado digital X.509 (.p12)."),
        ("04", "Envío a la DGII", "Transmisión segura mediante API REST directa para recepción y procesamiento en milisegundos."),
        ("05", "Timbre & Entrega", "Recepción del TrackID de la DGII, código QR fiscal y entrega al cliente en PDF y XML.")
    ]

    step_w = Inches(2.22)
    step_h = Inches(3.1)
    for idx, (s_num, s_title, s_desc) in enumerate(flow_steps):
        s_left = Inches(0.8 + idx * 2.38)
        s_top = Inches(2.0)

        add_card(s5, s_left, s_top, step_w, step_h, bg_color=COLOR_CARD_LIGHT)

        # Círculo con número
        c_circle = s5.shapes.add_shape(MSO_SHAPE.OVAL, s_left + Inches(0.18), s_top + Inches(0.18), Inches(0.48), Inches(0.48))
        c_circle.fill.solid()
        c_circle.fill.fore_color.rgb = COLOR_ORANGE_MAIN
        c_circle.line.fill.background()

        tb_num = s5.shapes.add_textbox(s_left + Inches(0.18), s_top + Inches(0.18), Inches(0.48), Inches(0.48))
        tf_num = tb_num.text_frame
        p_num = tf_num.paragraphs[0]
        p_num.alignment = PP_ALIGN.CENTER
        p_num.text = s_num
        p_num.font.name = FONT_HEADING
        p_num.font.size = Pt(11)
        p_num.font.bold = True
        p_num.font.color.rgb = COLOR_TEXT_MAIN_LIGHT

        # Textos del paso
        tb_step = s5.shapes.add_textbox(s_left + Inches(0.18), s_top + Inches(0.8), step_w - Inches(0.36), step_h - Inches(0.95))
        tf_step = tb_step.text_frame
        tf_step.word_wrap = True
        p_st = tf_step.paragraphs[0]
        p_st.text = s_title
        p_st.font.size = Pt(11.5)
        p_st.font.bold = True
        p_st.font.color.rgb = COLOR_TEXT_MAIN_DARK

        p_sd = tf_step.add_paragraph()
        p_sd.text = s_desc
        p_sd.font.size = Pt(8.5)
        p_sd.font.color.rgb = COLOR_TEXT_MUTED_DARK
        p_sd.space_before = Pt(6)

    # Nota destacada inferior
    add_card(s5, Inches(0.8), Inches(5.4), Inches(11.7), Inches(1.3), bg_color=COLOR_ORANGE_TINT, border_color=RGBColor(254, 215, 170))
    tb_fn = s5.shapes.add_textbox(Inches(1.0), Inches(5.5), Inches(11.3), Inches(1.1))
    tf_fn = tb_fn.text_frame
    tf_fn.word_wrap = True
    p_fn = tf_fn.paragraphs[0]
    p_fn.text = "Validaciones Oficiales y Manejo de Contingencia:"
    p_fn.font.bold = True
    p_fn.font.size = Pt(10)
    p_fn.font.color.rgb = COLOR_ORANGE_DARK
    p_fn2 = tf_fn.add_paragraph()
    p_fn2.text = "• Las respuestas y estados finales (Aceptado, En Proceso o Rechazado) dependen exclusivamente de las validaciones normativas de la DGII.\n• Si el servicio fiscal de la DGII presenta intermitencia, VykOne activa su modo de contingencia, almacenando la transacción para su sincronización y timbrado posterior en cuanto el servicio se restablece."
    p_fn2.font.size = Pt(9)
    p_fn2.font.color.rgb = COLOR_TEXT_MAIN_DARK
    p_fn2.space_before = Pt(2)

    add_footer(s5, 5, 12)
    set_notes(s5, "El flujo de facturación electrónica en VykOne toma apenas fracciones de segundo. El usuario factura como de costumbre; el sistema valida el RNC del cliente, desglosa los impuestos, firma el XML en segundo plano y se conecta con la DGII. El cliente final recibe su comprobante fiscal con su código QR oficial.")

    # =========================================================================
    # DIAPOSITIVA 6: CONTROL DE INVENTARIO
    # =========================================================================
    s6 = prs.slides.add_slide(blank_layout)
    set_solid_background(s6, COLOR_BG_LIGHT)
    add_header(s6, "Control Integral de Inventario y Almacenes", kicker="Operación y Logística", category="Inventario")

    # Tarjeta izquierda: Capacidades de inventario
    add_card(s6, Inches(0.8), Inches(2.0), Inches(5.7), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_ic = s6.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.3), Inches(3.2))
    tf_ic = tb_ic.text_frame
    tf_ic.word_wrap = True
    pi = tf_ic.paragraphs[0]
    pi.text = "Capacidades Operativas Clave"
    pi.font.size = Pt(14)
    pi.font.bold = True
    pi.font.color.rgb = COLOR_TEXT_MAIN_DARK

    inv_points = [
        ("Existencias Multialmacén:", " Control de stock separado por sucursal, depósito y ubicación física."),
        ("Movimientos Auditables:", " Entradas por compras, transferencias entre depósitos y salidas por ventas."),
        ("Conteos Físicos y Ajustes:", " Herramientas para conciliar el inventario teórico con las existencias reales."),
        ("Kardex Valorizado Continuo:", " Métodos de costeo deterministas: FIFO / PEPS, Promedio Ponderado y Estándar."),
        ("Control de Stock Negativo:", " Bloqueo estricto del sistema para evitar sacar mercancía inexistente.")
    ]
    for b_t, b_d in inv_points:
        pbi = tf_ic.add_paragraph()
        pbi.space_before = Pt(5)
        run_i1 = pbi.add_run()
        run_i1.text = "• " + b_t
        run_i1.font.bold = True
        run_i1.font.size = Pt(9)
        run_i1.font.color.rgb = COLOR_ORANGE_DARK
        run_i2 = pbi.add_run()
        run_i2.text = b_d
        run_i2.font.size = Pt(9)
        run_i2.font.color.rgb = COLOR_TEXT_MUTED_DARK

    # Tarjeta derecha: Flujo de vida del producto
    add_card(s6, Inches(6.8), Inches(2.0), Inches(5.7), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_flow = s6.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(3.2))
    tf_flow = tb_flow.text_frame
    tf_flow.word_wrap = True
    pf = tf_flow.paragraphs[0]
    pf.text = "Recorrido Visual del Producto"
    pf.font.size = Pt(14)
    pf.font.bold = True
    pf.font.color.rgb = COLOR_TEXT_MAIN_DARK

    flow_boxes = [
        ("1. Entrada por Compra", "Recepción de mercancía contra orden de compra. Aumento de existencias y registro de la capa de costo en el Kardex."),
        ("2. Custodia en Almacén", "Monitoreo continuo de existencias, alertas de stock mínimo para reorden y transferencias internas seguras."),
        ("3. Salida Valorizada (Venta)", "Deducción automática de stock en el comprobante fiscal o POS, calculando el costo real de venta exacto.")
    ]
    for f_t, f_d in flow_boxes:
        pbf = tf_flow.add_paragraph()
        pbf.space_before = Pt(8)
        run_f1 = pbf.add_run()
        run_f1.text = f_t + "\n"
        run_f1.font.bold = True
        run_f1.font.size = Pt(10)
        run_f1.font.color.rgb = COLOR_BLUE
        run_f2 = pbf.add_run()
        run_f2.text = f_d
        run_f2.font.size = Pt(8.5)
        run_f2.font.color.rgb = COLOR_TEXT_MUTED_DARK

    # Nota inferior
    add_card(s6, Inches(0.8), Inches(5.8), Inches(11.7), Inches(0.95), bg_color=COLOR_CARD_LIGHT)
    tb_inote = s6.shapes.add_textbox(Inches(1.0), Inches(5.85), Inches(11.3), Inches(0.85))
    tf_inote = tb_inote.text_frame
    tf_inote.word_wrap = True
    pin = tf_inote.paragraphs[0]
    pin.text = "Regla de Negocio & Disponibilidad:"
    pin.font.bold = True
    pin.font.size = Pt(9.5)
    pin.font.color.rgb = COLOR_EMERALD
    run_in = pin.add_run()
    run_in.text = " VykOne separa estrictamente bienes físicos de servicios (los servicios no mueven inventario). Las capacidades avanzadas de multialmacén, alertas de vencimiento y costeo FIFO están sujetas a la configuración y plan contratado por la empresa."
    run_in.font.bold = False
    run_in.font.color.rgb = COLOR_TEXT_MUTED_DARK

    add_footer(s6, 6, 12)
    set_notes(s6, "El inventario de VykOne está estrechamente integrado con las ventas y compras. Al vender un artículo físico, el sistema descuenta automáticamente el stock del almacén seleccionado y calcula el costo de venta mediante Kardex continuo (FIFO o Promedio). Además, impide ventas con stock negativo para mantener la veracidad contable.")

    # =========================================================================
    # DIAPOSITIVA 7: CERTIFICACIÓN DGII: VISIÓN GENERAL
    # =========================================================================
    s7 = prs.slides.add_slide(blank_layout)
    set_solid_background(s7, COLOR_BG_LIGHT)
    add_header(s7, "Certificación DGII: Visión General del Proceso", kicker="Procedimiento Oficial Ley 32-23", category="Certificación")

    phases = [
        ("Fase 1: Postulación", "Paso 1", "Solicitud formal en la Oficina Virtual (OFV) de la DGII y presentación del XML inicial firmado digitalmente para acceder a CerteCF.", COLOR_ORANGE_MAIN),
        ("Fase 2: Set de Pruebas", "Pasos 2 al 6", "Generación y validación de facturas electrónicas de prueba (E31, E32, E34, E45, RFCE), aprobación comercial y Representación Impresa.", COLOR_EMERALD),
        ("Fase 3: Conectividad", "Pasos 7 al 12", "Registro de URLs seguras en la DGII y validación de recepción de e-CF externos y acuses de aprobación comercial en la nube.", COLOR_BLUE),
        ("Fase 4: Autorización", "Pasos 13 al 15", "Declaración Jurada firmada por el representante legal, auditoría final de estatus tributario y emisión de resolución de la DGII.", COLOR_AMBER)
    ]

    card_pw = Inches(2.78)
    card_ph = Inches(3.2)
    for idx, (p_title, p_steps, p_desc, p_color) in enumerate(phases):
        p_left = Inches(0.8 + idx * 2.98)
        p_top = Inches(2.0)

        add_card(s7, p_left, p_top, card_pw, card_ph, bg_color=COLOR_CARD_LIGHT)

        # Franja superior
        f_bar = s7.shapes.add_shape(MSO_SHAPE.RECTANGLE, p_left, p_top, card_pw, Inches(0.08))
        f_bar.fill.solid()
        f_bar.fill.fore_color.rgb = p_color
        f_bar.line.fill.background()

        tb_ph = s7.shapes.add_textbox(p_left + Inches(0.2), p_top + Inches(0.2), card_pw - Inches(0.4), card_ph - Inches(0.4))
        tf_ph = tb_ph.text_frame
        tf_ph.word_wrap = True
        pp_title = tf_ph.paragraphs[0]
        pp_title.text = p_title
        pp_title.font.size = Pt(13)
        pp_title.font.bold = True
        pp_title.font.color.rgb = COLOR_TEXT_MAIN_DARK

        pp_steps = tf_ph.add_paragraph()
        pp_steps.text = p_steps.upper()
        pp_steps.font.size = Pt(9)
        pp_steps.font.bold = True
        pp_steps.font.color.rgb = p_color
        pp_steps.space_before = Pt(2)

        pp_desc = tf_ph.add_paragraph()
        pp_desc.text = p_desc
        pp_desc.font.size = Pt(8.5)
        pp_desc.font.color.rgb = COLOR_TEXT_MUTED_DARK
        pp_desc.space_before = Pt(8)

    # Línea de tiempo visual y fuente oficial
    add_card(s7, Inches(0.8), Inches(5.45), Inches(11.7), Inches(1.25), bg_color=COLOR_CARD_LIGHT)
    tb_tl = s7.shapes.add_textbox(Inches(1.0), Inches(5.55), Inches(11.3), Inches(1.05))
    tf_tl = tb_tl.text_frame
    tf_tl.word_wrap = True
    ptl = tf_tl.paragraphs[0]
    ptl.text = "Línea de Tiempo Oficial de los 15 Pasos Normativos:"
    ptl.font.bold = True
    ptl.font.size = Pt(9.5)
    ptl.font.color.rgb = COLOR_TEXT_MAIN_DARK

    ptl2 = tf_tl.add_paragraph()
    ptl2.text = "[P1. Registro] ──▶ [P2. Datos e-CF] ──▶ [P3. Aprobación ACECF] ──▶ [P4. Simulación] ──▶ [P5. RI PDF] ──▶ [P6. Validación RI] ──▶\n[P7. URLs Prueba] ──▶ [P8. Inicio Recepción] ──▶ [P9. Recepción e-CF] ──▶ [P10-11. ACECF] ──▶ [P12. URLs Prod] ──▶ [P13. Declaración] ──▶ [P14. Estatus] ──▶ [P15. Go-Live]"
    ptl2.font.size = Pt(7.8)
    ptl2.font.bold = True
    ptl2.font.color.rgb = COLOR_ORANGE_DARK
    ptl2.space_before = Pt(3)

    ptl3 = tf_tl.add_paragraph()
    ptl3.text = "Fuente principal: Guía oficial de certificación de la Dirección General de Impuestos Internos (DGII). La duración depende de los tiempos de revisión de la administración tributaria."
    ptl3.font.size = Pt(7.5)
    ptl3.font.color.rgb = COLOR_TEXT_MUTED_DARK
    ptl3.space_before = Pt(2)

    add_footer(s7, 7, 12)
    set_notes(s7, "Convertirse en emisor electrónico no es una simple configuración; es un proceso formal de homologación exigido por la DGII que consta de 15 pasos agrupados en 4 fases. Ningún proveedor puede prometer una fecha mágica de aprobación porque la DGII es quien audita cada paso, pero un sistema como VykOne automatiza todas las tareas técnicas para no perder tiempo.")

    # =========================================================================
    # DIAPOSITIVA 8: REQUISITOS PARA COMENZAR
    # =========================================================================
    s8 = prs.slides.add_slide(blank_layout)
    set_solid_background(s8, COLOR_BG_LIGHT)
    add_header(s8, "Requisitos Previos para Iniciar la Certificación", kicker="Lista de Preparación", category="Requisitos")

    reqs = [
        ("1. RNC Activo y Cumplimiento", "Estar en estatus Activo y en Régimen Ordinario, al día en todas las obligaciones fiscales (declaraciones juradas IT-1, IR-1 o IR-2 al día, sin omisiones ni deudas en cobro)."),
        ("2. Clave Oficina Virtual (OFV)", "Acceso activo y vigente con usuario y contraseña al portal web de la Oficina Virtual de la DGII con privilegios de administración fiscal."),
        ("3. Representante Legal Registrado", "Los datos de la persona física o apoderado legal deben coincidir con la información oficial registrada en el padrón tributario de la DGII."),
        ("4. Certificado de Firma Digital (.p12)", "Certificado digital válido para procesos tributarios emitido a nombre del representante legal por una entidad autorizada por INDOTEL, junto con su contraseña.")
    ]

    card_rw = Inches(5.7)
    card_rh = Inches(1.65)
    for idx, (r_title, r_desc) in enumerate(reqs):
        row = idx // 2
        col = idx % 2
        r_left = Inches(0.8 + col * 6.0)
        r_top = Inches(2.0 + row * 1.85)

        add_card(s8, r_left, r_top, card_rw, card_rh, bg_color=COLOR_CARD_LIGHT)

        tb_r = s8.shapes.add_textbox(r_left + Inches(0.25), r_top + Inches(0.18), card_rw - Inches(0.45), card_rh - Inches(0.3))
        tf_r = tb_r.text_frame
        tf_r.word_wrap = True
        pr_title = tf_r.paragraphs[0]
        pr_title.text = r_title
        pr_title.font.size = Pt(12)
        pr_title.font.bold = True
        pr_title.font.color.rgb = COLOR_TEXT_MAIN_DARK

        pr_desc = tf_r.add_paragraph()
        pr_desc.text = r_desc
        pr_desc.font.size = Pt(8.5)
        pr_desc.font.color.rgb = COLOR_TEXT_MUTED_DARK
        pr_desc.space_before = Pt(3)

    # Tarjeta explicativa sobre Firma Digital y Proveedores
    add_card(s8, Inches(0.8), Inches(5.75), Inches(11.7), Inches(1.0), bg_color=COLOR_BLUE_BG, border_color=RGBColor(191, 219, 254))
    tb_fd = s8.shapes.add_textbox(Inches(1.0), Inches(5.82), Inches(11.3), Inches(0.85))
    tf_fd = tb_fd.text_frame
    tf_fd.word_wrap = True
    p_fd = tf_fd.paragraphs[0]
    p_fd.text = "¿Para qué sirve el Certificado Digital y dónde adquirirlo?"
    p_fd.font.bold = True
    p_fd.font.size = Pt(9.5)
    p_fd.font.color.rgb = COLOR_BLUE

    p_fd2 = tf_fd.add_paragraph()
    p_fd2.text = "Es la firma criptográfica que otorga validez legal, autenticidad e inalterabilidad a cada comprobante emitido.\nProveedores acreditados por INDOTEL documentados: DigiFirma (Cámara de Comercio de Santo Domingo) y Avansi. (Aclaración: El contribuyente debe verificar las entidades acreditadas y opciones vigentes al momento de su solicitud)."
    p_fd2.font.size = Pt(8.5)
    p_fd2.font.color.rgb = COLOR_TEXT_MAIN_DARK
    p_fd2.space_before = Pt(2)

    add_footer(s8, 8, 12)
    set_notes(s8, "Antes de iniciar el proceso técnico, el contribuyente debe asegurarse de tener estos cuatro requisitos en orden. La firma digital debe ser de Persona Física para Procedimientos Tributarios a nombre del representante legal. Recomendamos tramitarla con tiempo a través de DigiFirma o Avansi.")

    # =========================================================================
    # DIAPOSITIVA 9: ¿CÓMO AYUDA VYKONE EN LA CERTIFICACIÓN?
    # =========================================================================
    s9 = prs.slides.add_slide(blank_layout)
    set_solid_background(s9, COLOR_BG_LIGHT)
    add_header(s9, "¿Cómo Ayuda VykOne en la Certificación?", kicker="Facilitación Técnica", category="VykOne & DGII")

    # Columna 1: Lo que resuelve VykOne automáticamente
    add_card(s9, Inches(0.8), Inches(2.0), Inches(5.7), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_h1 = s9.shapes.add_textbox(Inches(1.0), Inches(2.2), Inches(5.3), Inches(3.2))
    tf_h1 = tb_h1.text_frame
    tf_h1.word_wrap = True
    ph1 = tf_h1.paragraphs[0]
    ph1.text = "Tareas Técnicas que VykOne Facilita"
    ph1.font.size = Pt(13)
    ph1.font.bold = True
    ph1.font.color.rgb = COLOR_EMERALD

    v_tasks = [
        "Firma automática del XML de postulación inicial.",
        "Procesamiento del archivo Excel oficial de prueba de la DGII.",
        "Generación y transmisión de los comprobantes electrónicos de prueba.",
        "Generación y envío automático de respuestas comerciales ACECF.",
        "Generación de la Representación Impresa (PDF) con QR y código de seguridad.",
        "Endpoints cloud preconfigurados para recepción de e-CF externos.",
        "Generación y firmado del XML de Declaración Jurada (Paso 13)."
    ]
    for vt in v_tasks:
        pvt = tf_h1.add_paragraph()
        pvt.space_before = Pt(3)
        run_v = pvt.add_run()
        run_v.text = "✓ " + vt
        run_v.font.size = Pt(8.5)
        run_v.font.color.rgb = COLOR_TEXT_MUTED_DARK

    # Columna 2: Responsabilidades del Contribuyente
    add_card(s9, Inches(6.8), Inches(2.0), Inches(5.7), Inches(3.6), bg_color=COLOR_CARD_LIGHT)
    tb_h2 = s9.shapes.add_textbox(Inches(7.0), Inches(2.2), Inches(5.3), Inches(3.2))
    tf_h2 = tb_h2.text_frame
    tf_h2.word_wrap = True
    ph2 = tf_h2.paragraphs[0]
    ph2.text = "Responsabilidades del Contribuyente"
    ph2.font.size = Pt(13)
    ph2.font.bold = True
    ph2.font.color.rgb = COLOR_BLUE

    c_tasks = [
        "Solicitar el ingreso al proceso en la Oficina Virtual (OFV).",
        "Adquirir y custodiar el certificado digital .p12 y su contraseña.",
        "Cargar el XML de postulación firmado en el portal de la DGII.",
        "Adjuntar los PDFs de Representación Impresa en el portal fiscal.",
        "Mantener al día el cumplimiento de todas las obligaciones tributarias.",
        "Firmar legalmente la Declaración Jurada formal (Paso 13).",
        "Solicitar los rangos de secuencias e-NCF una vez autorizado."
    ]
    for ct in c_tasks:
        pct = tf_h2.add_paragraph()
        pct.space_before = Pt(3)
        run_c = pct.add_run()
        run_c.text = "• " + ct
        run_c.font.size = Pt(8.5)
        run_c.font.color.rgb = COLOR_TEXT_MUTED_DARK

    # Nota destacada OBLIGATORIA
    add_card(s9, Inches(0.8), Inches(5.8), Inches(11.7), Inches(0.95), bg_color=COLOR_ORANGE_TINT, border_color=RGBColor(254, 215, 170))
    tb_discl = s9.shapes.add_textbox(Inches(1.0), Inches(5.85), Inches(11.3), Inches(0.85))
    tf_discl = tb_discl.text_frame
    tf_discl.word_wrap = True
    p_dis = tf_discl.paragraphs[0]
    p_dis.text = "Nota Destacada:"
    p_dis.font.bold = True
    p_dis.font.size = Pt(9.5)
    p_dis.font.color.rgb = COLOR_ORANGE_DARK
    run_dis = p_dis.add_run()
    run_dis.text = " “VykOne facilita el proceso técnico; la DGII es quien evalúa y concede la autorización”.\nEl software automatiza la confección de archivos y la comunicación por API, pero la validez fiscal y aprobación definitiva corresponden a la administración tributaria."
    run_dis.font.bold = False
    run_dis.font.color.rgb = COLOR_TEXT_MAIN_DARK

    add_footer(s9, 9, 12)
    set_notes(s9, "Esta diapositiva delimita con total transparencia el alcance: VykOne realiza el 95% del esfuerzo técnico complejo (cálculo de impuestos, construcción de XMLs, firmado criptográfico y comunicación por API). El contribuyente solo debe ingresar a su Oficina Virtual para solicitar la postulación y suministrar su certificado digital.")

    # =========================================================================
    # DIAPOSITIVA 10: LAS CUATRO FASES EXPLICADAS
    # =========================================================================
    s10 = prs.slides.add_slide(blank_layout)
    set_solid_background(s10, COLOR_BG_LIGHT)
    add_header(s10, "Las Cuatro Fases de Certificación al Detalle", kicker="Metodología de Aprobación", category="Procedimiento")

    phase_details = [
        ("Fase 1: Postulación", "Paso 1: Registrado", "El contribuyente solicita el ingreso en su Oficina Virtual de la DGII. Se genera el archivo postulacion.xml, se firma digitalmente con el certificado .p12 y se envía al portal de certificación para obtener acceso al ambiente de pruebas CerteCF.", COLOR_ORANGE_MAIN),
        ("Fase 2: Set de Pruebas", "Pasos 2 al 6: Emisión & RI", "Procesamiento del Excel entregado por la DGII. Emisión de comprobantes e-CF (E31, E32, E34, E45, RFCE), pruebas de aprobación comercial (ACECF), simulación transaccional y validación de Representación Impresa (PDF con código QR).", COLOR_EMERALD),
        ("Fase 3: Conectividad", "Pasos 7 al 12: Servicios Web", "Registro formal de las URLs seguras provistas por VykOne para recepción de e-CF y respuestas comerciales. Validación de acuses de recibo en la nube y registro posterior de las URLs definitivas de producción.", COLOR_BLUE),
        ("Fase 4: Autorización", "Pasos 13 al 15: Pase a Producción", "El representante legal presenta la Declaración Jurada firmada digitalmente confirmando la integridad del proceso. La DGII realiza la auditoría de estatus y emite la resolución formal acreditando a la empresa como emisor electrónico.", COLOR_AMBER)
    ]

    card_dw = Inches(2.78)
    card_dh = Inches(4.7)
    for idx, (d_title, d_sub, d_body, d_col) in enumerate(phase_details):
        d_left = Inches(0.8 + idx * 2.98)
        d_top = Inches(2.0)

        add_card(s10, d_left, d_top, card_dw, card_dh, bg_color=COLOR_CARD_LIGHT)

        # Franja superior
        f_top = s10.shapes.add_shape(MSO_SHAPE.RECTANGLE, d_left, d_top, card_dw, Inches(0.08))
        f_top.fill.solid()
        f_top.fill.fore_color.rgb = d_col
        f_top.line.fill.background()

        tb_dt = s10.shapes.add_textbox(d_left + Inches(0.2), d_top + Inches(0.2), card_dw - Inches(0.4), card_dh - Inches(0.4))
        tf_dt = tb_dt.text_frame
        tf_dt.word_wrap = True
        p_dt = tf_dt.paragraphs[0]
        p_dt.text = d_title
        p_dt.font.size = Pt(12)
        p_dt.font.bold = True
        p_dt.font.color.rgb = COLOR_TEXT_MAIN_DARK

        p_ds = tf_dt.add_paragraph()
        p_ds.text = d_sub
        p_ds.font.size = Pt(9)
        p_ds.font.bold = True
        p_ds.font.color.rgb = d_col
        p_ds.space_before = Pt(2)

        p_db = tf_dt.add_paragraph()
        p_db.text = d_body
        p_db.font.size = Pt(8.5)
        p_db.font.color.rgb = COLOR_TEXT_MUTED_DARK
        p_db.space_before = Pt(8)

    add_footer(s10, 10, 12)
    set_notes(s10, "Al desglosar las cuatro fases, vemos cómo cada una cumple un propósito: la Fase 1 valida la identidad jurídica del contribuyente; la Fase 2 valida que el sistema calcule y emita comprobantes fiscales exactos; la Fase 3 valida la recepción de documentos de proveedores; y la Fase 4 formaliza el compromiso legal para otorgar la luz verde.")

    # =========================================================================
    # DIAPOSITIVA 11: ¿QUÉ HACER DESPUÉS DE OBTENER LA AUTORIZACIÓN?
    # =========================================================================
    s11 = prs.slides.add_slide(blank_layout)
    set_solid_background(s11, COLOR_BG_LIGHT)
    add_header(s11, "¿Qué Hacer Después de Obtener la Autorización?", kicker="Puesta en Marcha (Go-Live)", category="Post-Certificación")

    steps_post = [
        ("Paso 1: Solicitar Rangos e-NCF", "Acceder a la Oficina Virtual (OFV) de la DGII y solicitar los rangos de secuencias electrónicas requeridas: E31 (crédito fiscal), E32 (consumo), E33/E34 (notas débito/crédito), E45 (gubernamental), etc."),
        ("Paso 2: Registrar en VykOne", "En VykOne ingresar a: Configuración → Secuencias Fiscales. Registrar los tipos autorizados, rangos numéricos otorgados por la DGII y sus fechas de vencimiento."),
        ("Paso 3: Verificar Parámetros", "Confirmar que el certificado digital .p12 continúe vigente, revisar los datos de encabezado de la empresa y asegurar la correcta asignación de tasas de ITBIS en productos."),
        ("Paso 4: Primera Emisión Real", "Emitir el primer comprobante en el ambiente de producción desde el módulo de Ventas o Punto de Venta (POS) y verificar su recepción con TrackID exitoso de la DGII.")
    ]

    for idx, (sp_title, sp_desc) in enumerate(steps_post):
        row = idx // 2
        col = idx % 2
        sp_left = Inches(0.8 + col * 6.0)
        sp_top = Inches(2.0 + row * 1.85)

        add_card(s11, sp_left, sp_top, Inches(5.7), Inches(1.65), bg_color=COLOR_CARD_LIGHT)

        tb_sp = s11.shapes.add_textbox(sp_left + Inches(0.25), sp_top + Inches(0.18), Inches(5.2), Inches(1.3))
        tf_sp = tb_sp.text_frame
        tf_sp.word_wrap = True
        psp_t = tf_sp.paragraphs[0]
        psp_t.text = sp_title
        psp_t.font.size = Pt(12)
        psp_t.font.bold = True
        psp_t.font.color.rgb = COLOR_TEXT_MAIN_DARK

        psp_d = tf_sp.add_paragraph()
        psp_d.text = sp_desc
        psp_d.font.size = Pt(8.5)
        psp_d.font.color.rgb = COLOR_TEXT_MUTED_DARK
        psp_d.space_before = Pt(3)

    # Aclaración sobre autorización vs configuración
    add_card(s11, Inches(0.8), Inches(5.75), Inches(11.7), Inches(1.0), bg_color=COLOR_EMERALD_BG, border_color=RGBColor(167, 243, 208))
    tb_post_note = s11.shapes.add_textbox(Inches(1.0), Inches(5.82), Inches(11.3), Inches(0.85))
    tf_post_note = tb_post_note.text_frame
    tf_post_note.word_wrap = True
    p_pn = tf_post_note.paragraphs[0]
    p_pn.text = "Aclaración Operativa Importante:"
    p_pn.font.bold = True
    p_pn.font.size = Pt(9.5)
    p_pn.font.color.rgb = COLOR_EMERALD

    p_pn2 = tf_post_note.add_paragraph()
    p_pn2.text = "Obtener la autorización de la DGII y configurar correctamente la operación en el sistema son etapas distintas y complementarias. La resolución habilita legalmente a la empresa, pero es indispensable cargar las secuencias autorizadas en VykOne para iniciar la facturación formal."
    p_pn2.font.size = Pt(8.5)
    p_pn2.font.color.rgb = COLOR_TEXT_MAIN_DARK
    p_pn2.space_before = Pt(2)

    add_footer(s11, 11, 12)
    set_notes(s11, "Obtener la certificación del Paso 15 es un gran hito, pero no significa que ya estés facturando. El día después, el cliente debe entrar a su OFV para pedir sus secuencias e-NCF y registrarlas en VykOne en la ruta Configuración → Secuencias Fiscales. A partir de ese momento, cada venta emitida tiene plena validez fiscal.")

    # =========================================================================
    # DIAPOSITIVA 12: CIERRE Y PRÓXIMOS PASOS
    # =========================================================================
    s12 = prs.slides.add_slide(blank_layout)
    set_solid_background(s12, COLOR_BG_DARK)
    add_header(s12, "Prepara tu Empresa para la Facturación Electrónica", kicker="El Futuro Digital de tu Negocio", category="Cierre", is_dark=True)

    pillars = [
        ("1. Conocer VykOne ERP", "Explora la plataforma en ambiente de pruebas (sandbox) para familiarizar a tu equipo con los flujos de trabajo sin riesgo fiscal."),
        ("2. Identificar Necesidades", "Determina los módulos prioritarios según el giro de tu empresa: facturación, inventario multialmacén, POS o nómina."),
        ("3. Revisar Requisitos", "Valida que tu RNC esté al día con la DGII y tramita con anticipación tu Certificado Digital con su respectiva contraseña."),
        ("4. Certificación Acompañada", "Ejecuta los 15 pasos de homologación de la DGII con el respaldo técnico y metodológico del equipo de VykCore.")
    ]

    card_cw = Inches(2.78)
    card_ch = Inches(2.9)
    for idx, (c_t, c_d) in enumerate(pillars):
        c_left = Inches(0.8 + idx * 2.98)
        c_top = Inches(2.0)

        add_card(s12, c_left, c_top, card_cw, card_ch, bg_color=COLOR_CARD_DARK, border_color=COLOR_BORDER_DARK)

        # Franja superior naranja
        c_top_strip = s12.shapes.add_shape(MSO_SHAPE.RECTANGLE, c_left, c_top, card_cw, Inches(0.08))
        c_top_strip.fill.solid()
        c_top_strip.fill.fore_color.rgb = COLOR_ORANGE_MAIN
        c_top_strip.line.fill.background()

        tb_c = s12.shapes.add_textbox(c_left + Inches(0.2), c_top + Inches(0.2), card_cw - Inches(0.4), card_ch - Inches(0.4))
        tf_c = tb_c.text_frame
        tf_c.word_wrap = True
        pc_t = tf_c.paragraphs[0]
        pc_t.text = c_t
        pc_t.font.size = Pt(12)
        pc_t.font.bold = True
        pc_t.font.color.rgb = COLOR_ORANGE_MAIN

        pc_d = tf_c.add_paragraph()
        pc_d.text = c_d
        pc_d.font.size = Pt(8.5)
        pc_d.font.color.rgb = COLOR_TEXT_MUTED_LIGHT
        pc_d.space_before = Pt(6)

    # Banner de Enlaces y Contacto Oficial
    add_card(s12, Inches(0.8), Inches(5.15), Inches(11.7), Inches(1.5), bg_color=RGBColor(18, 24, 38), border_color=COLOR_BORDER_DARK)
    tb_cont = s12.shapes.add_textbox(Inches(1.0), Inches(5.25), Inches(11.3), Inches(1.3))
    tf_cont = tb_cont.text_frame
    tf_cont.word_wrap = True
    p_call = tf_cont.paragraphs[0]
    p_call.text = "¡Da el salto a la facturación electrónica sin complicaciones!"
    p_call.font.bold = True
    p_call.font.size = Pt(13)
    p_call.font.color.rgb = COLOR_TEXT_MAIN_LIGHT

    p_links = tf_cont.add_paragraph()
    p_links.text = "• Sitio web institucional: https://vykcore.com    • Plataforma ERP: https://one.vykcore.com\nTe invitamos a solicitar una demostración guiada del sistema y coordinar tu proceso de habilitación fiscal ante la DGII."
    p_links.font.size = Pt(9.5)
    p_links.font.color.rgb = COLOR_ORANGE_MAIN
    p_links.space_before = Pt(4)

    p_sources = tf_cont.add_paragraph()
    p_sources.text = "Fuentes de información: Portal oficial DGII (Ley 32-23), Guía de Habilitación Fiscal VykOne (COM-ECF-001) y especificaciones técnicas de VykCore Automation S.R.L."
    p_sources.font.size = Pt(7.5)
    p_sources.font.color.rgb = COLOR_TEXT_MUTED_LIGHT
    p_sources.space_before = Pt(3)

    add_footer(s12, 12, 12, is_dark=True)
    set_notes(s12, "Para cerrar, los invitamos a no esperar hasta el último minuto de los plazos de la Ley 32-23. Pueden ingresar a vykcore.com y one.vykcore.com para conocer la plataforma o agendar una demostración práctica. Estamos a su entera disposición para acompañarles en esta transformación tecnológica.")

    # Guardar presentación inicial
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(OUTPUT_FILE))
    
    # Aplicar sanitización OpenXML para compatibilidad total con Apple Keynote y MS PowerPoint
    sanitize_pptx_for_keynote(OUTPUT_FILE)
    print(f"✅ Presentación PowerPoint generada y sanitizada exitosamente en: {OUTPUT_FILE}")


def sanitize_pptx_for_keynote(pptx_path):
    """
    Corrige incompatibilidades de OpenXML entre python-pptx y Apple Keynote:
    1. Ajusta <p:sldSz type="screen16x9"> para evitar el conflicto con screen4x3 en lienzo 16:9.
    2. Agrega <p:notesMasterIdLst> en presentation.xml si existen notas de orador,
       resolviendo el bug #1051 de python-pptx que bloquea la importación en Keynote.
    """
    import tempfile
    import zipfile
    import shutil
    import re

    temp_dir = tempfile.mkdtemp()
    try:
        with zipfile.ZipFile(pptx_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)

        pres_xml_path = os.path.join(temp_dir, 'ppt', 'presentation.xml')
        rels_xml_path = os.path.join(temp_dir, 'ppt', '_rels', 'presentation.xml.rels')

        if os.path.exists(pres_xml_path):
            with open(pres_xml_path, 'r', encoding='utf-8') as f:
                pres_content = f.read()

            # 1. Corregir type a screen16x9
            pres_content = pres_content.replace('type="screen4x3"', 'type="screen16x9"')

            # 2. Corregir relación con notesMaster si existen notas
            if os.path.exists(rels_xml_path) and '<p:notesMasterIdLst>' not in pres_content:
                with open(rels_xml_path, 'r', encoding='utf-8') as rf:
                    rels_content = rf.read()

                m = re.search(r'<Relationship[^>]*Id="([^"]+)"[^>]*Type="[^"]*notesMaster"[^>]*>', rels_content)
                if not m:
                    m = re.search(r'<Relationship[^>]*Id="([^"]+)"[^>]*Target="notesMasters/notesMaster1\.xml"[^>]*>', rels_content)

                if m:
                    rid = m.group(1)
                    notes_tag = f'<p:notesMasterIdLst><p:notesMasterId r:id="{rid}"/></p:notesMasterIdLst>'
                    if '</p:sldMasterIdLst>' in pres_content:
                        pres_content = pres_content.replace('</p:sldMasterIdLst>', '</p:sldMasterIdLst>' + notes_tag)

            with open(pres_xml_path, 'w', encoding='utf-8') as f:
                f.write(pres_content)

        # Reempaquetar el archivo PPTX con compresión estándar
        with zipfile.ZipFile(pptx_path, 'w', zipfile.ZIP_DEFLATED) as zip_out:
            for folder_name, subfolders, filenames in os.walk(temp_dir):
                for filename in filenames:
                    file_path = os.path.join(folder_name, filename)
                    arcname = os.path.relpath(file_path, temp_dir)
                    zip_out.write(file_path, arcname)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    build_presentation()
