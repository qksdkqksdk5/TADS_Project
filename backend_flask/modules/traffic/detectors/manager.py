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
        """분석기 생성 및 관리 (URL 갱신 로직 추가)"""
        url = kwargs.get('url') # kwargs에서 url 추출

        with self._lock:
            if name in self.active_detectors:
                existing = self.active_detectors[name]
                
                # ✅ [핵심 추가] URL이 변경되었는지 확인 (토큰 만료 대응)
                # 기존 객체의 URL과 새로 들어온 URL이 다르면 교체해야 함
                if hasattr(existing, 'url') and existing.url != url:
                    print(f"🔄 [Manager] {name} URL 변경 감지. 기존 분석기 교체 중...")
                    self._stop_internal(name) # 기존 꺼 안전하게 중지
                
                # 아직 살아있고 URL도 같다면 그대로 반환
                elif self.threads[name].is_alive():
                    return existing
                
                else:
                    print(f"⚠️ [Manager] {name} 스레드 죽음 확인, 재시작")
                    self._stop_internal(name)

            # 새 분석기 생성
            print(f"🚀 [Manager] {name} 분석기 생성 (URL: {url[:30]}...)")
            instance = detector_class(name, **kwargs)
            
            # daemon=False로 유지하되, stop 시 join으로 회수
            t = threading.Thread(target=instance.run, name=f"Thread_{name}", daemon=False)
            t.start()
            
            self.active_detectors[name] = instance
            self.threads[name] = t
            return instance

    def _stop_internal(self, name):
        """내부용 정지 함수 (Lock 없이 호출)"""
        if name in self.active_detectors:
            self.active_detectors[name].stop()
            self.threads[name].join(timeout=1.0)
            del self.active_detectors[name]
            del self.threads[name]

    def stop(self, name):
        """특정 detector 정지 및 제거"""
        with self._lock:
            print(f"🛑 [Manager] {name} 분석기 정지 요청")
            self._stop_internal(name)

    def stop_all(self):
        """종료 시 안전하게 모든 스레드 회수"""
        with self._lock:
            print(f"🛑 [Manager] 모든 분석기 정지 중...")
            # 1. 모든 플래그 먼저 끄기
            for name, instance in self.active_detectors.items():
                instance.stop()
            
            # 2. 순차적으로 대기하며 회수
            for name, t in self.threads.items():
                t.join(timeout=1.0)
                
            self.active_detectors.clear()
            self.threads.clear()

# 전역 인스턴스
detector_manager = DetectionManager()