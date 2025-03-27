from flask import Flask, request, jsonify, render_template
import requests
from gtts import gTTS
from io import BytesIO
import base64
import logging
from functools import wraps
import os
from flask_cors import CORS

# Configuración inicial
app = Flask(__name__)
CORS(app)

# Configuración de logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

N8N_WEBHOOK_URL = "https://a6b9-187-189-50-8.ngrok-free.app/webhook/fa833c9e-f44a-44e5-9515-378505671975"
#N8N_WEBHOOK_URL = "https://a6b9-187-189-50-8.ngrok-free.app/webhook-test/fa833c9e-f44a-44e5-9515-378505671975"

TIMEOUT_N8N = int(os.getenv('TIMEOUT_N8N', 15))
MAX_MESSAGE_LENGTH = int(os.getenv('MAX_MESSAGE_LENGTH', 500))

def handle_errors(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except requests.exceptions.RequestException as e:
            logger.error(f"Error de conexión: {str(e)}")
            return jsonify({"error": "Error de conexión con servicios externos"}), 502
        except Exception as e:
            logger.error(f"Error inesperado: {str(e)}", exc_info=True)
            return jsonify({"error": "Error interno del servidor"}), 500
    return wrapper

def generar_audio(texto, lenguaje='es', tld='com.mx', velocidad=True):
    """Genera audio a partir de texto usando gTTS con manejo de errores"""
    if not texto:
        return None

    try:
        tts = gTTS(
            text=texto,
            lang=lenguaje,
            tld=tld,
            slow=not velocidad
        )
        audio_buffer = BytesIO()
        tts.write_to_fp(audio_buffer)
        audio_buffer.seek(0)
        return base64.b64encode(audio_buffer.getvalue()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error generando audio: {str(e)}")
        return None

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/consultar', methods=['POST'])
@handle_errors
def consultar():
    # Validación del contenido
    content_type = request.headers.get('Content-Type', '').lower()
    
    if content_type == 'application/json':
        data = request.get_json(silent=True) or {}
        mensaje = data.get('mensaje', '').strip()
    elif content_type == 'text/plain':
        mensaje = request.data.decode('utf-8').strip()
    else:
        return jsonify({"error": "Content-Type debe ser application/json o text/plain"}), 400

    # Validación del mensaje
    if not mensaje:
        return jsonify({"error": "El mensaje no puede estar vacío"}), 400
        
    if len(mensaje) > MAX_MESSAGE_LENGTH:
        return jsonify({
            "error": f"El mensaje excede el límite de {MAX_MESSAGE_LENGTH} caracteres",
            "longitud_actual": len(mensaje)
        }), 400

    logger.info(f"Consulta recibida: {mensaje[:100]}...")

    # Preparar y enviar a n8n
    payload = {
        "mensaje": mensaje,
        "metadata": {
            "origen": "asistente-imss-web",
            "version": "1.0",
            "requiere_audio": True
        }
    }

    try:
        response = requests.post(
            N8N_WEBHOOK_URL,
            headers={
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'User-Agent': 'AsistenteIMSS/1.0'
            },
            json=payload,
            timeout=TIMEOUT_N8N
        )
        response.raise_for_status()
        respuesta_data = response.json()
        
        # Procesamiento de respuesta
        respuesta_texto = respuesta_data.get('respuesta') or respuesta_data.get('texto')
        if not respuesta_texto or not isinstance(respuesta_texto, str):
            raise ValueError("Respuesta inválida o vacía recibida de n8n")
            
        # Generar audio
        audio_base64 = generar_audio(respuesta_texto) if respuesta_texto else None

        return jsonify({
            "texto": respuesta_texto,
            "audio": audio_base64,
            "metadata": {
                "longitud_texto": len(respuesta_texto),
                "audio_generado": audio_base64 is not None,
                "origen": "n8n"
            }
        })

    except requests.exceptions.Timeout:
        logger.error("Timeout al conectar con n8n")
        return jsonify({"error": "El servicio tardó demasiado en responder"}), 504
    except requests.exceptions.JSONDecodeError:
        logger.error(f"Respuesta no JSON de n8n: {response.text[:200]}")
        return jsonify({"error": "Respuesta inválida del servicio"}), 502
    except Exception as e:
        logger.error(f"Error procesando respuesta: {str(e)}")
        return jsonify({"error": "Error procesando la respuesta"}), 502

if __name__ == '__main__':
    app.run(
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 5000)),
        debug=os.getenv('DEBUG', 'false').lower() == 'true'
    )