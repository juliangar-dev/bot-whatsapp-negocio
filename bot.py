from flask import Flask, request, jsonify, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import json
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///negocios.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

class Negocio(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    password = db.Column(db.String(100))
    nombre = db.Column(db.String(200))
    ubicacion = db.Column(db.String(200))
    telefono = db.Column(db.String(50))
    whatsapp = db.Column(db.String(50))
    sitio_web = db.Column(db.String(200))
    horario = db.Column(db.String(300))
    servicios = db.Column(db.Text)
    info_adicional = db.Column(db.Text)
    contacto = db.Column(db.String(100))

with app.app_context():
    db.create_all()

def construir_contexto(negocio):
    servicios = json.loads(negocio.servicios) if negocio.servicios else []
    lista = "\n".join([f"- {s['nombre']}: ${s['precio']}" for s in servicios if s.get('nombre')])
    
    contexto = f"""
Sos el asistente virtual de '{negocio.nombre}'.
Ubicación: {negocio.ubicacion or 'No disponible'}.
Horario: {negocio.horario or 'No disponible'}.
"""
    if negocio.telefono:
        contexto += f"Teléfono: {negocio.telefono}.\n"
    if negocio.whatsapp:
        contexto += f"WhatsApp: {negocio.whatsapp}.\n"
    if negocio.sitio_web:
        contexto += f"Sitio web: {negocio.sitio_web}.\n"
    if lista:
        contexto += f"Servicios y precios:\n{lista}\n"
    if negocio.info_adicional:
        contexto += f"Información adicional: {negocio.info_adicional}\n"
    
    contexto += f"""
Sos un asistente virtual profesional y amable que representa a este negocio de la mejor manera posible.

CÓMO COMUNICARTE:
- Hablá siempre en español rioplatense, de forma cálida y natural
- Sé breve y directo, sin respuestas largas innecesarias
- Usá emojis con moderación para dar calidez

CÓMO REPRESENTAR AL NEGOCIO:
- Siempre hablá bien del negocio, destacando sus puntos positivos
- Nunca menciones quejas, críticas, problemas o aspectos negativos del negocio
- Si te preguntan por opiniones o reseñas, solo mencioná aspectos positivos
- Si hay algo que no sabés o no tenés información, decí que consulten directamente con {negocio.contacto or negocio.nombre}

CUANDO TE PREGUNTEN CÓMO CONTACTAR:
- Dales el teléfono o WhatsApp si están disponibles
- Si preguntan por una persona real, derivalos al contacto principal

TU OBJETIVO:
- Responder las consultas del cliente de forma útil y rápida
- Generar una buena impresión del negocio en cada interacción
- Convertir cada consulta en una oportunidad para que el cliente visite o compre
"""
    return contexto

historiales = {}

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/panel/<negocio_id>")
def panel(negocio_id):
    return send_file("panel.html")

@app.route("/negocio/<negocio_id>", methods=["GET"])
def obtener_negocio(negocio_id):
    password = request.args.get("password")
    negocio = Negocio.query.get(negocio_id)
    if not negocio:
        return jsonify({"error": "No encontrado"}), 404
    if negocio.password and negocio.password != password:
        return jsonify({"error": "Contraseña incorrecta"}), 403
    return jsonify({
        "nombre": negocio.nombre,
        "ubicacion": negocio.ubicacion,
        "telefono": negocio.telefono,
        "whatsapp": negocio.whatsapp,
        "sitio_web": negocio.sitio_web,
        "horario": negocio.horario,
        "servicios": negocio.servicios,
        "info_adicional": negocio.info_adicional,
        "contacto": negocio.contacto
    })

@app.route("/crear", methods=["POST"])
def crear():
    datos = request.get_json()
    negocio_id = str(uuid.uuid4())[:8]
    password = datos.get("password")
    
    negocio = Negocio(
        id=negocio_id,
        password=password,
        nombre=datos["nombre"],
        ubicacion=datos.get("ubicacion", ""),
        telefono=datos.get("telefono", ""),
        whatsapp=datos.get("whatsapp", ""),
        sitio_web=datos.get("sitio_web", ""),
        horario=datos.get("horario", ""),
        servicios=json.dumps(datos.get("servicios", []), ensure_ascii=False),
        info_adicional=datos.get("info_adicional", ""),
        contacto=datos.get("contacto", "")
    )
    db.session.add(negocio)
    db.session.commit()
    
    return jsonify({
        "mensaje": f"✅ Bot creado para {datos['nombre']}",
        "id": negocio_id,
        "panel": f"/panel/{negocio_id}",
        "webhook": f"/webhook/{negocio_id}"
    })

@app.route("/guardar", methods=["POST"])
def guardar():
    datos = request.get_json()
    negocio_id = datos.get("id")
    password = datos.get("password")
    
    negocio = Negocio.query.get(negocio_id)
    if not negocio:
        return jsonify({"error": "No encontrado"}), 404
    if negocio.password and negocio.password != password:
        return jsonify({"error": "Contraseña incorrecta"}), 403
    
    negocio.nombre = datos["nombre"]
    negocio.ubicacion = datos.get("ubicacion", "")
    negocio.telefono = datos.get("telefono", "")
    negocio.whatsapp = datos.get("whatsapp", "")
    negocio.sitio_web = datos.get("sitio_web", "")
    negocio.horario = datos.get("horario", "")
    negocio.servicios = json.dumps(datos.get("servicios", []), ensure_ascii=False)
    negocio.info_adicional = datos.get("info_adicional", "")
    negocio.contacto = datos.get("contacto", "")
    
    db.session.add(negocio)
    db.session.commit()
    
    return jsonify({"mensaje": f"✅ Bot actualizado para {datos['nombre']}"})

@app.route("/webhook/<negocio_id>", methods=["POST"])
def webhook(negocio_id):
    numero = request.form.get("From")
    mensaje = request.form.get("Body")

    negocio = Negocio.query.get(negocio_id)
    if not negocio:
        resp = MessagingResponse()
        resp.message("Lo siento, este servicio no está configurado.")
        return str(resp)

    clave = f"{negocio_id}_{numero}"
    if clave not in historiales:
        historiales[clave] = []

    historiales[clave].append({"role": "user", "content": mensaje})

    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=construir_contexto(negocio),
        messages=historiales[clave]
    )

    texto = respuesta.content[0].text
    historiales[clave].append({"role": "assistant", "content": texto})

    resp = MessagingResponse()
    resp.message(texto)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))