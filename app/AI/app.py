import io
import pandas as pd
from pydantic import BaseModel
from coder import CoderAgent
from code_executor import CodeExecutor
from chat_agent import ChatAgent, ConversationState
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI, UploadFile, File, HTTPException
from typing import Optional
from datetime import datetime

app = FastAPI(title="Excel NLP Transformer", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")

current_dataframe: pd.DataFrame = None
previous_dataframe: pd.DataFrame = None

coder_agent = CoderAgent()
code_executor = CodeExecutor()
conversation_state = ConversationState()
chat_agent = ChatAgent()

def safe_to_dict(df: pd.DataFrame, orient='records'):
    df_clean = df.copy()
    df_clean = df_clean.where(pd.notnull(df_clean), None)
    return df_clean.to_dict(orient)

class TransformRequest(BaseModel):
    instruction: str

class CodeExecutionRequest(BaseModel):
    code: str

class ChatRequest(BaseModel):
    message: str

@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    global current_dataframe, previous_dataframe
    
    if not file.filename.endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(status_code=400, detail="Only Excel and CSV files are supported")
    
    try:
        contents = await file.read()
        
        if file.filename.endswith('.csv'):
            current_dataframe = pd.read_csv(io.StringIO(contents.decode('utf-8')))
        else:
            current_dataframe = pd.read_excel(io.BytesIO(contents))
        
        previous_dataframe = None
        
        return {
            "message": "File uploaded successfully",
            "filename": file.filename,
            "shape": current_dataframe.shape,
            "columns": list(current_dataframe.columns),
            "preview": safe_to_dict(current_dataframe.head(100)),
            "total_rows": len(current_dataframe)
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error processing file: {str(e)}")

@app.post("/transform")
async def transform_data(request: TransformRequest):
    global current_dataframe
    

    
    try:
        generated_code = await coder_agent.process_instruction(
            request.instruction, 
            current_dataframe
        )

        
        global previous_dataframe
        previous_dataframe = current_dataframe.copy()
        
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
            "total_rows": len(current_dataframe)
        }
    
    except Exception as e:

        return {
            "error": str(e),
            "generated_code": generated_code if 'generated_code' in locals() else None
        }



@app.post("/undo")
async def undo_last_transformation():
    global current_dataframe, previous_dataframe
    
    if previous_dataframe is None:
        return {
            "success": False,
            "error": "No previous version available to undo"
        }
    
    print("Undo requested - restoring previous dataframe")
    
    temp = current_dataframe
    current_dataframe = previous_dataframe
    previous_dataframe = temp
    
    current_dataframe.to_csv('data.csv', index=False)
    print("Previous df restored and saved to data.csv file")
    
    return {
        "success": True,
        "type": "transformation",
        "message": "Successfully undone last transformation",
        "result_shape": current_dataframe.shape,
        "result_columns": list(current_dataframe.columns),
        "preview": safe_to_dict(current_dataframe.head(100)),
        "total_rows": len(current_dataframe)
    }

@app.get("/data")
async def get_data_page(page: int = 1, rows_per_page: int = 10):
    global current_dataframe
    
    if current_dataframe is None:
        raise HTTPException(status_code=400, detail="No data available")
    
    total_rows = len(current_dataframe)
    total_pages = (total_rows + rows_per_page - 1) // rows_per_page
    
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
        "end_row": end_idx
    }

@app.post("/chat")
async def chat_with_agent(request: ChatRequest):
    global current_dataframe, conversation_state
    
    try:
        print(f"\nUSER: {request.message}")
        
        conversation_state.messages.append({
            'role': 'user',
            'content': request.message,
            'timestamp': datetime.now().isoformat()
        })
        
        response = await chat_agent.chat(
            request.message, 
            conversation_state.messages, 
            current_dataframe
        )
        
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
                global previous_dataframe
                previous_dataframe = current_dataframe.copy()
                current_dataframe = execution_result['dataframe']
                current_dataframe.to_csv('data.csv', index=False)
                dataframe_updated = True

        
        return {
            'success': True,
            'message': response['message'],
            'dataframe_updated': dataframe_updated
        }
        
    except Exception as e:

        return {
            'success': False,
            'error': str(e)
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

@app.get("/", response_class=HTMLResponse)
async def read_root():
    with open("static/index-react.html", "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)