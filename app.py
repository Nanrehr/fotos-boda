# app.py
from flask import Flask, render_template, request, redirect
import boto3
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')
REGION_NAME = os.environ.get('AWS_REGION')

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ.get('AWS_ACCESS_KEY_ID'),
    aws_secret_access_key=os.environ.get('AWS_SECRET_ACCESS_KEY'),
    region_name=REGION_NAME
)

@app.route('/')
def home():
    return render_template('upload.html')


@app.route('/upload', methods=['POST'])
def upload():
    try:
        files = request.files.getlist('fotos')
        for f in files:
            if f.filename:
                filename = secure_filename(f.filename)
                s3.upload_fileobj(f, BUCKET_NAME, filename, ExtraArgs={'ACL': 'public-read'})
        return redirect('/gallery')
    except Exception as e:
        return f"Error: {str(e)}", 500


@app.route('/gallery')
def gallery():
    response = s3.list_objects_v2(Bucket=BUCKET_NAME)
    fotos = []
    if 'Contents' in response:
        for obj in response['Contents']:
            fotos.append(f"https://{BUCKET_NAME}.s3.{REGION_NAME}.amazonaws.com/{obj['Key']}")
    return render_template('gallery.html', fotos=fotos)
