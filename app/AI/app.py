import pytesseract
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

from controllers.data_transformation_controller import data_router
from controllers.rag_controller import rag_router

import logging
import os

pytesseract.pytesseract.tesseract_cmd = r"C:\dev\tesseract\tesseract.exe"

app = FastAPI(title="AI Backend API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router)
app.include_router(rag_router)


if __name__ == "__main__":
    import uvicorn
    
    print("AI Backend API Started on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)