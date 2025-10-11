import io
import os
import pandas as pd
import pytesseract
from pydantic import BaseModel
from transform import CoderAgent
from code_executor import CodeExecutor
from chat_agent import ChatAgent, ConversationState
from rag import RagSystem
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import Optional
from datetime import datetime
from werkzeug.utils import secure_filename

pytesseract.pytesseract.tesseract_cmd = r"C:\dev\tesseract\tesseract.exe"

app = FastAPI(title="Excel AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

# Configure upload settings for RAG
PDF_UPLOAD_FOLDER = 'uploads/pdfs'
os.makedirs(PDF_UPLOAD_FOLDER, exist_ok=True)

current_dataframe: pd.DataFrame = None
# Maintain full history stacks for robust undo/redo
undo_stack: list[pd.DataFrame] = []
redo_stack: list[pd.DataFrame] = []

coder_agent = CoderAgent()
code_executor = CodeExecutor()
conversation_state = ConversationState()
chat_agent = ChatAgent()

# RAG system for document Q&A
rag_system: Optional[RagSystem] = None
gemini_api_key = os.getenv("GEMINI_API_KEY", "AIzaSyC5OZ6UW4rAgAunXVcaP-ZihOnJQgOLbG4")

def safe_to_dict(df: pd.DataFrame, orient='records'):
    df_clean = df.copy()
    df_clean = df_clean.where(pd.notnull(df_clean), None)
    return df_clean.to_dict(orient)

class TransformRequest(BaseModel):
    instruction: str
    model: Optional[str] = None

class CodeExecutionRequest(BaseModel):
    code: str

class ChatRequest(BaseModel):
    message: str

class RagQueryRequest(BaseModel):
    question: str

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    global current_dataframe, undo_stack, redo_stack
    
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Only Excel and CSV files are supported")
    
    try:
        contents = await file.read()
        
        if file.filename.endswith('.csv'):
            current_dataframe = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        else:
            current_dataframe = pd.read_excel(io.BytesIO(contents))
        
        # reset history stacks on new upload
        undo_stack = []
        redo_stack = []
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "shape": current_dataframe.shape,
            "columns": list(current_dataframe.columns),
            "preview": safe_to_dict(current_dataframe.head(100)),
            "total_rows": len(current_dataframe),
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

@app.post("/transform")
async def transform_data(request: TransformRequest):
    global current_dataframe, undo_stack, redo_stack
    
    try:
        generated_code = await coder_agent.process_instruction(
            request.instruction, 
            current_dataframe,
            "ollama"
        )

        # push current state to undo stack before applying transformation
        if current_dataframe is not None:
            undo_stack.append(current_dataframe.copy())
            # optional cap to prevent excessive memory
            if len(undo_stack) > 50:
                undo_stack.pop(0)
        # clear redo history when a new transform occurs
        redo_stack = []
        
        result_df, execution_log = code_executor.execute_code(generated_code, current_dataframe)
        
        current_dataframe = result_df
        current_dataframe.to_csv('data.csv', index=False)
        
        return {
            "success": True,
            "type": "transformation",
            "generated_code": generated_code,
            "execution_log": execution_log,
            "result_shape": current_dataframe.shape,
            "result_columns": list(current_dataframe.columns),
            "preview": safe_to_dict(current_dataframe.head(100)),
            "total_rows": len(current_dataframe),
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }
    except Exception as e:

        return {
            "error": str(e),
            "generated_code": generated_code if 'generated_code' in locals() else None
        }

@app.post("/undo")
async def undo_last_transformation():
    global current_dataframe, undo_stack, redo_stack
    if not undo_stack:
        return {
            "success": False,
            "error": "Nothing to undo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }

    print("Undo requested - restoring previous dataframe from stack")
    # move current to redo, pop last undo into current
    if current_dataframe is not None:
        redo_stack.append(current_dataframe)
    current_dataframe = undo_stack.pop()

    current_dataframe.to_csv('data.csv', index=False)
    print("Previous df restored and saved to data.csv file")

    return {
        "success": True,
        "type": "transformation",
        "message": "Successfully undone last transformation",
        "result_shape": current_dataframe.shape,
        "result_columns": list(current_dataframe.columns),
        "preview": safe_to_dict(current_dataframe.head(100)),
        "total_rows": len(current_dataframe),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    }

@app.post("/redo")
async def redo_last_undo():
    global current_dataframe, undo_stack, redo_stack
    if not redo_stack:
        return {
            "success": False,
            "error": "Nothing to redo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }

    print("Redo requested - re-applying last undone dataframe from stack")
    # move current to undo, pop last redo into current
    if current_dataframe is not None:
        undo_stack.append(current_dataframe)
        if len(undo_stack) > 50:
            undo_stack.pop(0)
    current_dataframe = redo_stack.pop()

    current_dataframe.to_csv('data.csv', index=False)

    return {
        "success": True,
        "type": "transformation",
        "message": "Successfully redone last undo",
        "result_shape": current_dataframe.shape,
        "result_columns": list(current_dataframe.columns),
        "preview": safe_to_dict(current_dataframe.head(100)),
        "total_rows": len(current_dataframe),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    }

@app.post("/chat")
async def chat_with_agent(request: ChatRequest):
    global current_dataframe, conversation_state, undo_stack, redo_stack
    try:
        # record user message
        conversation_state.messages.append({
            'role': 'user',
            'content': request.message,
            'timestamp': datetime.now().isoformat()
        })

        # get assistant response
        response = await chat_agent.chat(
            request.message,
            conversation_state.messages,
            current_dataframe
        )

        # record assistant message
        conversation_state.messages.append({
            'role': 'assistant',
            'content': response['message'],
            'code': response.get('code'),
            'timestamp': datetime.now().isoformat()
        })

        dataframe_updated = False
        if response.get('has_code') and response.get('execution_result'):
            execution_result = response['execution_result']
            if execution_result.get('success'):
                # push current to undo stack and clear redo
                if current_dataframe is not None:
                    undo_stack.append(current_dataframe.copy())
                    if len(undo_stack) > 50:
                        undo_stack.pop(0)
                redo_stack = []

                current_dataframe = execution_result['dataframe']
                current_dataframe.to_csv('data.csv', index=False)
                dataframe_updated = True

        # sanitize execution_result for response
        safe_execution_result = None
        if response.get('execution_result') is not None:
            er = dict(response['execution_result'])
            if 'dataframe' in er:
                er.pop('dataframe', None)
            if isinstance(er.get('original_shape'), (list, tuple)):
                er['original_shape'] = [int(x) for x in er['original_shape']]
            if isinstance(er.get('new_shape'), (list, tuple)):
                er['new_shape'] = [int(x) for x in er['new_shape']]
            if 'execution_log' in er and er['execution_log'] is not None:
                er['execution_log'] = str(er['execution_log'])
            if 'error' in er and er['error'] is not None:
                er['error'] = str(er['error'])
            safe_execution_result = er

        return {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated,
            'raw_response': response.get('raw_response'),
            'executed_code': response.get('executed_code'),
            'execution_result': safe_execution_result,
            'undo_count': len(undo_stack),
            'redo_count': len(redo_stack),
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

@app.get("/data")
async def get_data_page(page: int = 1, rows_per_page: int = 10):
    global current_dataframe, undo_stack, redo_stack
    if current_dataframe is None:
        raise HTTPException(status_code=400, detail="No data available")

    total_rows = len(current_dataframe)
    total_pages = (total_rows + rows_per_page - 1) // rows_per_page
    if total_pages == 0:
        total_pages = 1
    if page < 1 or page > total_pages:
        raise HTTPException(status_code=400, detail=f"Invalid page number. Must be between 1 and {total_pages}")

    start_idx = (page - 1) * rows_per_page
    end_idx = min(start_idx + rows_per_page, total_rows)
    page_data = current_dataframe.iloc[start_idx:end_idx]

    return {
        "data": safe_to_dict(page_data),
        "columns": list(current_dataframe.columns),
        "current_page": page,
        "total_pages": total_pages,
        "total_rows": total_rows,
        "rows_per_page": rows_per_page,
        "start_row": start_idx + 1,
        "end_row": end_idx,
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    }

@app.get("/chat/history")
async def get_chat_history():
    global conversation_state
    return {
        'messages': conversation_state.messages[-20:],
        'total_messages': len(conversation_state.messages)
    }

@app.post("/chat/clear")
async def clear_chat_history():
    global conversation_state
    conversation_state.messages = []
    return {'success': True, 'message': 'Chat history cleared'}

@app.post("/rag/upload")
async def upload_pdf(file: UploadFile = File(...)):
    global rag_system
    
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    
    try:
        # Save the uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.join(PDF_UPLOAD_FOLDER, filename)
        
        contents = await file.read()
        with open(filepath, 'wb') as f:
            f.write(contents)
        
        # Initialize RAG system and index the PDF
        rag_system = RagSystem(
            gemini_api_key=gemini_api_key,
            model="gemini-2.0-flash-exp"
        )
        rag_system.index_pdf(filepath)
        
        return {
            "success": True,
            "message": "PDF uploaded and processed successfully",
            "filename": filename
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing PDF: {str(e)}")

@app.post("/rag/query")
async def query_document(request: RagQueryRequest):
    global rag_system
    
    if rag_system is None:
        raise HTTPException(status_code=400, detail="No PDF has been uploaded yet. Please upload a PDF first.")
    
    if not request.question:
        raise HTTPException(status_code=400, detail="No question provided")
    
    try:
        response = rag_system.query(request.question)
        return {
            "success": True,
            "answer": response
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing query: {str(e)}")

@app.get("/rag/status")
async def get_rag_status():
    global rag_system
    
    return {
        "document_loaded": rag_system is not None,
        "pdf_name": os.path.basename(rag_system.pdf_path) if rag_system and rag_system.pdf_path else None
    }

@app.post("/rag/clear")
async def clear_rag_system():
    global rag_system
    rag_system = None
    return {
        "success": True,
        "message": "RAG system cleared"
    }

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index-react.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


if __name__ == "__main__":
    import uvicorn
    import logging
    
    # Hide uvicorn logs
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")