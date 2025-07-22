from flask import Flask, render_template, request, redirect, flash
import boto3
import os
from werkzeug.utils import secure_filename
from datetime import datetime
import pytz
from PIL import Image
from PIL.ExifTags import TAGS
import logging
import re

# === Configuración de Flask ===
app = Flask(__name__)
app.secret_key = 'fotos-boda-mar-jc-secret'

# === Configuración de AWS S3 ===
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
REGION_NAME = os.environ.get('AWS_REGION')

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=REGION_NAME
)

# === Configuración de logs ===
logging.basicConfig(filename="uploads.log", level=logging.INFO, format='%(message)s')

# === Extensiones permitidas ===
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'heic', 'webp'}

# === Funciones auxiliares ===
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def obtener_categoria(dt):
    tz = pytz.timezone('Europe/Madrid')
    dt = tz.localize(dt)
    segmentos = [
        ("PreBoda",           tz.localize(datetime(2025, 7, 1, 0, 0)), tz.localize(datetime(2025, 7, 19, 8, 59))),
        ("PreparaciónBoda",  tz.localize(datetime(2025, 7, 19, 9, 0)), tz.localize(datetime(2025, 7, 19, 18, 40))),
        ("Ceremonia",        tz.localize(datetime(2025, 7, 19, 18, 40, 1)), tz.localize(datetime(2025, 7, 19, 20, 20))),
        ("Coctel",           tz.localize(datetime(2025, 7, 19, 20, 20, 1)), tz.localize(datetime(2025, 7, 19, 22, 30))),
        ("Banquete",         tz.localize(datetime(2025, 7, 19, 22, 30, 1)), tz.localize(datetime(2025, 7, 20, 3, 0))),
        ("Fiesta",           tz.localize(datetime(2025, 7, 20, 3, 0, 1)), tz.localize(datetime(2025, 7, 20, 10, 0))),
    ]
    for nombre, inicio, fin in segmentos:
        if inicio <= dt < fin:
            return nombre
    return "Desconocida"

def registrar_subida(ip, filename, categoria, agente):
    tz = pytz.timezone('Europe/Madrid')
    hora_local = datetime.now(tz).isoformat()
    linea = f"{hora_local} | IP: {ip} | Archivo: {filename} | Categoría: {categoria} | Navegador: {agente}"
    logging.info(linea)

# === Rutas de la app ===

@app.route('/')
def home():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        f = request.files.get('fotos')
        if not f or not allowed_file(f.filename):
            return 'Archivo no permitido', 400

        filename = secure_filename(f.filename)
        file_extension = filename.rsplit('.', 1)[1].lower()
        exif_date = None

        try:
            img = Image.open(f.stream)
            exif_data = img._getexif()
            if exif_data:
                for tag, value in exif_data.items():
                    if TAGS.get(tag) == 'DateTimeOriginal':
                        exif_date = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                        break
        except Exception as ex:
            print("No EXIF:", ex)

        if exif_date:
            fecha_str = exif_date.strftime("%Y%m%d_%H%M%S")
            filename = f"{fecha_str}_{filename}"

        try:
            s3.head_object(Bucket=BUCKET_NAME, Key=filename)
            print(f"Duplicada: {filename}")
            return '', 200
        except:
            pass

        f.stream.seek(0)
        s3.upload_fileobj(
            f,
            BUCKET_NAME,
            filename,
            ExtraArgs={
                'ContentType': f'image/{file_extension}',
                'CacheControl': 'max-age=86400'
            }
        )

        ip = request.remote_addr
        user_agent = request.headers.get('User-Agent')
        categoria = obtener_categoria(exif_date) if exif_date else "Desconocida"
        registrar_subida(ip, filename, categoria, user_agent)

        print(f"Subida: {filename}")
        return '', 200

    except Exception as e:
        print(f"Error al subir: {str(e)}")
        return f'Error al subir: {str(e)}', 500

@app.route('/gallery')
def gallery():
    try:
        tz = pytz.timezone('Europe/Madrid')
        segmentos_definidos = [
            ("PreBoda",           tz.localize(datetime(2025, 7, 1, 0, 0)), tz.localize(datetime(2025, 7, 19, 8, 59))),
            ("PreparaciónBoda",  tz.localize(datetime(2025, 7, 19, 9, 0)), tz.localize(datetime(2025, 7, 19, 18, 40))),
            ("Ceremonia",        tz.localize(datetime(2025, 7, 19, 18, 40, 1)), tz.localize(datetime(2025, 7, 19, 20, 20))),
            ("Coctel",           tz.localize(datetime(2025, 7, 19, 20, 20, 1)), tz.localize(datetime(2025, 7, 19, 22, 30))),
            ("Banquete",         tz.localize(datetime(2025, 7, 19, 22, 30, 1)), tz.localize(datetime(2025, 7, 20, 3, 0))),
            ("Fiesta",           tz.localize(datetime(2025, 7, 20, 3, 0, 1)), tz.localize(datetime(2025, 7, 20, 10, 0))),
        ]

        fotos_por_categoria = {nombre: [] for nombre, _, _ in segmentos_definidos}

        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        if 'Contents' in response:
            for obj in response['Contents']:
                url = f"https://{BUCKET_NAME}.s3.{REGION_NAME}.amazonaws.com/{obj['Key']}"
                key = obj['Key']

                match = re.match(r"(\d{8}_\d{6})_", key)
                if match:
                    fecha = tz.localize(datetime.strptime(match.group(1), "%Y%m%d_%H%M%S"))
                else:
                    fecha = obj['LastModified'].astimezone(tz)

                for nombre, inicio, fin in segmentos_definidos:
                    if inicio <= fecha < fin:
                        fotos_por_categoria[nombre].append(url)
                        break

        return render_template('gallery.html', fotos_por_categoria=fotos_por_categoria)

    except Exception as e:
        print(f"Error al cargar galería: {str(e)}")
        flash(f'Error al cargar la galería: {str(e)}', 'error')
        return redirect('/')

@app.route('/registros')
def ver_registros():
    registros = []
    try:
        with open("uploads.log", "r") as f:
            lineas = f.readlines()

        for linea in lineas[-100:]:
            partes = linea.strip().split(" | ")
            if len(partes) == 5:
                fecha = partes[0]
                ip = partes[1].replace("IP: ", "")
                archivo = partes[2].replace("Archivo: ", "")
                categoria = partes[3].replace("Categoría: ", "")
                navegador = partes[4].replace("Navegador: ", "")
                registros.append({
                    "fecha": fecha,
                    "ip": ip,
                    "archivo": archivo,
                    "categoria": categoria,
                    "navegador": navegador
                })
        return render_template("registros.html", registros=registros)

    except Exception as e:
        return f"<p>Error al leer el log: {str(e)}</p>"