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
import pytz  # AÑADIR EN requirements.txt

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
        files = request.files.getlist('fotos')
        uploaded_count = 0
        skipped_count = 0

        for f in files:
            if f.filename and allowed_file(f.filename):
                filename = secure_filename(f.filename)
                try:
                    s3.head_object(Bucket=BUCKET_NAME, Key=filename)
                    skipped_count += 1
                    continue
                except:
                    pass

                file_extension = filename.rsplit('.', 1)[1].lower()
                s3.upload_fileobj(
                    f,
                    BUCKET_NAME,
                    filename,
                    ExtraArgs={
                        'ContentType': f'image/{file_extension}',
                        'CacheControl': 'max-age=86400'
                    }
                )
                uploaded_count += 1

        if uploaded_count > 0:
            flash(f'¡Perfecto! Se subieron {uploaded_count} fotos nuevas.', 'success')
            if skipped_count > 0:
                flash(f'{skipped_count} fotos ya existían y se omitieron.', 'info')
        elif skipped_count > 0:
            flash(f'Las {skipped_count} fotos ya estaban en la galería.', 'info')
        else:
            flash('No se subieron archivos válidos. Solo se permiten imágenes.', 'error')

        return redirect('/gallery')

    except Exception as e:
        print(f"Error al subir: {str(e)}")
        flash(f'Error al subir las fotos: {str(e)}', 'error')
        return redirect('/')

# ✅ NUEVA RUTA /gallery ORGANIZADA POR HORAS
@app.route('/gallery')
def gallery():
    try:
        tz = pytz.timezone('Europe/Madrid')
        segments = [
            ("PreBoda",        tz.localize(datetime(2025,7,18,0,0)),  tz.localize(datetime(2025,7,19,4,0))),
            ("PreparaciónBoda",tz.localize(datetime(2025,7,19,4,0)),  tz.localize(datetime(2025,7,19,18,0))),
            ("Ceremonia",      tz.localize(datetime(2025,7,19,18,0)), tz.localize(datetime(2025,7,19,20,0))),
            ("Coctel",         tz.localize(datetime(2025,7,19,20,0)), tz.localize(datetime(2025,7,19,21,15))),
            ("Banquete",       tz.localize(datetime(2025,7,19,21,15)),tz.localize(datetime(2025,7,20,0,30))),
            ("Fiesta",         tz.localize(datetime(2025,7,20,0,30)), tz.localize(datetime(2025,7,20,6,0))),
            ("Sin Clasificar", tz.localize(datetime(2025,7,17,0,0)),  tz.localize(datetime(2025,7,21,0,0)))  # fallback
        ]
        segmentos = {nombre: [] for nombre, _, _ in segments}

        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        if 'Contents' in response:
            for obj in response['Contents']:
                url = f"https://{BUCKET_NAME}.s3.{REGION_NAME}.amazonaws.com/{obj['Key']}"
                fecha = obj['LastModified'].astimezone(tz)
                añadido = False
                for nombre, inicio, fin in segments[:-1]:  # Excluir el último (fallback) de momento
                    if inicio <= fecha < fin:
                        segmentos[nombre].append(url)
                        añadido = True
                        break
                if not añadido:
                    segmentos["Sin Clasificar"].append(url)

        return render_template('gallery.html', segmentos=segmentos)

    except Exception as e:
        print(f"Error al cargar galería: {str(e)}")
        flash(f'Error al cargar la galería: {str(e)}', 'error')
        return redirect('/')

# (Las rutas de ZIP se mantienen igual)
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