import os
from flask import request, jsonify
from werkzeug.utils import secure_filename
from services.rag_services.rag_service import RagSystem
from typing import Optional

class RagUploadHandler:
    def __init__(self, rag_system: Optional[RagSystem], upload_folder: str):
        self.rag_system = rag_system
        self.upload_folder = upload_folder
    
    def handle_upload(self):
        try:
            files = []
            
            if 'file' in request.files:
                single_file = request.files['file']
                if single_file.filename != '':
                    files.append(single_file)
            
            if 'files' in request.files:
                multiple_files = request.files.getlist('files')
                files.extend([f for f in multiple_files if f.filename != ''])
            
            if not files:
                return jsonify({"error": "No files provided. Use 'file' for single upload or 'files' for multiple uploads"}), 400
            
            for file in files:
                if not file.filename.endswith('.pdf'):
                    return jsonify({"error": f"File {file.filename} is not a PDF. Only PDF files are supported"}), 400
            
            processed_files = []
            failed_files = []
            
            try:
                if self.rag_system is None:
                    self.rag_system = RagSystem(model="llama3.1:8b")
            except Exception as e:
                return jsonify({"error": f"Failed to initialize RAG system: {str(e)}"}), 500
            
            for file in files:
                try:
                    filename = secure_filename(file.filename)
                    filepath = os.path.join(self.upload_folder, filename)
                    
                    file.save(filepath)
                    
                    self.rag_system.index_pdf(filepath)
                    processed_files.append(filename)
                    
                except Exception as e:
                    failed_files.append({
                        "filename": file.filename,
                        "error": str(e)
                    })
            
            file_count = len(processed_files)
            if file_count == 1:
                message = f"Successfully processed 1 PDF: {processed_files[0]}"
            else:
                message = f"Successfully processed {file_count} PDFs"
            
            return jsonify({
                "success": len(failed_files) == 0,
                "message": message,
                "filenames": processed_files,
                "failed_files": failed_files,
                "total_processed": file_count
            })
            
        except Exception as e:
            print(f"RAG Upload Error: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({"error": f"Unexpected error: {str(e)}"}), 500
    
    def get_rag_system(self):
        return self.rag_system