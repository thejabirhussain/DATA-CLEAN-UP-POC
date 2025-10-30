import os
from fastapi import APIRouter, HTTPException, UploadFile, File
from services.rag_services.rag_service import RagSystem
from typing import Optional, List
from handlers.rag_handlers.upload_handler import RagUploadHandler
from handlers.rag_handlers.query_handler import RagQueryHandler, QueryRequest
from handlers.rag_handlers.status_handler import RagStatusHandler

rag_router = APIRouter(prefix="/rag", tags=["rag"])

PDF_UPLOAD_FOLDER = 'storage/uploads/pdfs'
os.makedirs(PDF_UPLOAD_FOLDER, exist_ok=True)

rag_system: Optional[RagSystem] = None

upload_handler = RagUploadHandler(rag_system, PDF_UPLOAD_FOLDER)
query_handler = RagQueryHandler(rag_system)
status_handler = RagStatusHandler(rag_system)

@rag_router.post("/upload")
async def upload_pdfs(files: List[UploadFile] = File(...)):
    global rag_system
    try:
        result = await upload_handler.handle_upload(files)
        rag_system = upload_handler.get_rag_system()
        query_handler.rag_system = rag_system
        status_handler.rag_system = rag_system
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@rag_router.get("/status")
def get_rag_status():
    status_handler.rag_system = rag_system
    return status_handler.handle_status()

@rag_router.post("/query")
def query_document(request: QueryRequest):
    query_handler.rag_system = rag_system
    return query_handler.handle_query(request)