import cv2
import numpy as np
import threading
import time
import os


class VisionEngine:
    def __init__(self, model_path="models/onnx_model.onnx"):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        xml_path = os.path.join(base_dir, "models", "haarcascade_frontalface_default.xml")
        onnx_full_path = os.path.join(base_dir, model_path)

        self.face_cascade = cv2.CascadeClassifier(xml_path)
        self.last_frame = None  # 核心：用于存储最新的一帧画面

        if self.face_cascade.empty():
            print(f"❌ [严重错误] 找不到 XML！")
        else:
            print(f"✅ [视觉引擎] 人脸检测器已就绪")

        self.model_loaded = False
        try:
            if os.path.exists(onnx_full_path):
                self.net = cv2.dnn.readNetFromONNX(onnx_full_path)
                self.model_loaded = True
                print(f"✅ [视觉引擎] 情绪识别模型已就绪")
        except Exception as e:
            print(f"❌ [错误] 模型初始化失败: {e}")

        self.emotion_labels = ['angry', 'disgust', 'fear', 'happy', 'sad', 'surprise', 'neutral']
        self.cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        self.current_state = {"face_detected": False, "emotion": "neutral", "attention_loss_time": 0.0}
        self.last_face_time = time.time()
        self.is_running = True

        self.thread = threading.Thread(target=self._process_video, daemon=True)
        self.thread.start()

    def _process_video(self):
        frame_count = 0
        while self.is_running:
            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            # --- 关键修复：将实时画面存入 last_frame 供 UI 调用 ---
            self.last_frame = frame

            if self.face_cascade.empty():
                continue

            frame_count += 1
            small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
            gray = cv2.cvtColor(small_frame, cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(gray, 1.3, 5)

            new_state = self.current_state.copy()
            if len(faces) > 0:
                new_state["face_detected"] = True
                self.last_face_time = time.time()
                new_state["attention_loss_time"] = 0.0

                if self.model_loaded and frame_count % 3 == 0:
                    try:
                        (x, y, w, h) = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]
                        roi = gray[y:y + h, x:x + w]
                        roi = cv2.resize(roi, (48, 48))
                        blob = cv2.dnn.blobFromImage(roi, 1.0 / 255.0, (48, 48), (0, 0, 0), swapRB=False)
                        self.net.setInput(blob)
                        preds = self.net.forward()
                        idx = np.argmax(preds[0])
                        raw_emotion = self.emotion_labels[idx]

                        mapping = {
                            "happy": "happy", "surprise": "happy", "sad": "sad",
                            "angry": "anxious", "fear": "anxious", "disgust": "anxious",
                            "neutral": "neutral"
                        }
                        new_state["emotion"] = mapping.get(raw_emotion, "neutral")
                    except:
                        pass
            else:
                new_state["face_detected"] = False
                new_state["attention_loss_time"] = round(time.time() - self.last_face_time, 1)

            self.current_state = new_state
            time.sleep(0.01)

    # --- 核心修复：添加 WebUI 需要的接口 ---
    def get_current_frame(self):
        """安全地返回当前帧"""
        return self.last_frame

    def get_latest_state(self):
        return self.current_state

    def stop(self):
        self.is_running = False
        if self.cap.isOpened():
            self.cap.release()