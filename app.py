from flask import Flask, render_template, jsonify, request
from src.helper import download_hugging_face_embeddings
from langchain_pinecone import PineconeVectorStore
from langchain_openai import ChatOpenAI
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from dotenv import load_dotenv
import base64
from src.prompt import *
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(BASE_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from ml.intent_classifier import predict_intent

# ⬇ NEW: for CSV logging
import csv

app = Flask(__name__)

load_dotenv()

PINECONE_API_KEY = os.environ.get('PINECONE_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')

os.environ["PINECONE_API_KEY"] = PINECONE_API_KEY
os.environ["OPENAI_API_KEY"] = OPENAI_API_KEY

embeddings = download_hugging_face_embeddings()

index_name = "medical-chatbot"
docsearch = PineconeVectorStore.from_existing_index(
    index_name=index_name,
    embedding=embeddings
)

retriever = docsearch.as_retriever(search_type="similarity", search_kwargs={"k": 3})

chatModel = ChatOpenAI(
    model="openai/gpt-3.5-turbo",       
    openai_api_key=OPENAI_API_KEY,        
    openai_api_base="https://openrouter.ai/api/v1"
)

visionModel = ChatOpenAI(
    model="nvidia/nemotron-nano-12b-v2-vl:free",       
    openai_api_key=OPENAI_API_KEY,        
    openai_api_base="https://openrouter.ai/api/v1",
    max_tokens=800
)

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        ("human", "{input}"),
    ]
)


question_answer_chain = create_stuff_documents_chain(chatModel, prompt)
rag_chain = create_retrieval_chain(retriever, question_answer_chain)


CSV_PATH = "interactions.csv"

if not os.path.exists(CSV_PATH):
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "response"])   # header row


@app.route("/")
def index():
    return render_template('chat.html')


@app.route("/get", methods=["GET", "POST"])
def chat():
    msg = request.form.get("msg", "")
    image_file = request.files.get("image")
    user_input = msg

    print("User:", user_input)
    
    base64_image = None
    if image_file:
        file_bytes = image_file.read()
        if file_bytes:
            base64_image = base64.b64encode(file_bytes).decode('utf-8')
            print("Received an image upload.")

    if base64_image:
        # Route to Vision Model
        messages = [
            SystemMessage(content=vision_system_prompt),
            HumanMessage(
                content=[
                    {"type": "text", "text": user_input if user_input.strip() else "Please analyze this skin condition."},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{image_file.mimetype};base64,{base64_image}"
                        },
                    },
                ]
            )
        ]
        print("[VISION] Requesting analysis from Vision LLM...")
        try:
            response = visionModel.invoke(messages)
            answer = response.content
        except Exception as e:
            answer = "Sorry, there was an issue processing your image: " + str(e)
    else:
        # Standard RAG flow
        intent = predict_intent(user_input)
        print(f"[INTENT] {intent} | text = {user_input}")

        response = rag_chain.invoke({
            "input": user_input,
            "intent": intent
        })
        answer = response["answer"]

    print("Response:", answer)

    # 📝 Save to CSV
    log_text = f"[IMAGE] {user_input}" if base64_image else user_input
    try:
        with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([log_text, answer])
    except Exception as e:
        print("CSV logging error:", e)

    return str(answer)




if __name__ == '__main__':
    app.run(host="0.0.0.0", port=8080, debug=True)
