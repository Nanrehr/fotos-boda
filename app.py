# app.py
from flask import Flask, render_template, request, redirect, flash
import boto3
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'fotos-boda-mar-jc-secret'  # Para flash messages

BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
REGION_NAME = os.environ.get('AWS_REGION')

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=REGION_NAME
)

# Tipos de archivo permitidos
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
                # Mantener nombre original (sin UUID)
                filename = secure_filename(f.filename)
                
                # Verificar si ya existe
                try:
                    s3.head_object(Bucket=BUCKET_NAME, Key=filename)
                    skipped_count += 1  # Ya existe, saltar
                    continue
                except:
                    pass  # No existe, continuar con la subida
                
                # Subir archivo
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
        
        # Mensaje de éxito
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

@app.route('/gallery')
def gallery():
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        fotos = []
        
        if 'Contents' in response:
            # Ordenar por fecha de modificación (más recientes primero)
            sorted_objects = sorted(response['Contents'], key=lambda x: x['LastModified'], reverse=True)
            fotos = [f"https://{BUCKET_NAME}.s3.{REGION_NAME}.amazonaws.com/{obj['Key']}" for obj in sorted_objects]
        
        return render_template('gallery.html', fotos=fotos, total=len(fotos))
    except Exception as e:
        print(f"Error al cargar galería: {str(e)}")
        flash(f'Error al cargar la galería: {str(e)}', 'error')
        return redirect('/')
        

@app.route('/download-zip', methods=['POST'])
def download_zip():
    urls = request.json.get('urls', [])
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for i, url in enumerate(urls, 1):
            filename = f"foto_{i}.jpg"
            img_data = requests.get(url).content
            zip_file.writestr(filename, img_data)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype='application/zip',
        as_attachment=True,
        download_name='Fotos_Boda_M&JC.zip'
    )