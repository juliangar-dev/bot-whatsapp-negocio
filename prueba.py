import anthropic

client = anthropic.Anthropic(api_key="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")

negocio = """
Sos el asistente virtual de 'Peluquería Carlos', ubicada en Buenos Aires.
Horario: lunes a sábado de 9 a 20hs.
Servicios y precios:
- Corte de pelo: $3000
- Corte y barba: $4500
- Afeitado: $2000
- Turno previo: no es necesario, se atiende por orden de llegada
Respondé siempre de forma amable, breve y en español rioplatense.
Si te preguntan algo que no sabés, decí que consulten directamente con Carlos.
"""

historial = []

def responder(mensaje_cliente):
    historial.append({"role": "user", "content": mensaje_cliente})
    
    respuesta = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=negocio,
        messages=historial
    )
    
    texto = respuesta.content[0].text
    historial.append({"role": "assistant", "content": texto})
    return texto

print("Bot de Peluquería Carlos activo. Escribí 'salir' para terminar.")
print("---")

while True:
    mensaje = input("Vos: ")
    if mensaje.lower() == "salir":
        break
    respuesta = responder(mensaje)
    print(f"Bot: {respuesta}")
    print("---")