#!/bin/bash

# 1. DB 서버가 준비될 때까지 대기 (중요!)
echo "Waiting for MySQL to start..."
while ! nc -z db 3306; do
  sleep 1
done
echo "MySQL is up - executing command"

# 2. migrations 폴더가 없으면 초기화
if [ ! -d "migrations" ]; then
    echo "Initializing migrations..."
    flask db init
fi

# 3. 마이그레이션 파일 생성 및 반영
echo "Running migrations..."
flask db migrate -m "Auto-migration" || echo "No changes in model"
flask db upgrade

# 4. Flask 앱 실행
echo "Starting Flask app..."
exec python app.py