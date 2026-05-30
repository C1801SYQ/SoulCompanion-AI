# modules/speech_engine.py
import json
import time
import queue
import threading
import sys
import os
import numpy as np
import pyaudio
from collections import deque
from vosk import Model, KaldiRecognizer
from transformers import pipeline

# Fix Windows console encoding for emoji support
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class SpeechEngine:
    def __init__(self, vosk_path="model", ser_model_path="models/ser_model"):
        self.is_running = True
        self.current_state = {"text": "", "emotion": "neutral"}
        self._lock = threading.Lock()

        # 1. 初始化 VOSK (内容识别)
        print(f"🎙️ [听觉引擎] 正在加载 VOSK 模型: {vosk_path}...")
        try:
            self.vosk_model = Model(vosk_path)
            self.recognizer = KaldiRecognizer(self.vosk_model, 16000)
        except Exception as e:
            print(f"❌ [听觉引擎] VOSK 初始化失败: {e}")
            self.is_running = False
            return

        # 2. 初始化 Transformer 语音情感识别 (纯离线加载)
        print(f"🧠 [听觉引擎] 正在加载 Wav2Vec2 情感模型: {ser_model_path}...")
        try:
            # device=-1 表示使用 CPU，如果装了 CUDA 版本可以改成 device=0
            self.ser_classifier = pipeline(
                "audio-classification",
                model=ser_model_path,
                device=-1
            )
            print("✅ [听觉引擎] 深度学习情感模型加载完毕！")
        except Exception as e:
            print(f"❌ [听觉引擎] 情感模型加载失败: {e}")
            self.is_running = False
            return

        # 3. 初始化音频流和环形缓冲区
        self.audio_queue = queue.Queue()
        # 16000 采样率，保存最近 3 秒的数据 (16000 * 3 * 2 bytes = 96000 bytes)
        self.audio_buffer = deque(maxlen=16000 * 3 * 2)

        self.p = pyaudio.PyAudio()
        try:
            self.stream = self.p.open(
                format=pyaudio.paInt16,
                channels=1,
                rate=16000,
                input=True,
                frames_per_buffer=4000,
                stream_callback=self._audio_callback
            )
            self.stream.start_stream()
        except Exception as e:
            print(f"❌ [听觉引擎] 麦克风启动失败: {e}")
            self.is_running = False

        # 4. 启动后台处理线程
        if self.is_running:
            self.process_thread = threading.Thread(target=self._process_audio, daemon=True)
            self.process_thread.start()
            print("👂 [听觉引擎] 实时多模态听觉（内容+语气）已启动。")

    def _audio_callback(self, in_data, frame_count, time_info, status):
        """麦克风录音回调，将数据压入队列和环形缓冲区"""
        self.audio_queue.put(in_data)
        # 实时覆盖旧数据，始终保留最近3秒
        for byte in in_data:
            self.audio_buffer.append(byte)
        return (None, pyaudio.paContinue)

    def _process_audio(self):
        """后台解析线程"""
        while self.is_running:
            try:
                data = self.audio_queue.get(timeout=0.1)

                # VOSK 判断是否说完了一句话
                if self.recognizer.AcceptWaveform(data):
                    result = json.loads(self.recognizer.Result())
                    text = result.get('text', '')

                    if text:
                        print(f"\n🗣️ [VOSK] 识别到文字: '{text}'")
                        print("⏳ 正在调用 Transformer 分析语气...")

                        # --- 核心：提取最近3秒的声音送给深度学习模型 ---
                        audio_bytes = bytes(self.audio_buffer)
                        # 将 Int16 的字节流转为 Float32 的 Numpy 数组 (深度学习模型的标准输入)
                        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0

                        # 执行推理
                        ser_result = self.ser_classifier({"raw": audio_np, "sampling_rate": 16000})

                        # 获取得分最高的情绪标签
                        raw_emotion = ser_result[0]['label']

                        # 将英文缩写映射到你机器人的标准情绪逻辑
                        emotion_mapping = {
                            "neu": "neutral",
                            "hap": "happy",
                            "ang": "anxious",  # 愤怒映射为焦虑/激动
                            "sad": "sad"
                        }
                        final_emotion = emotion_mapping.get(raw_emotion, "neutral")

                        print(f"📊 [Wav2Vec2] 语气分析结果: {final_emotion} (置信度: {ser_result[0]['score']:.2f})")

                        # 更新状态，供主程序读取
                        with self._lock:
                            self.current_state = {
                                "text": text,
                                "emotion": final_emotion
                            }

            except queue.Empty:
                continue
            except Exception as e:
                print(f"⚠️ 音频处理异常: {e}")

    def get_latest_text(self):
        """返回识别结果，并清空当前状态以防重复读取"""
        with self._lock:
            if self.current_state["text"]:
                result = self.current_state.copy()
                self.current_state["text"] = ""  # 读取后清空
                return result
        return None

    def stop(self):
        self.is_running = False
        if hasattr(self, 'stream'):
            self.stream.stop_stream()
            self.stream.close()
        if hasattr(self, 'p'):
            self.p.terminate()