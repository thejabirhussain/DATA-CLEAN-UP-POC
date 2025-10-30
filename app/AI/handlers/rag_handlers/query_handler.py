from fastapi import HTTPException
from pydantic import BaseModel
from services.rag_services.rag_service import RagSystem
from typing import Optional

class QueryRequest(BaseModel):
    question: str

class RagQueryHandler:
    def __init__(self, rag_system: Optional[RagSystem]):
        self.rag_system = rag_system
    
    def handle_query(self, request: QueryRequest):
        if self.rag_system is None:
            raise HTTPException(status_code=400, detail="No PDF has been uploaded yet. Please upload a PDF first.")
        
        try:
            response = self.rag_system.query(request.question)
            return {
                "success": True,
                "answer": response
            }
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")