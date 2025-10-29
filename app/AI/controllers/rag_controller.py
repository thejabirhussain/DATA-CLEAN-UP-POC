import os
from flask import Blueprint
from services.rag_services.rag_service import RagSystem
from typing import Optional
from handlers.rag_handlers.upload_handler import RagUploadHandler
from handlers.rag_handlers.query_handler import RagQueryHandler
from handlers.rag_handlers.status_handler import RagStatusHandler

rag_bp = Blueprint('rag', __name__)

PDF_UPLOAD_FOLDER = 'storage/uploads/pdfs'
os.makedirs(PDF_UPLOAD_FOLDER, exist_ok=True)

rag_system: Optional[RagSystem] = None

upload_handler = RagUploadHandler(rag_system, PDF_UPLOAD_FOLDER)
query_handler = RagQueryHandler(rag_system)
status_handler = RagStatusHandler(rag_system)

@rag_bp.route("/rag/upload", methods=["POST"])
def upload_pdfs():
    global rag_system
    try:
        result = upload_handler.handle_upload()
        rag_system = upload_handler.get_rag_system()
        query_handler.rag_system = rag_system
        status_handler.rag_system = rag_system
        return result
    except Exception as e:
        from flask import jsonify
        return jsonify({"error": f"Server error: {str(e)}"}), 500

@rag_bp.route("/rag/status", methods=["GET"])
def get_rag_status():
    status_handler.rag_system = rag_system
    return status_handler.handle_status()

@rag_bp.route("/rag/query", methods=["POST"])
def query_document():
    query_handler.rag_system = rag_system
    return query_handler.handle_query()