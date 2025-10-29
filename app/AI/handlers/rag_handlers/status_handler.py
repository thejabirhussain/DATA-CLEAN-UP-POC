from flask import jsonify
from services.rag_services.rag_service import RagSystem
from typing import Optional

class RagStatusHandler:
    def __init__(self, rag_system: Optional[RagSystem]):
        self.rag_system = rag_system
    
    def handle_status(self):
        return jsonify({
            "document_loaded": self.rag_system is not None and hasattr(self.rag_system, 'pdf_names') and len(self.rag_system.pdf_names) > 0,
            "pdf_names": self.rag_system.pdf_names if self.rag_system and hasattr(self.rag_system, 'pdf_names') else []
        })