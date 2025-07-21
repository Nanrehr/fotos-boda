from flask import Flask, render_template, request, redirect, flash, send_file, jsonify
import boto3
import os
from werkzeug.utils import secure_filename
import zipfile
import requests
from io import BytesIO
import threading
import uuid
from datetime import datetime
import pytz
from PIL import Image
from PIL.ExifTags import TAGS
import re

zips_generados = {}

app = Flask(__name__)
app.secret_key = 'fotos-boda-mar-jc-secret'

BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
REGION_NAME = os.environ.get('AWS_REGION')

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=REGION_NAME
)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'heic', 'webp'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload():
    try:
        if 'fotos' not in request.files:
            return 'No se recibieron archivos', 400

        files = request.files.getlist('fotos')
        uploaded = 0
        skipped = 0

        for f in files:
            if not f.filename or not allowed_file(f.filename):
                continue

            filename = secure_filename(f.filename)
            file_extension = filename.rsplit('.', 1)[1].lower()
            exif_date = None

            try:
                img = Image.open(f.stream)
                exif_data = img._getexif()
                if exif_data:
                    for tag, value in exif_data.items():
                        decoded = TAGS.get(tag, tag)
                        if decoded == 'DateTimeOriginal':
                            exif_date = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                            break
            except Exception as ex:
                print("No EXIF:", ex)

            if exif_date:
                fecha_str = exif_date.strftime("%Y%m%d_%H%M%S")
                filename = f"{fecha_str}_{filename}"

            try:
                s3.head_object(Bucket=BUCKET_NAME, Key=filename)
                skipped += 1
                continue
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
            uploaded += 1

        print(f"Subidas: {uploaded}, Duplicadas: {skipped}")
        return '', 200  # ✅ Esto permite que fetch reconozca que todo fue bien

    except Exception as e:
        print(f"Error al subir: {str(e)}")
        return f'Error al subir: {str(e)}', 500
        
@app.route('/gallery')
def gallery():
    try:
        tz = pytz.timezone('Europe/Madrid')
        segmentos_definidos = [
            ("PrePreBoda",        tz.localize(datetime(2025, 7, 1, 0, 0)),  tz.localize(datetime(2025, 7, 16, 23, 59))),
            ("PreBoda",           tz.localize(datetime(2025, 7, 17, 0, 0)), tz.localize(datetime(2025, 7, 19, 4, 0))),
            ("PreparaciónBoda",   tz.localize(datetime(2025, 7, 19, 4, 0)), tz.localize(datetime(2025, 7, 19, 18, 0))),
            ("Ceremonia",         tz.localize(datetime(2025, 7, 19, 18, 0)), tz.localize(datetime(2025, 7, 19, 20, 0))),
            ("Coctel",            tz.localize(datetime(2025, 7, 19, 20, 0)), tz.localize(datetime(2025, 7, 19, 21, 15))),
            ("Banquete",          tz.localize(datetime(2025, 7, 19, 21, 15)),tz.localize(datetime(2025, 7, 20, 0, 30))),
            ("Fiesta",            tz.localize(datetime(2025, 7, 20, 0, 30)), tz.localize(datetime(2025, 7, 20, 6, 0))),
        ]

        fotos_por_categoria = {nombre: [] for nombre, _, _ in segmentos_definidos}
        fotos_por_categoria["Sin Clasificar"] = []

        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        if 'Contents' in response:
            for obj in response['Contents']:
                url = f"https://{BUCKET_NAME}.s3.{REGION_NAME}.amazonaws.com/{obj['Key']}"
                key = obj['Key']

                match = re.match(r"(\d{8}_\d{6})_", key)
                if match:
                    fecha = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").astimezone(tz)
                else:
                    fecha = obj['LastModified'].astimezone(tz)

                añadido = False
                for nombre, inicio, fin in segmentos_definidos:
                    if inicio <= fecha < fin:
                        fotos_por_categoria[nombre].append(url)
                        añadido = True
                        break

                if not añadido:
                    fotos_por_categoria["Sin Clasificar"].append(url)

        return render_template('gallery.html', fotos_por_categoria=fotos_por_categoria)

    except Exception as e:
        print(f"Error al cargar galería: {str(e)}")
        flash(f'Error al cargar la galería: {str(e)}', 'error')
        return redirect('/')

@app.route('/download-zip', methods=['POST'])
def download_zip():
    try:
        urls = request.json.get('urls', [])
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, url in enumerate(urls, 1):
                filename = f"foto_{i}.jpg"
                try:
                    img_data = requests.get(url).content
                    zip_file.writestr(filename, img_data)
                except Exception as e:
                    print(f"Error al descargar {url}: {e}")

        zip_buffer.seek(0)
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name='Fotos_Boda_M&JC.zip'
        )
    except Exception as e:
        print(f"Error al generar el ZIP: {e}")
        return jsonify({'error': 'No se pudo generar el ZIP'}), 500

@app.route('/solicitar-zip', methods=['POST'])
def solicitar_zip():
    try:
        urls = request.json.get('urls', [])
        zip_id = str(uuid.uuid4())

        thread = threading.Thread(target=crear_zip_en_memoria, args=(urls, zip_id))
        thread.start()

        return jsonify({'zip_id': zip_id})
    except Exception as e:
        return jsonify({'error': 'No se pudo preparar el ZIP'}), 500

@app.route('/download-ready/<zip_id>')
def download_ready(zip_id):
    zip_buffer = zips_generados.get(zip_id)
    if not zip_buffer:
        return "Todavía se está generando el ZIP o ha expirado.", 404

    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='Fotos_Boda_M&JC.zip'
    )

def crear_zip_en_memoria(urls, zip_id):
    try:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, url in enumerate(urls, 1):
                filename = f"foto_{i}.jpg"
                try:
                    img_data = requests.get(url).content
                    zip_file.writestr(filename, img_data)
                except Exception as e:
                    print(f"Error descargando {url}: {e}")
        zip_buffer.seek(0)
        zips_generados[zip_id] = zip_buffer
    except Exception as e:
        print(f"Error en thread ZIP: {e}")