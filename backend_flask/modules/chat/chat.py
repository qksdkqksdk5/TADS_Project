import os
import re
from datetime import datetime
from flask import Blueprint, request, jsonify
from openai import OpenAI
from sqlalchemy import create_engine, text
from dotenv import load_dotenv
from pymongo import MongoClient

# --- LangChain 관련 임포트 (보내주신 코드 반영) ---
from langchain_community.document_loaders import TextLoader
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
chat_bp = Blueprint('chat', __name__)

# 1. DB 및 OpenAI 설정
DB_URL = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_engine(DB_URL)

# MongoDB 연결 추가
MONGO_URI = os.getenv("MONGO_URI")
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client["TADS_DB"]          # DB 이름
history_col = mongo_db["chat_history"]      # 컬렉션 이름

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

last_intent = "UNKNOWN"

# 2. RAG 초기화 로직 (TADS_knowledge.txt 로드)
def init_rag_system():
    knowledge_path = os.path.join(BASE_DIR, "TADS_knowledge.txt")
    persist_db_path = os.path.join(BASE_DIR, "chroma_db")

    if not os.path.exists(knowledge_path):
        print(f"경고: {knowledge_path} 파일이 없습니다.")
        return None
    
    loader = TextLoader(knowledge_path, encoding='utf-8')
    documents = loader.load()
    
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    docs = text_splitter.split_documents(documents)
    
    embeddings = OpenAIEmbeddings()
    # 서버 실행 시마다 새로 생성하지 않도록 persist_directory 활용
    vectorstore = Chroma.from_documents(
        documents=docs, 
        embedding=embeddings, 
        persist_directory=persist_db_path
    )
    return vectorstore

# 서버 시작 시 벡터 DB 로드
vector_db = init_rag_system()

# 3. SQL 스키마 컨텍스트 (보내주신 내용 그대로 활용)
with open(os.path.join(BASE_DIR, "schema_context.txt"), "r", encoding="utf-8") as f:
    SCHEMA_CONTEXT = f.read()

@chat_bp.route('/ask', methods=['POST'])
def ask_tads():
    global last_intent
    
    data = request.json
    user_question = data.get('question')
    user_name = data.get('userName', '익명 사용자')  # user_name이 없으면 '익명 사용자'로 처리
    intent = "UNKNOWN"
    row_count = 0
    rows = []          
    query = ""
    knowledge_context = ""

    if not user_question:
        return jsonify({"answer": "질문을 입력해 주세요."}), 400

    try:

        # --- [추가] MongoDB에서 이 사용자의 마지막 대화 1건 가져오기 ---
        last_log = history_col.find_one(
            {"user_name": user_name}, 
            sort=[("timestamp", -1)]
        )
        prev_info = ""
        if last_log:
            prev_info = f"사용자의 직전 질문: {last_log['user_question']}\nAI의 직전 답변: {last_log['ai_answer']}"

        # --- [Step 1] 의도 파악 (SQL인지 RAG인지 판단) ---
        intent_completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"""사용자 질문의 의도를 'SQL', 'RAG', 'BOTH' 중 하나로 분류하세요.
                    이전 질문의 의도는 {last_intent}였습니다. 이를 참고하여 현재 질문의 의도를 분류하세요.
                    
                    만약 '화재는?', '역주행은?' 처럼 질문이 짧고 이전 의도가 SQL이었다면, 
                    이번에도 해당 항목의 데이터를 조회하려는 SQL 의도로 간주하세요.
                    
                    1. SQL: '결과', '목록', '기록', '데이터', '찾아줘', '보여줘', '~영상' 등 특정 데이터를 조회하려는 의도가 조금이라도 있는 경우.
                    2. RAG: 시스템의 정의, 작동 원리, 대처 방법, 기능 설명 등 일반적인 지식을 묻는 경우.
                    3. BOTH: 데이터를 보여주면서 동시에 설명이나 절차도 필요한 경우 (예: "화재 결과 보여주고 어떻게 처리하는지도 알려줘").

                    - 사용자가 본인의 '마지막 질문', '과거 기록' 등을 물어보는 것은 SQL 조회가 아닌 대화 맥락 확인이므로 반드시 'RAG'로 분류하세요.
                    아래의 이전 대화 내용을 참고하여 사용자가 '마지막 질문'이나 '아까 말한 거' 등을 언급하면 문맥을 파악하세요.
                    [이전 대화 정보]
                    {prev_info if prev_info else "이전 기록 없음"}
                    """
                },
                {"role": "user", "content": user_question}
            ],
            temperature=0
        )
        intent = intent_completion.choices[0].message.content.strip().upper()
        last_intent = intent

        # --- [Step 2] RAG 지식 검색 ---
        if intent in ['RAG', 'BOTH', 'UNKNOWN']:
            if vector_db:
                related_docs = vector_db.similarity_search(user_question, k=2)
                knowledge_context = "\n".join([doc.page_content for doc in related_docs])

        # --- [Step 3] SQL 생성 및 DB 실행 ---
        if intent in ['SQL', 'BOTH']:
            sql_completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SCHEMA_CONTEXT + "\n순수 SQL만 반환하세요."},
                    {"role": "user", "content": user_question}
                ],
                temperature=0
            )
            raw_query = sql_completion.choices[0].message.content.strip()
            match = re.search(r"(SELECT.*)", raw_query, re.IGNORECASE | re.DOTALL)
            query = match.group(1).split(';')[0] + ';' if match else raw_query

            if "SELECT" in query.upper():
                with engine.connect() as connection:
                    result = connection.execute(text(query))
                    rows = [dict(row._mapping) for row in result]
                    # [중요] row_count를 여기서 업데이트해야 합니다!
                    row_count = len(rows)

       # --- Step 4: 최종 답변 생성 부분 수정 ---

        # 확실한 조건부 플래그 설정
        is_sql_intent = intent in ['SQL', 'BOTH']
        has_data = row_count > 0

        answer_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"""당신은 TADS 관제 시스템 비서입니다.

                    [순위 1: 대화 문맥 질문]
                    - 질문에 '마지막', '이전', '아까', '답변' 등이 포함된 경우:
                    데이터 건수나 운영 지침을 무시하고 [직전 대화 기록]의 'user_question'이나 'ai_answer'를 사용하여 답변하세요. 
                    (예: "마지막 질문은 ~였고, 답변은 ~라고 드렸습니다.")

                    [순위 2: 방법/절차 질문 (RAG)]
                    - 질문이 '~방법', '~절차', '~어떻게' 등을 묻는 경우:
                    데이터 건수(0건 등)를 언급하지 말고 바로 [운영 지침]을 설명하세요.

                    [순위 3: 데이터 조회 질문 (SQL)]
                    - 위 케이스가 아니며 실시간 목록을 찾는 경우:
                    - 데이터가 있으면: "총 {row_count}건이 확인되었습니다. 상세 내역은 표를 확인해 주세요."
                    - 데이터가 없으면: "조회 결과 해당 데이터가 존재하지 않습니다."

                    [데이터 소스]
                    - 직전 대화: {prev_info}
                    - 운영 지침: {knowledge_context}
                    
                    """
                },
                {
                    "role": "user", 
                    "content": f"질문: {user_question}\n판단된 의도: {intent}\n실제 데이터 건수: {row_count}건"
                }
            ],
            temperature=0
        )
        final_answer = answer_response.choices[0].message.content

        try:
            history_col.insert_one({
                "timestamp": datetime.now(),
                "user_name": user_name,
                "user_question": user_question,
                "ai_answer": final_answer,
                "intent": intent,
                "sql_query": query if query else None,
                "row_count": row_count,
                "success": True
            })
        except Exception as mongo_err:
            print(f"MongoDB 저장 실패: {mongo_err}") # DB 저장 실패가 서비스 중단으로 이어지지 않게 처리
        
        return jsonify({
            "answer": answer_response.choices[0].message.content,
            "data": rows,
            "query": query
        })

    except Exception as e:
        print(f"에러 발생: {e}")
        return jsonify({"answer": f"분석 중 오류 발생: {str(e)}"}), 500