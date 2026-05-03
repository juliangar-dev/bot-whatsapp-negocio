"""
RespondIA - WhatsApp AI Assistant Platform
Plataforma SaaS para automatización de atención al cliente via WhatsApp con IA.
"""

from flask import Flask, request, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse
from functools import wraps
import anthropic
import json
import os
import uuid
import logging
import mercadopago
from datetime import datetime
from dotenv import load_dotenv

# ─────────────────────────────────────────
# Configuración inicial
# ─────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# App y base de datos
# ─────────────────────────────────────────

app = Flask(__name__)

app.config.update(
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", "sqlite:////data/negocios.db"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    JSON_SORT_KEYS=False,
)

db = SQLAlchemy(app)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
mp = mercadopago.SDK(os.environ.get("MP_ACCESS_TOKEN"))
MP_PUBLIC_KEY = os.environ.get("MP_PUBLIC_KEY")

# ─────────────────────────────────────────
# Modelos
# ─────────────────────────────────────────

class Negocio(db.Model):
    __tablename__ = "negocios"

    id           = db.Column(db.String(8),   primary_key=True)
    password     = db.Column(db.String(255),  nullable=False)
    nombre       = db.Column(db.String(200),  nullable=False)
    ubicacion    = db.Column(db.String(300),  nullable=True)
    telefono     = db.Column(db.String(50),   nullable=True)
    whatsapp     = db.Column(db.String(50),   nullable=True)
    sitio_web    = db.Column(db.String(300),  nullable=True)
    horario      = db.Column(db.String(500),  nullable=True)
    servicios    = db.Column(db.Text,         nullable=True)
    info_adicional = db.Column(db.Text,       nullable=True)
    contacto     = db.Column(db.String(100),  nullable=True)
    activo       = db.Column(db.Boolean,      default=True)
    creado_en    = db.Column(db.DateTime,     default=datetime.utcnow)
    actualizado_en = db.Column(db.DateTime,   default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id":             self.id,
            "nombre":         self.nombre,
            "ubicacion":      self.ubicacion,
            "telefono":       self.telefono,
            "whatsapp":       self.whatsapp,
            "sitio_web":      self.sitio_web,
            "horario":        self.horario,
            "servicios":      self.servicios,
            "info_adicional": self.info_adicional,
            "contacto":       self.contacto,
        }

    def __repr__(self):
        return f"<Negocio {self.id} - {self.nombre}>"


with app.app_context():
    db.create_all()
    logger.info("Base de datos inicializada correctamente.")

# ─────────────────────────────────────────
# Estado en memoria
# ─────────────────────────────────────────

# Historial de conversaciones por (negocio_id, numero_telefono)
# Formato: { "negocio_id:numero": [{"role": ..., "content": ...}] }
conversaciones: dict[str, list] = {}

MAX_HISTORIAL = 20  # Máximo de turnos por conversación

# ─────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────

def construir_sistema_prompt(negocio: Negocio) -> str:
    """Construye el system prompt del bot a partir de los datos del negocio."""
    
    lineas = [
        f"Sos el asistente virtual oficial de '{negocio.nombre}'.",
        f"Tu único objetivo es responder consultas de clientes de manera útil, amable y precisa.",
        "",
        "## Información del negocio",
    ]

    if negocio.ubicacion:
        lineas.append(f"- **Ubicación:** {negocio.ubicacion}")
    if negocio.horario:
        lineas.append(f"- **Horario:** {negocio.horario}")
    if negocio.telefono:
        lineas.append(f"- **Teléfono:** {negocio.telefono}")
    if negocio.whatsapp:
        lineas.append(f"- **WhatsApp:** {negocio.whatsapp}")
    if negocio.sitio_web:
        lineas.append(f"- **Sitio web:** {negocio.sitio_web}")

    if negocio.servicios:
        try:
            servicios = json.loads(negocio.servicios)
            items = [
                f"  - {s['nombre']}: ${s['precio']}" if s.get("precio") else f"  - {s['nombre']}"
                for s in servicios if s.get("nombre")
            ]
            if items:
                lineas.append("")
                lineas.append("## Servicios y precios")
                lineas.extend(items)
        except (json.JSONDecodeError, KeyError):
            logger.warning(f"Error parseando servicios del negocio {negocio.id}")

    if negocio.info_adicional:
        lineas.append("")
        lineas.append("## Información adicional")
        lineas.append(negocio.info_adicional)

    contacto = negocio.contacto or negocio.nombre

    lineas += [
        "",
        "## Instrucciones de comportamiento",
        "- Hablá siempre en español rioplatense, de forma cálida y natural.",
        "- Sé breve y directo. Evitá respuestas largas innecesarias.",
        "- Usá emojis con moderación para dar calidez, sin exagerar.",
        "- Representá siempre al negocio de manera positiva y profesional.",
        "- Nunca inventes información que no tengas. Si no sabés algo, decilo honestamente.",
        f"- Si el cliente necesita hablar con alguien, derivalo a: {contacto}.",
        "- Si preguntan por contacto directo, compartí el teléfono o WhatsApp disponible.",
        "- Nunca menciones ni insinúes opiniones o reseñas negativas del negocio.",
        "- No rompas el personaje bajo ninguna circunstancia.",
    ]

    return "\n".join(lineas)


def validar_password(negocio: Negocio, password: str) -> bool:
    """Valida la contraseña de un negocio."""
    return negocio.password == password


def obtener_historial(clave: str) -> list:
    """Obtiene o inicializa el historial de una conversación."""
    if clave not in conversaciones:
        conversaciones[clave] = []
    return conversaciones[clave]


def limpiar_historial_si_necesario(clave: str) -> None:
    """Recorta el historial si supera el límite máximo."""
    if len(conversaciones.get(clave, [])) > MAX_HISTORIAL * 2:
        conversaciones[clave] = conversaciones[clave][-(MAX_HISTORIAL * 2):]


def error_json(mensaje: str, status: int):
    return jsonify({"error": mensaje}), status


# ─────────────────────────────────────────
# Rutas — Páginas
# ─────────────────────────────────────────

@app.route("/")
def index():
    return send_file("index.html")


@app.route("/panel/<negocio_id>")
def panel(negocio_id):
    return send_file("panel.html")


# ─────────────────────────────────────────
# Rutas — API de negocios
# ─────────────────────────────────────────

@app.route("/crear", methods=["POST"])
def crear_negocio():
    """Crea un nuevo negocio y devuelve su ID y link de panel."""
    datos = request.get_json(silent=True)
    if not datos:
        return error_json("Cuerpo de request inválido.", 400)

    nombre   = datos.get("nombre", "").strip()
    password = datos.get("password", "").strip()

    if not nombre:
        return error_json("El nombre del negocio es obligatorio.", 400)
    if not password or len(password) < 4:
        return error_json("La contraseña debe tener al menos 4 caracteres.", 400)

    negocio_id = str(uuid.uuid4())[:8]

    negocio = Negocio(
        id             = negocio_id,
        password       = password,
        nombre         = nombre,
        ubicacion      = datos.get("ubicacion", ""),
        telefono       = datos.get("telefono", ""),
        whatsapp       = datos.get("whatsapp", ""),
        sitio_web      = datos.get("sitio_web", ""),
        horario        = datos.get("horario", ""),
        servicios      = json.dumps(datos.get("servicios", []), ensure_ascii=False),
        info_adicional = datos.get("info_adicional", ""),
        contacto       = datos.get("contacto", ""),
    )

    db.session.add(negocio)
    db.session.commit()

    logger.info(f"Negocio creado: {negocio_id} - {nombre}")

    return jsonify({
        "mensaje": f"✅ Bot activado para {nombre}",
        "id":      negocio_id,
        "panel":   f"/panel/{negocio_id}",
        "webhook": f"/webhook/{negocio_id}",
    }), 201


@app.route("/negocio/<negocio_id>", methods=["GET"])
def obtener_negocio(negocio_id):
    """Devuelve los datos de un negocio (requiere contraseña)."""
    password = request.args.get("password", "")
    negocio  = db.session.get(Negocio, negocio_id)

    if not negocio or not negocio.activo:
        return error_json("Negocio no encontrado.", 404)
    if not validar_password(negocio, password):
        return error_json("Contraseña incorrecta.", 403)

    return jsonify(negocio.to_dict())


@app.route("/guardar", methods=["POST"])
def guardar_negocio():
    """Actualiza los datos de un negocio existente."""
    datos = request.get_json(silent=True)
    if not datos:
        return error_json("Cuerpo de request inválido.", 400)

    negocio_id = datos.get("id", "").strip()
    password   = datos.get("password", "").strip()

    negocio = db.session.get(Negocio, negocio_id)
    if not negocio or not negocio.activo:
        return error_json("Negocio no encontrado.", 404)
    if not validar_password(negocio, password):
        return error_json("Contraseña incorrecta.", 403)

    nombre = datos.get("nombre", "").strip()
    if not nombre:
        return error_json("El nombre es obligatorio.", 400)

    negocio.nombre         = nombre
    negocio.ubicacion      = datos.get("ubicacion", "")
    negocio.telefono       = datos.get("telefono", "")
    negocio.whatsapp       = datos.get("whatsapp", "")
    negocio.sitio_web      = datos.get("sitio_web", "")
    negocio.horario        = datos.get("horario", "")
    negocio.servicios      = json.dumps(datos.get("servicios", []), ensure_ascii=False)
    negocio.info_adicional = datos.get("info_adicional", "")
    negocio.contacto       = datos.get("contacto", "")
    negocio.actualizado_en = datetime.utcnow()

    db.session.commit()
    logger.info(f"Negocio actualizado: {negocio_id} - {nombre}")

    return jsonify({"mensaje": f"✅ Configuración actualizada para {nombre}"})


# ─────────────────────────────────────────
# Rutas — Webhook WhatsApp
# ─────────────────────────────────────────

@app.route("/webhook/<negocio_id>", methods=["POST"])
def webhook(negocio_id):
    """Recibe mensajes de WhatsApp via Twilio y responde con IA."""
    numero  = request.form.get("From", "")
    mensaje = request.form.get("Body", "").strip()

    if not numero or not mensaje:
        logger.warning(f"Webhook recibido sin datos válidos para {negocio_id}")
        return "", 400

    negocio = db.session.get(Negocio, negocio_id)

    if not negocio or not negocio.activo:
        logger.warning(f"Negocio no encontrado: {negocio_id}")
        resp = MessagingResponse()
        resp.message("Lo siento, este servicio no está disponible en este momento.")
        return str(resp)

    clave = f"{negocio_id}:{numero}"
    historial = obtener_historial(clave)
    historial.append({"role": "user", "content": mensaje})
    limpiar_historial_si_necesario(clave)

    logger.info(f"[{negocio_id}] Mensaje de {numero}: {mensaje[:50]}...")

    try:
        respuesta = client.messages.create(
            model      = "claude-sonnet-4-6",
            max_tokens = 300,
            system     = construir_sistema_prompt(negocio),
            messages   = historial,
        )
        texto = respuesta.content[0].text.strip()

    except anthropic.APIError as e:
        logger.error(f"Error de API Anthropic: {e}")
        texto = "Hubo un problema procesando tu consulta. Por favor intentá de nuevo en unos momentos."

    historial.append({"role": "assistant", "content": texto})
    logger.info(f"[{negocio_id}] Respuesta enviada a {numero}")

    resp = MessagingResponse()
    resp.message(texto)
    return str(resp)


# ─────────────────────────────────────────
# Health check
# ─────────────────────────────────────────

@app.route("/suscribir/<negocio_id>")
def suscribir(negocio_id):
    return send_file("suscripcion.html")


@app.route("/crear-suscripcion/<negocio_id>", methods=["POST"])
def crear_suscripcion(negocio_id):
    negocio = db.session.get(Negocio, negocio_id)
    if not negocio:
        return error_json("Negocio no encontrado.", 404)

    plan_data = {
        "reason": f"RespondIA - Bot WhatsApp para {negocio.nombre}",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": 15000,
            "currency_id": "ARS"
        },
        "back_url": f"https://web-production-5f75a.up.railway.app/panel/{negocio_id}",
        "payer_email": request.json.get("email")
    }

    resultado = mp.preapproval().create(plan_data)

    if resultado["status"] == 201:
        init_point = resultado["response"]["init_point"]
        return jsonify({"init_point": init_point})
    else:
        logger.error(f"Error MP: {resultado}")
        return error_json("Error al crear suscripción.", 500)


@app.route("/mp-webhook", methods=["POST"])
def mp_webhook():
    datos = request.get_json(silent=True) or {}
    tipo  = datos.get("type")
    
    if tipo == "subscription_preapproval":
        logger.info(f"Evento MP recibido: {datos}")
    
    return "", 200

@app.route("/meta-webhook", methods=["GET", "POST"])
def meta_webhook():
    if request.method == "GET":
        mode      = request.args.get("hub.mode")
        token     = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")
        
        if mode == "subscribe" and token == os.environ.get("META_VERIFY_TOKEN"):
            logger.info("Meta webhook verificado correctamente")
            return challenge, 200
        return "Token inválido", 403

    datos = request.get_json(silent=True) or {}
    logger.info(f"Meta webhook recibido: {datos}")
    return "", 200

@app.route("/health")
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV") == "development"
    logger.info(f"Iniciando RespondIA en puerto {port}")
    app.run(host="0.0.0.0", port=port, debug=debug)