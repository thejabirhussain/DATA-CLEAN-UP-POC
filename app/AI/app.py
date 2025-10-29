import pytesseract
from flask import Flask, jsonify
from flask_cors import CORS
from datetime import datetime

from controllers.data_transformation_controller import data_bp
from controllers.rag_controller import rag_bp

import logging
import os

pytesseract.pytesseract.tesseract_cmd = r"C:\dev\tesseract\tesseract.exe"

app = Flask(__name__)
CORS(app)

app.register_blueprint(data_bp)
app.register_blueprint(rag_bp)

@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "service": "AI Backend API",
        "timestamp": datetime.now().isoformat()
    })

if __name__ == "__main__":
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    print("AI Backend API Started on http://localhost:8000")
    app.run(host="0.0.0.0", port=8000, debug=False)