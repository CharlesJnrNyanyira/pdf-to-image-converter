from flask import Flask, request, jsonify
import base64
import io
import zipfile
from pdf2image import convert_from_bytes
from PIL import Image
import os
import tempfile
import gc
import subprocess

app = Flask(__name__)

# Configure for Render
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

def check_poppler():
    """Check if poppler is installed"""
    try:
        result = subprocess.run(['pdftoppm', '-h'], capture_output=True, text=True)
        return True
    except FileNotFoundError:
        return False

@app.route('/pdf-to-images', methods=['POST'])
def pdf_to_images():
    try:
        # Check if poppler is available
        if not check_poppler():
            return jsonify({'error': 'poppler-utils not installed on server'}), 500
        
        # Get JSON data from request
        data = request.get_json()
        
        if not data or 'pdfBase64' not in data:
            return jsonify({'error': 'No pdfBase64 data provided'}), 400
            
        # Decode base64 PDF
        pdf_base64 = data['pdfBase64']
        
        if not pdf_base64:
            return jsonify({'error': 'Empty pdfBase64 data'}), 400
            
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
        except Exception as e:
            return jsonify({'error': f'Invalid base64 data: {str(e)}'}), 400
        
        # Validate PDF header
        if not pdf_bytes.startswith(b'%PDF'):
            return jsonify({'error': 'Data does not appear to be a valid PDF file'}), 400
        
        print(f"Processing PDF: {len(pdf_bytes)} bytes")
        
        # Convert PDF to images with better error handling
        try:
            images = convert_from_bytes(
                pdf_bytes, 
                dpi=150,  # Lower DPI for better memory usage
                fmt='png',
                thread_count=1,
                first_page=None,
                last_page=None,
                poppler_path=None  # Let it auto-detect
            )
        except Exception as e:
            print(f"pdf2image error: {str(e)}")
            return jsonify({'error': f'PDF conversion failed: {str(e)}'}), 500
        
        if not images:
            return jsonify({'error': 'No pages found in PDF or conversion failed'}), 400
        
        print(f"Converted to {len(images)} images")
        
        # Free up PDF bytes from memory
        del pdf_bytes
        del pdf_base64
        gc.collect()
        
        # Convert images to base64
        result_images = []
        for i, image in enumerate(images):
            try:
                # Convert PIL image to bytes
                img_buffer = io.BytesIO()
                # Optimize image for smaller size
                image.save(img_buffer, format='PNG', optimize=True, compress_level=6)
                img_buffer.seek(0)
                
                # Encode to base64
                img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
                
                result_images.append({
                    'page': i + 1,
                    'image_base64': img_base64,
                    'width': image.width,
                    'height': image.height
                })
                
                # Clean up to save memory
                img_buffer.close()
                del img_buffer
                
            except Exception as e:
                print(f"Error processing page {i+1}: {str(e)}")
                continue
        
        # Clean up images from memory
        del images
        gc.collect()
        
        if not result_images:
            return jsonify({'error': 'Failed to process any pages from PDF'}), 500
        
        return jsonify({
            'success': True,
            'total_pages': len(result_images),
            'images': result_images
        })
        
    except Exception as e:
        # Clean up on error
        gc.collect()
        print(f"Unexpected error: {str(e)}")
        return jsonify({'error': f'Conversion failed: {str(e)}'}), 500

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
        images = convert_from_bytes(pdf_bytes, dpi=150, fmt='png')
        
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
    poppler_status = check_poppler()
    return jsonify({
        'status': 'healthy', 
        'service': 'PDF to Image Converter',
        'optimized_for': 'n8n Cloud',
        'max_file_size': '50MB',
        'supported_formats': ['PDF'],
        'output_formats': ['PNG'],
        'poppler_installed': poppler_status
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'message': 'PDF to Image Converter API',
        'endpoints': {
            '/health': 'GET - Health check',
            '/pdf-to-images': 'POST - Convert PDF to images',
            '/pdf-to-images-zip': 'POST - Convert PDF to zip of images'
        },
        'usage': {
            'method': 'POST',
            'content_type': 'application/json',
            'body': {'pdfBase64': 'base64_encoded_pdf_data'}
        }
    })

# Add CORS headers for n8n Cloud
@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    return response

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))  # Render uses PORT env variable
    app.run(debug=False, host='0.0.0.0', port=port)
