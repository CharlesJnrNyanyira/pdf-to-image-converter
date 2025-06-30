from flask import Flask, request, jsonify
import base64
import io
import zipfile
from pdf2image import convert_from_bytes
from PIL import Image
import os
import tempfile

app = Flask(__name__)

@app.route('/pdf-to-images', methods=['POST'])
def pdf_to_images():
    try:
        # Get JSON data from request
        data = request.get_json()
        
        if not data or 'pdfBase64' not in data:
            return jsonify({'error': 'No pdfBase64 data provided'}), 400
            
        # Decode base64 PDF
        pdf_base64 = data['pdfBase64']
        pdf_bytes = base64.b64decode(pdf_base64)
        
        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300, fmt='png')
        
        # Convert images to base64
        result_images = []
        for i, image in enumerate(images):
            # Convert PIL image to bytes
            img_buffer = io.BytesIO()
            image.save(img_buffer, format='PNG')
            img_buffer.seek(0)
            
            # Encode to base64
            img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
            
            result_images.append({
                'page': i + 1,
                'image_base64': img_base64,
                'width': image.width,
                'height': image.height
            })
        
        return jsonify({
            'success': True,
            'total_pages': len(images),
            'images': result_images
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pdf-to-images-zip', methods=['POST'])
def pdf_to_images_zip():
    """Alternative endpoint that returns a zip file download link"""
    try:
        data = request.get_json()
        
        if not data or 'pdfBase64' not in data:
            return jsonify({'error': 'No pdfBase64 data provided'}), 400
            
        pdf_base64 = data['pdfBase64']
        pdf_bytes = base64.b64decode(pdf_base64)
        
        # Convert PDF to images
        images = convert_from_bytes(pdf_bytes, dpi=300, fmt='png')
        
        # Create zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for i, image in enumerate(images):
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG')
                zip_file.writestr(f'page_{i+1}.png', img_buffer.getvalue())
        
        zip_buffer.seek(0)
        zip_base64 = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
        
        return jsonify({
            'success': True,
            'total_pages': len(images),
            'zip_base64': zip_base64
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'PDF to Image Converter'})

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
