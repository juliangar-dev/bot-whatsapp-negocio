from flask import Flask, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///negocios.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

class Negocio(db.Model):
    id = db.Column(db.String(100), primary_key=True)
    nombre = db.Column(db.String(200))
    ubicacion = db.Column(db.String(200))
    horario = db.Column(db.String(200))
    servicios = db.Column(db.Text)
    turnos = db.Column(db.String(200))
    contacto = db.Column(db.String(100))

with app.app_context():
    db.create_all()

def construir_contexto(negocio):
    servicios = json.loads(negocio.servicios)
    lista = "\n".join([f"- {s['nombre']}: ${s['precio']}" for s in servicios])
    return f"""
Sos el asistente virtual de '{negocio.nombre}', ubicada en {negocio.ubicacion}.
Horario: {negocio.horario}.
Servicios y precios:
{lista}
Turnos: {negocio.turnos}.
Respondé siempre de forma amable, breve y en español rioplatense.
Si te preguntan algo que no sabés, decí que consulten directamente con {negocio.contacto}.
"""

historiales = {}

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/guardar", methods=["POST"])
def guardar():
    datos = request.get_json()
    negocio_id = datos["nombre"].lower().replace(" ", "_")
    
    negocio = Negocio.query.get(negocio_id)
    if not negocio:
        negocio = Negocio(id=negocio_id)
    
    negocio.nombre = datos["nombre"]
    negocio.ubicacion = datos["ubicacion"]
    negocio.horario = datos["horario"]
    negocio.servicios = json.dumps(datos["servicios"], ensure_ascii=False)
    negocio.turnos = datos.get("turnos", "No es necesario, se atiende por orden de llegada")
    negocio.contacto = datos["contacto"]
    
    db.session.add(negocio)
    db.session.commit()
    
    return jsonify({"mensaje": f"✅ Bot activado para {datos['nombre']}", "id": negocio_id})

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