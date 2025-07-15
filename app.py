from flask import Flask, render_template, request, redirect
import boto3
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)

BUCKET_NAME = 'fotos-boda-mar-jc'
s3 = boto3.client('s3')

@app.route('/')
def home():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload():
    files = request.files.getlist('fotos')
    for f in files:
        filename = secure_filename(f.filename)
        s3.upload_fileobj(f, BUCKET_NAME, filename, ExtraArgs={'ACL': 'public-read'})
    return redirect('/gallery')

@app.route('/gallery')
def gallery():
    response = s3.list_objects_v2(Bucket=BUCKET_NAME)
    fotos = []
    if 'Contents' in response:
        for obj in response['Contents']:
            fotos.append(f"https://{BUCKET_NAME}.s3.amazonaws.com/{obj['Key']}")
    return render_template('gallery.html', fotos=fotos)

if __name__ == '__main__':
    app.run(debug=True)
