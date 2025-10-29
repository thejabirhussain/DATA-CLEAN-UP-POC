from flask import request, jsonify
from services.rag_services.rag_service import RagSystem
from typing import Optional

class RagQueryHandler:
    def __init__(self, rag_system: Optional[RagSystem]):
        self.rag_system = rag_system
    
    def handle_query(self):
        data = request.get_json()
        if not data or 'question' not in data:
            return jsonify({"error": "No question provided"}), 400
        
        if self.rag_system is None:
            return jsonify({"error": "No PDF has been uploaded yet. Please upload a PDF first."}), 400
        
        try:
            response = self.rag_system.query(data['question'])
            return jsonify({
                "success": True,
                "answer": response
            })
        except Exception as e:
            return jsonify({"error": f"Error processing query: {str(e)}"}), 500