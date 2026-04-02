# YOLO + ByteTrack 래퍼
from pathlib import Path
from ultralytics import YOLO


class YoloTracker:
    def __init__(self, model_path_or_instance, conf, target_classes=None, use_gpu=False):
        if isinstance(model_path_or_instance, (str, Path)):
            self.model = YOLO(str(model_path_or_instance))
        else:
            self.model = model_path_or_instance

        self.conf           = conf
        self.target_classes = target_classes
        self.class_names    = getattr(self.model, "names", {})
        self.use_gpu        = use_gpu

    def track(self, frame):
        track_kwargs = {
            "tracker": "bytetrack.yaml",
            "persist": True,
            "verbose": False,
            "conf":    self.conf,
            "imgsz":   640 if self.use_gpu else 320,
        }

        # ✅ GPU 옵션은 use_gpu=True일 때만 추가
        if self.use_gpu:
            track_kwargs["device"] = 0
            track_kwargs["half"]   = True

        if self.target_classes is not None:
            track_kwargs["classes"] = self.target_classes

        results = self.model.track(frame, **track_kwargs)
        boxes   = results[0].boxes

        if boxes.id is None:
            return []

        tracks = []
        for i, tid in enumerate(boxes.id.int().tolist()):
            x1, y1, x2, y2 = boxes.xyxy[i].tolist()
            tracks.append({
                "id": tid,
                "x1": x1, "y1": y1,
                "x2": x2, "y2": y2,
                "cx": (x1 + x2) / 2,
                "cy": (y1 + y2) / 2,
            })
        return tracks