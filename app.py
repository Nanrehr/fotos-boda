from flask import Flask, render_template, request, redirect, flash
import boto3
import os
from werkzeug.utils import secure_filename
from io import BytesIO
from datetime import datetime
import pytz
from PIL import Image
from PIL.ExifTags import TAGS
import re

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
            ("PreparaciónBoda",   tz.localize(datetime(2025, 7, 19, 9, 0)), tz.localize(datetime(2025, 7, 19, 18, 40, 0))),
            ("Ceremonia",         tz.localize(datetime(2025, 7, 19, 18, 40, 1)), tz.localize(datetime(2025, 7, 19, 20, 20, 0))),
            ("Coctel",            tz.localize(datetime(2025, 7, 19, 20, 20, 1)), tz.localize(datetime(2025, 7, 19, 22, 30, 0))),
            ("Banquete",          tz.localize(datetime(2025, 7, 19, 22, 30, 1)), tz.localize(datetime(2025, 7, 20, 3, 0, 0))),
            ("Fiesta",            tz.localize(datetime(2025, 7, 20, 3, 0, 1)), tz.localize(datetime(2025, 7, 20, 10, 0))),
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
                    fecha = tz.localize(datetime.strptime(match.group(1), "%Y%m%d_%H%M%S"))
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