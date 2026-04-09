# 1. 최상단: gevent 패치 (SocketIO와 멀티스레딩 호환을 위해 필수)
from gevent import monkey
monkey.patch_all()

import os
import warnings
import atexit
from dotenv import load_dotenv
from flask import Flask, jsonify
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from flask_migrate import Migrate

from modules.traffic.detectors.manager import detector_manager
from models import db

load_dotenv()

warnings.filterwarnings("ignore", category=FutureWarning, message="`torch.distributed.reduce_op` is deprecated")

app = Flask(__name__)
CORS(app)

DB_USER = os.getenv("DB_USER", "root")
DB_PW   = os.getenv("DB_PASSWORD", "12341234")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME", "tads")

app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{DB_USER}:{DB_PW}@{DB_HOST}:{DB_PORT}/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "fallback-secret-key")

db.init_app(app)
migrate = Migrate(app, db)

os.makedirs(os.path.join(app.root_path, "static", "captures"), exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')
app.extensions['socketio'] = socketio

# 기존 Blueprint
from modules.traffic.its        import its_bp
from modules.traffic.streaming  import streaming_bp
from modules.traffic.simulation import simulation_bp
from modules.stats.result       import result_bp
from modules.member.member      import member_bp

app.register_blueprint(member_bp,    url_prefix='/api/member')
app.register_blueprint(result_bp)
app.register_blueprint(its_bp,       url_prefix='/api/its')
app.register_blueprint(streaming_bp)
app.register_blueprint(simulation_bp)

# ✅ 새 Blueprint
from modules.plate.plate   import plate_bp
from modules.carbon.carbon import carbon_bp
from modules.raspi.raspi   import raspi_bp

app.register_blueprint(plate_bp,  url_prefix='/api/plate')
app.register_blueprint(carbon_bp, url_prefix='/api/carbon')
app.register_blueprint(raspi_bp,  url_prefix='/api/raspi')

# ✅ DB 매니저 초기화 (백그라운드 스레드에서 DB 접근 가능하도록)
from modules.plate import db_manager
db_manager.init_app(app)

def shutdown_detectors():
    print("🛑 [System] 서버 종료 감지: 모든 분석 스레드를 정지합니다...")
    detector_manager.stop_all()

atexit.register(shutdown_detectors)

@socketio.on('resolve_emergency')
def handle_resolve(data):
    print(f"📡 조치 신호 전파: {data.get('alertId')}")
    emit('emergency_resolved', data, broadcast=True)

@app.route('/')
def index():
    return "TADS Backend Server is Running"

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)