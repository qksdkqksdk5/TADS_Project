import os
import glob
import threading

def cleanup_real_cctv_models():
    """시뮬레이션(sim_)을 제외한 실제 CCTV 학습 데이터(.npy) 삭제"""
    model_dir = "learned_models"
    if not os.path.exists(model_dir):
        return

    # flow_*.npy 패턴의 모든 파일 찾기
    model_files = glob.glob(os.path.join(model_dir, "flow_*.npy"))
    
    for f in model_files:
        filename = os.path.basename(f)
        # 파일명에 'sim_'이 포함되지 않은 경우만 삭제
        if "flow_sim_" not in filename:
            try:
                os.remove(f)
                print(f"🗑️ [Cleanup] 실제 CCTV 모델 초기화 완료: {filename}")
            except Exception as e:
                print(f"❌ [Cleanup] {filename} 삭제 실패: {e}")

# ✅ 서버 시작 시 즉시 실행
cleanup_real_cctv_models()

class DetectionManager:
    def __init__(self):
        self.active_detectors = {}
        self.threads = {}
        self._lock = threading.Lock()

    def get_or_create(self, name, detector_class, **kwargs):
        """분석기 생성 및 관리"""
        with self._lock:
            if name in self.active_detectors:
                if self.threads[name].is_alive():
                    return self.active_detectors[name]
                else:
                    print(f"⚠️ [Manager] {name} 재시작 시도")
                    del self.active_detectors[name]
                    del self.threads[name]

            print(f"🚀 [Manager] {name} 분석기 생성")
            instance = detector_class(name, **kwargs)
            
            # 1. daemon=False로 변경하여 종료 시점 제어
            # 2. name을 명확히 주어 로그 추적 용이하게 설정
            t = threading.Thread(target=instance.run, name=f"Thread_{name}", daemon=False)
            t.start()
            
            self.active_detectors[name] = instance
            self.threads[name] = t
            return instance

    def stop(self, name):
        """특정 detector 정지 및 제거"""
        with self._lock:
            if name not in self.active_detectors:
                return
            print(f"🛑 [Manager] {name} 분석기 정지")
            self.active_detectors[name].stop()
            self.threads[name].join(timeout=2.0)
            del self.active_detectors[name]
            del self.threads[name]

    def stop_all(self):
        """종료 시 안전하게 모든 스레드 회수"""
        with self._lock:
            print(f"🛑 [Manager] 모든 분석기 정지 중...")
            for name, instance in self.active_detectors.items():
                instance.stop()  # stop_flag를 True로 변경
            
            # 스레드가 완전히 끝날 때까지 대기 (선택 사항)
            for name, t in self.threads.items():
                t.join(timeout=2.0)
                
            self.active_detectors.clear()
            self.threads.clear()

# 전역 인스턴스
detector_manager = DetectionManager()