from flask import Blueprint
from services.data_transformation_services.transform_service import TransformService
from services.data_transformation_services.code_executor_service import CodeExecutorService
from services.data_transformation_services.dataframe_state_service import DataFrameStateService
from handlers.data_transformation_handlers.upload_handler import UploadHandler
from handlers.data_transformation_handlers.transform_handler import TransformHandler
from handlers.data_transformation_handlers.chat_handler import ChatHandler
from handlers.data_transformation_handlers.data_handler import DataHandler

data_bp = Blueprint('data_transformation', __name__)

df_state = DataFrameStateService()
coder_agent = TransformService()
code_executor = CodeExecutorService()
conversation_history = []

upload_handler = UploadHandler(df_state)
transform_handler = TransformHandler(df_state, coder_agent, code_executor)
chat_handler = ChatHandler(df_state, conversation_history)
data_handler = DataHandler(df_state)

@data_bp.route("/upload", methods=["POST"])
def upload_file():
    return upload_handler.handle_upload()

@data_bp.route("/transform", methods=["POST"])
def transform_data():
    return transform_handler.handle_transform()

@data_bp.route("/chat", methods=["POST"])
def chat_with_agent():
    return chat_handler.handle_chat()

@data_bp.route("/data", methods=["GET"])
def get_data_page():
    return data_handler.handle_data_retrieval()