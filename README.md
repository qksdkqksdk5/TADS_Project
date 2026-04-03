# 🚗 TADS_Project
> **Traffic Monitoring and Anomaly Detection System**
> 교통 모니터링 및 이상 징후 감지 시스템 프로젝트입니다.

---

## 💻 1. Frontend Setup (React/JS)
프론트엔드 실행을 위해 아래 명령어를 순서대로 입력하세요.

```bash
cd frontend_js
npm install
npm run dev
⚙️ 2. Simulation & Environment (.env)
데이터 및 환경 변수 설정을 위해 아래 작업을 수행하세요.

Assets 설정: N드라이브/이동훈/ 위치에서 assets 폴더를 다운로드하여 backend_flask/ 경로 내에 삽입합니다.

환경 변수 설정: env.txt 파일을 다운로드하여 프로젝트 최상단 폴더에 넣고, 파일명을 .env로 변경합니다.

🐍 3. Backend Setup (Flask)
백엔드 가상환경 설정 및 라이브러리 설치 가이드입니다.

⚠️ 주의: 작업 전 backend_flask 폴더 내에 기존 migrations 폴더가 있다면 반드시 삭제해 주세요.

Bash
cd backend_flask

# 1. Conda 가상환경 생성 및 활성화
conda create -n tads python=3.11 -y
conda activate tads

# 2. 필수 라이브러리 설치
pip install -r requirements.txt
🗄️ 4. Database Setup (MySQL)
데이터베이스 초기화 및 테이블 생성을 위한 단계입니다.

DB 생성: MySQL Workbench 또는 VSCode Database 확장 프로그램에서 아래 쿼리를 실행합니다.

SQL
CREATE DATABASE tads;
Migration 실행: 터미널(가상환경 활성화 상태)에서 아래 명령어를 입력합니다.

Bash
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
서버 실행:

Bash
python app.py
🤝 5. 협업 가이드 (Collaboration)
우리 팀의 협업 규칙(Fork, PR, 브랜치 전략)은 아래 가이드를 참고하세요.
👉 CONTRIBUTING.md 보러가기

© 2026 TADS Team. All Rights Reserved.