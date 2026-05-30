# SoulCompanion_AI/utils/audio_player.py
import pyttsx3
import threading
import queue
import time


class AudioPlayer:
    def __init__(self):
        self.msg_queue = queue.Queue()
        self.is_running = True
        # 核心：只启动唯一一个守护线程处理语音，避免多线程冲突
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def speak(self, text):
        """将文字放入队列，立即返回，不阻塞主程序"""
        if text:
            self.msg_queue.put(text)

    def _worker(self):
        """语音工作线程，顺序处理队列中的每一句话"""
        # 在线程内初始化，保证 engine 属于该线程
        engine = pyttsx3.init()
        engine.setProperty('rate', 160)  # 稍微加快语速，更自然

        while self.is_running:
            try:
                # 阻塞式等待，直到队列有新消息（每秒检查一次运行状态）
                text = self.msg_queue.get(timeout=1)

                # 只有当 engine 没有在忙时才说话
                print(f"🔊 [正在播放]: {text}")
                engine.say(text)
                engine.runAndWait()

                # 标记任务完成
                self.msg_queue.task_done()
                # 语毕短暂停顿，防止句子粘连
                time.sleep(0.3)

            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 语音引擎异常: {e}")
                # 如果引擎崩溃，尝试在此重新初始化
                time.sleep(1)
                engine = pyttsx3.init()

    def stop(self):
        self.is_running = False