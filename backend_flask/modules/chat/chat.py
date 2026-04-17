# modules/chat/chat.py
import os
import json
from flask import Blueprint, request, jsonify
from openai import OpenAI
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

chat_bp = Blueprint('chat', __name__)

# OpenAI 클라이언트 및 DB 엔진 설정
api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=api_key)
DB_URL = f"mysql+pymysql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
engine = create_engine(DB_URL)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(BASE_DIR, "schema_context.txt"), "r", encoding="utf-8") as f:
    SCHEMA_CONTEXT = f.read()

@chat_bp.route('/ask', methods=['POST'])
def ask_tads():
    data = request.json
    user_question = data.get('question')

    if not user_question:
        return jsonify({"answer": "질문을 입력해 주세요."}), 400

    try:
        # Step 1: SQL 생성
        sql_completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SCHEMA_CONTEXT},
                {"role": "user", "content": user_question}
            ]
        )
        query = sql_completion.choices[0].message.content.strip().replace("```sql", "").replace("```", "")

        # Step 2: DB 실행
        with engine.connect() as connection:
            result = connection.execute(text(query))
            rows = [dict(row._mapping) for row in result]

        # Step 3: 답변 생성 (chat.py 내 수정)
        num_rows = len(rows)
        data_str = json.dumps(rows, ensure_ascii=False, default=str) if rows else "데이터 없음"
        
        answer_response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system", 
                    "content": f"""당신은 TADS 관제 시스템 비서입니다.
                    1. 답변은 아주 간결하게 총 건수만 말하세요. (예: "조회된 역주행 내역은 총 {num_rows}건입니다.")
                    2. 상세 내역을 텍스트로 나열하지 마세요. 
                    3. 마지막에 '상세 내용은 아래 표를 확인해 주세요.'라고만 덧붙이세요.
                    4. 데이터가 0건이면 '해당 조건으로 조회된 내역이 없습니다.'라고 답하세요."""
                },
                {"role": "user", "content": f"질문: {user_question}\n실제 데이터: {data_str}"}
            ]
        )
        
        return jsonify({
            "answer": answer_response.choices[0].message.content,
            "query": query, # (선택) 디버깅용으로 쿼리도 같이 전달 가능
            "data": rows
        })

    except Exception as e:
        return jsonify({"answer": f"분석 중 오류가 발생했습니다: {str(e)}"}), 500