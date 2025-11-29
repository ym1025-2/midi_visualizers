import pygame
import mido
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
import os
import sys

# --- 設定 ---
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 30  # 動画のフレームレート
PIXEL_SCALE = 2  # ドット絵の拡大率（1ドットの大きさ）
KEY_WIDTH = 12   # 白鍵の幅（ドット数）
KEY_HEIGHT = 40  # 白鍵の高さ（ドット数）

# 色定義 (R, G, B)
COLOR_BG = (20, 20, 20)
COLOR_WHITE_KEY_OFF = (200, 200, 200)
COLOR_WHITE_KEY_ON = (100, 100, 100) # 押したときの色
COLOR_BLACK_KEY_OFF = (100, 100, 100)
COLOR_BLACK_KEY_ON = (50, 50, 50)   # 押したときの色

class MidiVisualizer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw() # メインウィンドウを隠す

    def select_file(self):
        """MIDIファイル選択ダイアログ"""
        file_path = filedialog.askopenfilename(
            title="MIDIファイルを選択してください",
            filetypes=[("MIDI files", "*.mid"), ("All files", "*.*")]
        )
        return file_path

    def select_output_dir(self):
        """保存先フォルダ選択ダイアログ"""
        dir_path = filedialog.askdirectory(title="動画の保存先を選択してください")
        return dir_path

    def parse_midi(self, midi_path):
        """MIDIファイルを解析して固定テンポで時間ごとのイベントリストを作成"""
        mid = mido.MidiFile(midi_path)
        
        # ----------------------------------------------------
        # ▼ 修正箇所 1: 固定BPMを設定し、テンポに変換する ▼
        # ----------------------------------------------------
        # 例として 120 BPM に固定する場合
        FIXED_BPM = 174 
        
        # FIXED_BPMを mido が扱うテンポ値（マイクロ秒/拍）に変換
        tempo = mido.bpm2tempo(FIXED_BPM) 
        # ----------------------------------------------------
        
        ticks_per_beat = mid.ticks_per_beat
        
        merged_msgs = mido.merge_tracks(mid.tracks)
        
        current_time_sec = 0.0
        events = []
        
        for msg in merged_msgs:
            # 時間を経過させる
            if msg.time > 0:
                # ティック数を**固定のテンポ**に基づいて秒に変換
                seconds = mido.tick2second(msg.time, ticks_per_beat, tempo)
                current_time_sec += seconds
            
            # ----------------------------------------------------
            # ▼ 修正箇所 2: MIDIファイル内のテンポ変更メッセージを無視する ▼
            # ----------------------------------------------------
            # MIDIファイル内に 'set_tempo' があっても、上記で設定した固定値 'tempo' は更新しません。
            # ----------------------------------------------------

            if msg.type in ['note_on', 'note_off']:
                # ... (後略：ノートイベントの処理は変更なし)
                velocity = getattr(msg, 'velocity', 0)
                is_note_on = (msg.type == 'note_on' and velocity > 0)
                is_note_off = (msg.type == 'note_off' or (msg.type == 'note_on' and velocity == 0))
                
                if is_note_on or is_note_off:
                    events.append({
                        'time': current_time_sec,
                        'note': msg.note,
                        'is_on': is_note_on
                    })
                
        return events, current_time_sec

    def draw_keyboard(self, surface, active_notes):
        """ドット絵風キーボードを描画"""
        surface.fill(COLOR_BG)
        
        # 描画開始位置（中央寄せ）
        total_keys_width = 52 * KEY_WIDTH * PIXEL_SCALE # 白鍵は約52個
        start_x = (SCREEN_WIDTH - total_keys_width) // 2
        start_y = (SCREEN_HEIGHT - (KEY_HEIGHT * PIXEL_SCALE)) // 2

        # ピアノの鍵盤データ (MIDIノート番号 21(A0) ～ 108(C8))
        white_keys = []
        black_keys = []
        
        wk_index = 0
        for note in range(21, 109):
            # 1オクターブ内の位置 (0-11)
            octave_pos = note % 12
            is_black = octave_pos in [1, 3, 6, 8, 10]
            
            if not is_black:
                x = start_x + (wk_index * KEY_WIDTH * PIXEL_SCALE)
                y = start_y
                w = KEY_WIDTH * PIXEL_SCALE
                h = KEY_HEIGHT * PIXEL_SCALE
                white_keys.append({'rect': (x, y, w, h), 'note': note})
                wk_index += 1
            else:
                # ----------------------------------------------------
                # ▼ 修正箇所: 黒鍵の中心を白鍵の境目に合わせる ▼
                # ----------------------------------------------------
                
                # 黒鍵の幅を定義 (例: 白鍵幅の約60%)
                w = int(KEY_WIDTH * PIXEL_SCALE * 0.6)
                
                # 境界線の位置 (wk_index は既に次の白鍵を指している)
                boundary_x = start_x + (wk_index * KEY_WIDTH * PIXEL_SCALE)
                
                # 黒鍵の開始位置 (境界線 - 黒鍵の幅の半分)
                x = boundary_x - (w // 2) 
                
                # ----------------------------------------------------
                
                y = start_y
                h = int(KEY_HEIGHT * PIXEL_SCALE * 0.6)
                black_keys.append({'rect': (x, y, w, h), 'note': note})

        # 白鍵を描画
        for k in white_keys:
            color = COLOR_WHITE_KEY_ON if k['note'] in active_notes else COLOR_WHITE_KEY_OFF
            pygame.draw.rect(surface, color, k['rect'])
            # ドット絵っぽく枠線を描く
            pygame.draw.rect(surface, (0,0,0), k['rect'], 2)

        # 黒鍵を描画（白鍵の上に重ねる）
        for k in black_keys:
            color = COLOR_BLACK_KEY_ON if k['note'] in active_notes else COLOR_BLACK_KEY_OFF
            pygame.draw.rect(surface, color, k['rect'])
            pygame.draw.rect(surface, (0,0,0), k['rect'], 2)

    def run(self):
        # 1. MIDIファイル選択
        midi_path = self.select_file()
        if not midi_path:
            print("ファイルが選択されませんでした。")
            return

        # 2. 保存先選択
        output_dir = self.select_output_dir()
        if not output_dir:
            print("保存先が選択されませんでした。")
            return
            
        output_filename = os.path.join(output_dir, "output_video.mp4")
        print(f"解析中: {midi_path} ...")

        # 3. MIDI解析
        events, total_duration = self.parse_midi(midi_path)
        print(f"曲の長さ: {total_duration:.2f}秒")

        # 4. Pygame初期化
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("MIDI Pixel Visualizer")
        clock = pygame.time.Clock()

        # 5. 動画書き出し準備 (OpenCV)
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_filename, fourcc, FPS, (SCREEN_WIDTH, SCREEN_HEIGHT))

        # 再生用変数
        current_time = 0.0
        event_idx = 0
        active_notes = set()
        running = True
        
        font = pygame.font.SysFont(None, 30)

        print("レンダリング開始... (画面を閉じると中断します)")

        while running and current_time <= total_duration + 2.0: # 余韻用に+2秒
            # イベント処理（ウィンドウを閉じるなど）
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False

            # 時間経過
            dt = 1 / FPS
            current_time += dt

            # MIDIイベントの更新
            while event_idx < len(events) and events[event_idx]['time'] <= current_time:
                ev = events[event_idx]
                if ev['is_on']:
                    active_notes.add(ev['note'])
                else:
                    if ev['note'] in active_notes:
                        active_notes.remove(ev['note'])
                event_idx += 1

            # 描画
            self.draw_keyboard(screen, active_notes)
            
            # 進捗表示
            progress_text = f"Time: {current_time:.1f}/{total_duration:.1f}s"
            text_surf = font.render(progress_text, True, (255, 255, 255))
            screen.blit(text_surf, (10, 10))

            pygame.display.flip()

            # 画面キャプチャ -> 動画保存
            # Pygame(RGB) -> OpenCV(BGR)へ変換
            frame_data = pygame.surfarray.array3d(screen)
            frame_data = np.transpose(frame_data, (1, 0, 2))
            frame_data = cv2.cvtColor(frame_data, cv2.COLOR_RGB2BGR)
            
            out.write(frame_data)
            
            # 表示用クロック（レンダリング速度を実際の速度に合わせる場合はコメントアウトを外す）
            # clock.tick(FPS) 
            # ※ 動画書き出しを最速で行うため、あえてclock.tickしていません。
            #    プレビューをリアルタイムで見たい場合は上を有効にしてください。

        # 終了処理
        out.release()
        pygame.quit()
        print(f"完了しました！動画は以下に保存されました:\n{output_filename}")

if __name__ == "__main__":
    app = MidiVisualizer()
    app.run()