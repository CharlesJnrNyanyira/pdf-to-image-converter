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
import sys
import traceback
from datetime import datetime

app = Flask(__name__)

# Configure for Render with better memory handling
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB limit

def check_poppler():
    """Check if poppler is installed"""
    try:
        result = subprocess.run(['pdftoppm', '-h'], capture_output=True, text=True)
        return True
    except FileNotFoundError:
        return False

def log_memory_usage():
    """Log current memory usage"""
    try:
        import psutil
        process = psutil.Process(os.getpid())
        memory_mb = process.memory_info().rss / 1024 / 1024
        print(f"Memory usage: {memory_mb:.1f} MB")
    except ImportError:
        pass

def cleanup_memory():
    """Force garbage collection and memory cleanup"""
    gc.collect()
    gc.collect()  # Run twice for better cleanup
    gc.collect()

@app.route('/pdf-to-images', methods=['POST'])
def pdf_to_images():
    start_time = datetime.now()
    pdf_bytes = None
    pdf_base64 = None
    images = None
    
    try:
        print(f"[{start_time}] Starting PDF conversion request")
        log_memory_usage()
        
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
        
        print(f"Received base64 data length: {len(pdf_base64)}")
        
        try:
            pdf_bytes = base64.b64decode(pdf_base64)
            print(f"Decoded PDF size: {len(pdf_bytes)} bytes")
        except Exception as e:
            return jsonify({'error': f'Invalid base64 data: {str(e)}'}), 400
        
        # Clear base64 data from memory immediately
        pdf_base64 = None
        data = None
        cleanup_memory()
        
        # Validate PDF header
        if not pdf_bytes.startswith(b'%PDF'):
            return jsonify({'error': 'Data does not appear to be a valid PDF file'}), 400
        
        print(f"Processing PDF: {len(pdf_bytes)} bytes")
        log_memory_usage()
        
        # Convert PDF to images with optimized settings
        try:
            # Use lower DPI for memory efficiency, but you can increase if needed
            dpi = 150  # Change to 300 if you need higher quality
            
            images = convert_from_bytes(
                pdf_bytes, 
                dpi=dpi,
                fmt='png',
                thread_count=1,  # Single thread to avoid memory issues
                first_page=None,
                last_page=None,
                poppler_path=None,
                # Additional memory optimization
                grayscale=False,  # Set to True if you want to save memory
                transparent=False
            )
            
            print(f"pdf2image completed successfully")
            
        except Exception as e:
            print(f"pdf2image error: {str(e)}")
            print(f"Traceback: {traceback.format_exc()}")
            return jsonify({'error': f'PDF conversion failed: {str(e)}'}), 500
        
        if not images:
            return jsonify({'error': 'No pages found in PDF or conversion failed'}), 400
        
        print(f"Converted to {len(images)} images")
        log_memory_usage()
        
        # Free up PDF bytes from memory immediately
        pdf_bytes = None
        cleanup_memory()
        
        # Process images one by one to minimize memory usage
        result_images = []
        
        for i, image in enumerate(images):
            try:
                print(f"Processing image {i+1}/{len(images)}")
                
                # Convert PIL image to bytes with optimization
                img_buffer = io.BytesIO()
                
                # Optimize image settings for smaller size and faster processing
                image.save(
                    img_buffer, 
                    format='PNG', 
                    optimize=True, 
                    compress_level=6,  # Good compression without too much CPU
                    pnginfo=None  # Remove metadata to save space
                )
                img_buffer.seek(0)
                
                # Encode to base64
                img_base64 = base64.b64encode(img_buffer.getvalue()).decode('utf-8')
                
                result_images.append({
                    'page': i + 1,
                    'image_base64': img_base64,
                    'width': image.width,
                    'height': image.height
                })
                
                # Clean up immediately
                img_buffer.close()
                img_buffer = None
                img_base64 = None
                
                # Force cleanup every image to prevent memory buildup
                if i % 2 == 0:  # Cleanup every other image
                    cleanup_memory()
                
            except Exception as e:
                print(f"Error processing page {i+1}: {str(e)}")
                continue
        
        # Clean up images from memory
        images = None
        cleanup_memory()
        
        if not result_images:
            return jsonify({'error': 'Failed to process any pages from PDF'}), 500
        
        end_time = datetime.now()
        processing_time = (end_time - start_time).total_seconds()
        
        print(f"Conversion completed in {processing_time:.2f} seconds")
        log_memory_usage()
        
        response_data = {
            'success': True,
            'total_pages': len(result_images),
            'images': result_images,
            'processing_time': processing_time
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        # Clean up on error
        pdf_bytes = None
        pdf_base64 = None
        images = None
        cleanup_memory()
        
        error_msg = str(e)
        print(f"Unexpected error: {error_msg}")
        print(f"Traceback: {traceback.format_exc()}")
        
        return jsonify({
            'error': f'Conversion failed: {error_msg}',
            'error_type': type(e).__name__
        }), 500

@app.route('/pdf-to-images-zip', methods=['POST'])
def pdf_to_images_zip():
    """Alternative endpoint that returns a zip file download link"""
    try:
        data = request.get_json()
        
        if not data or 'pdfBase64' not in data:
            return jsonify({'error': 'No pdfBase64 data provided'}), 400
            
        pdf_base64 = data['pdfBase64']
        pdf_bytes = base64.b64decode(pdf_base64)
        
        # Convert PDF to images with memory optimization
        images = convert_from_bytes(
            pdf_bytes, 
            dpi=150, 
            fmt='png',
            thread_count=1
        )
        
        # Clean up PDF data
        pdf_bytes = None
        pdf_base64 = None
        cleanup_memory()
        
        # Create zip file in memory
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zip_file:
            for i, image in enumerate(images):
                img_buffer = io.BytesIO()
                image.save(img_buffer, format='PNG', optimize=True)
                zip_file.writestr(f'page_{i+1}.png', img_buffer.getvalue())
                img_buffer.close()
        
        # Clean up images
        images = None
        cleanup_memory()
        
        zip_buffer.seek(0)
        zip_base64 = base64.b64encode(zip_buffer.getvalue()).decode('utf-8')
        zip_buffer.close()
        
        return jsonify({
            'success': True,
            'total_pages': len(images) if images else 0,
            'zip_base64': zip_base64
        })
        
    except Exception as e:
        cleanup_memory()
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    poppler_status = check_poppler()
    
    # Check available memory
    memory_info = "Unknown"
    try:
        import psutil
        memory = psutil.virtual_memory()
        memory_info = f"{memory.available / 1024 / 1024 / 1024:.1f}GB available"
    except ImportError:
        pass
    
    return jsonify({
        'status': 'healthy', 
        'service': 'PDF to Image Converter',
        'optimized_for': 'Render.com',
        'max_file_size': '50MB',
        'supported_formats': ['PDF'],
        'output_formats': ['PNG'],
        'poppler_installed': poppler_status,
        'memory_info': memory_info,
        'python_version': sys.version
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({
        'message': 'PDF to Image Converter API - Memory Optimized',
        'endpoints': {
            '/health': 'GET - Health check',
            '/pdf-to-images': 'POST - Convert PDF to images',
            '/pdf-to-images-zip': 'POST - Convert PDF to zip of images'
        },
        'usage': {
            'method': 'POST',
            'content_type': 'application/json',
            'body': {'pdfBase64': 'base64_encoded_pdf_data'}
        },
        'optimizations': [
            'Memory cleanup after each operation',
            'Aggressive garbage collection',
            'Optimized image compression',
            'Single-threaded processing for stability'
        ]
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
