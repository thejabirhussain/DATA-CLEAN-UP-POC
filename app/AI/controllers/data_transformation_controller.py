from fastapi import APIRouter, UploadFile, File, Query
from services.data_transformation_services.transform_service import TransformService
from services.data_transformation_services.code_executor_service import CodeExecutorService
from services.data_transformation_services.dataframe_state_service import DataFrameStateService
from handlers.data_transformation_handlers.upload_handler import UploadHandler
from handlers.data_transformation_handlers.transform_handler import TransformHandler, TransformRequest
from handlers.data_transformation_handlers.chat_handler import ChatHandler, ChatRequest
from handlers.data_transformation_handlers.data_handler import DataHandler

data_router = APIRouter(prefix="/data", tags=["data_transformation"])

df_state = DataFrameStateService()
coder_agent = TransformService()
code_executor = CodeExecutorService()
conversation_history = []

upload_handler = UploadHandler(df_state)
transform_handler = TransformHandler(df_state, coder_agent, code_executor)
chat_handler = ChatHandler(df_state, conversation_history)
data_handler = DataHandler(df_state)

@data_router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    return await upload_handler.handle_upload(file)

@data_router.post("/transform")
def transform_data(request: TransformRequest):
    return transform_handler.handle_transform(request)

@data_router.post("/chat")
def chat_with_agent(request: ChatRequest):
    return chat_handler.handle_chat(request)

@data_router.get("/")
def get_data_page(page: int = Query(1, ge=1), rows_per_page: int = Query(10, ge=1, le=1000)):
    return data_handler.handle_data_retrieval(page, rows_per_page)