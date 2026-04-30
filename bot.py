from flask import Flask, request, jsonify, send_file
from twilio.twiml.messaging_response import MessagingResponse
import anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

def cargar_negocio():
    with open("negocio.json", "r", encoding="utf-8") as f:
        datos = json.load(f)
    
    servicios = "\n".join([f"- {s['nombre']}: ${s['precio']}" for s in datos["servicios"]])
    
    return f"""
Sos el asistente virtual de '{datos["nombre"]}', ubicada en {datos["ubicacion"]}.
Horario: {datos["horario"]}.
Servicios y precios:
{servicios}
Turnos: {datos["turnos"]}.
Respondé siempre de forma amable, breve y en español rioplatense.
Si te preguntan algo que no sabés, decí que consulten directamente con {datos["contacto"]}.
"""

historiales = {}

@app.route("/")
def index():
    return send_file("index.html")

@app.route("/guardar", methods=["POST"])
def guardar():
    datos = request.get_json()
    with open("negocio.json", "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=4)
    return jsonify({"mensaje": "✅ Configuración guardada correctamente"})

@app.route("/webhook", methods=["POST"])
def webhook():
    numero = request.form.get("From")
    mensaje = request.form.get("Body")

    if numero not in historiales:
        historiales[numero] = []

    historiales[numero].append({"role": "user", "content": mensaje})

    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=cargar_negocio(),
        messages=historiales[numero]
    )

    texto = respuesta.content[0].text
    historiales[numero].append({"role": "assistant", "content": texto})

    resp = MessagingResponse()
    resp.message(texto)
    return str(resp)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))