import io
import os
import pandas as pd
import pytesseract
from pydantic import BaseModel
from transform import CoderAgent
from code_executor import CodeExecutor
import chat_agent
from rag import RagSystem
from dataframe_state import DataFrameState
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File, HTTPException
from starlette.concurrency import run_in_threadpool

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

# Dataframe state management
df_state = DataFrameState()

# Maintain full history stacks for robust undo/redo
undo_stack: list[pd.DataFrame] = []
redo_stack: list[pd.DataFrame] = []

coder_agent = CoderAgent()
code_executor = CodeExecutor()
conversation_history = []

# RAG system for document Q&A
rag_system: Optional[RagSystem] = None

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
    global undo_stack, redo_stack
    
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Only Excel and CSV files are supported")
    
    try:
        contents = await file.read()
        
        if file.filename.endswith('.csv'):
            uploaded_df = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        else:
            uploaded_df = pd.read_excel(io.BytesIO(contents))
        
        # Set dataframe in state
        df_state.set_dataframe(uploaded_df)
        
        # reset history stacks on new upload
        undo_stack = []
        redo_stack = []
        
        # Save uploaded data to data.csv immediately
        df_state.get_dataframe().to_csv('data.csv', index=False)
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "shape": df_state.get_dataframe().shape,
            "columns": list(df_state.get_dataframe().columns),
            "preview": safe_to_dict(df_state.get_dataframe().head(100)),
            "total_rows": len(df_state.get_dataframe()),
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

@app.post("/transform")
async def transform_data(request: TransformRequest):
    global undo_stack, redo_stack
    
    try:
        generated_code = await coder_agent.process_instruction(
            request.instruction, 
            df_state.get_dataframe(),
            "ollama"
        )

        # push current state to undo stack before applying transformation
        if df_state.has_dataframe():
            undo_stack.append(df_state.get_dataframe().copy())
            # optional cap to prevent excessive memory
            if len(undo_stack) > 50:
                undo_stack.pop(0)
        # clear redo history when a new transform occurs
        redo_stack = []
        
        result_df, execution_log, error_msg = code_executor.execute_code(generated_code, df_state.get_dataframe())
        
        # Check if there was an error
        if error_msg:
            return {
                "success": False,
                "error": error_msg,
                "generated_code": generated_code
            }
        
        df_state.update_dataframe(result_df)
        df_state.get_dataframe().to_csv('data.csv', index=False)
        
        return {
            "success": True,
            "type": "transformation",
            "generated_code": generated_code,
            "execution_log": execution_log,
            "result_shape": df_state.get_dataframe().shape,
            "result_columns": list(df_state.get_dataframe().columns),
            "preview": safe_to_dict(df_state.get_dataframe().head(100)),
            "total_rows": len(df_state.get_dataframe()),
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
    global undo_stack, redo_stack
    if not undo_stack:
        return {
            "success": False,
            "error": "Nothing to undo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }

    print("Undo requested - restoring previous dataframe from stack")
    # move current to redo, pop last undo into current
    if df_state.has_dataframe():
        redo_stack.append(df_state.get_dataframe())
    df_state.update_dataframe(undo_stack.pop())

    df_state.get_dataframe().to_csv('data.csv', index=False)

    return {
        "success": True,
        "type": "transformation",
        "message": "Successfully undone last transformation",
        "result_shape": df_state.get_dataframe().shape,
        "result_columns": list(df_state.get_dataframe().columns),
        "preview": safe_to_dict(df_state.get_dataframe().head(100)),
        "total_rows": len(df_state.get_dataframe()),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    }

@app.post("/redo")
async def redo_last_undo():
    global undo_stack, redo_stack
    if not redo_stack:
        return {
            "success": False,
            "error": "Nothing to redo",
            "undo_count": len(undo_stack),
            "redo_count": len(redo_stack),
        }

    print("Redo requested - re-applying last undone dataframe from stack")
    # move current to undo, pop last redo into current
    if df_state.has_dataframe():
        undo_stack.append(df_state.get_dataframe())
        if len(undo_stack) > 50:
            undo_stack.pop(0)
    df_state.update_dataframe(redo_stack.pop())

    df_state.get_dataframe().to_csv('data.csv', index=False)

    return {
        "success": True,
        "type": "transformation",
        "message": "Successfully redone last undo",
        "result_shape": df_state.get_dataframe().shape,
        "result_columns": list(df_state.get_dataframe().columns),
        "preview": safe_to_dict(df_state.get_dataframe().head(100)),
        "total_rows": len(df_state.get_dataframe()),
        "undo_count": len(undo_stack),
        "redo_count": len(redo_stack),
    }


@app.post("/chat")
async def chat_with_agent(request: ChatRequest):
    global conversation_history, undo_stack, redo_stack
    try:
        # record user message
        conversation_history.append({
            'role': 'user',
            'content': request.message,
            'timestamp': datetime.now().isoformat()
        })

        # Capture dataframe state before chat in case chat_agent modifies it internally
        pre_df = df_state.get_dataframe().copy() if df_state.has_dataframe() else None

        response = await run_in_threadpool(
            chat_agent.chat,
            request.message,
            conversation_history,
            df_state
        )

        conversation_history.append({
            'role': 'assistant',
            'content': response['message'],
            'code': response.get('code'),
            'timestamp': datetime.now().isoformat()
        })

        dataframe_updated = False
        # Case 1: explicit execution_result in response
        if response.get('has_code') and response.get('execution_result'):
            execution_result = response['execution_result']
            if execution_result.get('success'):
                # push current to undo stack and clear redo
                if df_state.has_dataframe():
                    undo_stack.append(df_state.get_dataframe().copy())
                    if len(undo_stack) > 50:
                        undo_stack.pop(0)
                redo_stack = []

                df_state.update_dataframe(execution_result['dataframe'])
                df_state.get_dataframe().to_csv('data.csv', index=False)
                dataframe_updated = True
        else:
            # Case 2: chat_agent may have internally executed code and updated df_state
            if pre_df is not None and df_state.has_dataframe():
                try:
                    post_df = df_state.get_dataframe()
                    changed = not pre_df.equals(post_df)
                except Exception:
                    changed = True
                if changed:
                    # push pre-change to undo stack, clear redo
                    undo_stack.append(pre_df)
                    if len(undo_stack) > 50:
                        undo_stack.pop(0)
                    redo_stack = []
                    try:
                        df_state.get_dataframe().to_csv('data.csv', index=False)
                    except Exception:
                        pass
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

        # Prepare response
        chat_response = {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated,
            'raw_response': response.get('raw_response'),
            'executed_code': response.get('executed_code'),
            'execution_result': safe_execution_result,
            'undo_count': len(undo_stack),
            'redo_count': len(redo_stack),
        }
        
        # Add updated dataframe preview if dataframe was updated
        if dataframe_updated and df_state.has_dataframe():
            chat_response.update({
                'updated_preview': safe_to_dict(df_state.get_dataframe().head(100)),
                'updated_columns': list(df_state.get_dataframe().columns),
                'updated_shape': df_state.get_dataframe().shape,
                'updated_total_rows': len(df_state.get_dataframe()),
            })
        
        return chat_response
    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

@app.get("/data")
async def get_data_page(page: int = 1, rows_per_page: int = 10):
    global undo_stack, redo_stack
    if not df_state.has_dataframe():
        raise HTTPException(status_code=400, detail="No data available")

    current_df = df_state.get_dataframe()
    total_rows = len(current_df)
    total_pages = (total_rows + rows_per_page - 1) // rows_per_page
    if total_pages == 0:
        total_pages = 1
    if page < 1 or page > total_pages:
        raise HTTPException(status_code=400, detail=f"Invalid page number. Must be between 1 and {total_pages}")

    start_idx = (page - 1) * rows_per_page
    end_idx = min(start_idx + rows_per_page, total_rows)
    page_data = current_df.iloc[start_idx:end_idx]

    return {
        "data": safe_to_dict(page_data),
        "columns": list(current_df.columns),
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
    global conversation_history
    return {
        'messages': conversation_history[-20:],
        'total_messages': len(conversation_history)
    }

@app.post("/chat/clear")
async def clear_chat_history():
    global conversation_history
    conversation_history = []
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
        rag_system = RagSystem(model="llama3.1:8b", pdf_filename=filename)
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
    
    print("App Started")
    
    # Hide uvicorn logs
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="warning")