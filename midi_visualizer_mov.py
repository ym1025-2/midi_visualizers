import pygame
import mido
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
import os
import sys

# ==========================================
# 設定エリア (ここで挙動を調整してください)
# ==========================================

# 出力動画の設定
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 30

# MIDI設定
FIXED_BPM = 174  # MIDIファイルにBPMがない場合の固定値

# 鍵盤レイアウト設定
GRID_KEY_WIDTH = 24      # 白鍵1つあたりの配置間隔(px)
KEY_START_Y_OFFSET = 0   # 画面中央からのY座標のズレ

# アセット(画像/動画)の表示設定
ASSET_SCALE = 1.0        # 拡大率 (1.0 = 原寸大)
WHITE_KEY_OFFSET = (0, 0) # 白鍵の表示位置微調整 (x, y)
BLACK_KEY_OFFSET = (0, -20) # 黒鍵の表示位置微調整 (x, y)

# 背景色 (R, G, B)
COLOR_BG = (20, 20, 30)

# ==========================================
# ロジッククラス定義
# ==========================================

class AssetLoader:
    """
    画像と動画で完全に処理を分けたアセットローダー
    最終的に [pygame.Surface, pygame.Surface, ...] のリストを返すことで統一する
    """

    @staticmethod
    def load_static_image(path, scale, duration_sec=1.0):
        """
        【画像読み込み専用】
        Pygameの機能だけで読み込むため、透過情報は確実に保持される。
        動画と同じように扱うため、指定秒数分だけ同じ画像を複製したリストを作成する。
        """
        print(f"[Image Loader] Reading: {os.path.basename(path)}")
        frames = []
        try:
            # 1. Pygameで読み込み (convert_alphaで透過保持)
            img_surf = pygame.image.load(path).convert_alpha()
            
            # 2. リサイズ
            w, h = img_surf.get_size()
            new_w, new_h = int(w * scale), int(h * scale)
            img_surf = pygame.transform.smoothscale(img_surf, (new_w, new_h))
            
            # 3. フレーム複製 (FPS * 秒数 分だけコピーを作成)
            # これにより「1回叩くと1秒間表示される」ような挙動になる
            frame_count = int(FPS * duration_sec)
            frames = [img_surf] * frame_count
            
            print(f"  -> Success. Created {frame_count} frames from static image.")
            
        except Exception as e:
            print(f"  -> Error loading image: {e}")
            
        return frames

    @staticmethod
    def load_video_avi(path, scale):
        """
        【動画読み込み専用】
        OpenCVを使用してAVIを読み込む。
        RGBA(4ch)かRGB(3ch)かを判定し、適切にPygame形式に変換する。
        """
        print(f"[Video Loader] Reading: {os.path.basename(path)}")
        frames = []
        
        cap = cv2.VideoCapture(path)
        
        if not cap.isOpened():
            print("  -> Error: Could not open video file.")
            return []

        frame_idx = 0
        while True:
            # 1. フレーム読み込み
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            
            # 2. 形状チェック (高さ, 幅, チャンネル)
            # OpenCVは通常 (H, W, C) のnumpy配列を返す
            h, w = frame.shape[:2]
            channels = frame.shape[2] if len(frame.shape) > 2 else 1
            
            # 3. リサイズ (補間方法はドット絵ならNEAREST, 滑らかにならLINEAR/AREA)
            new_w, new_h = int(w * scale), int(h * scale)
            if new_w <= 0 or new_h <= 0: continue
            
            resized_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
            
            # 4. 色空間の変換 (OpenCVはBGR配列 -> PygameはRGB/RGBA)
            surf = None
            
            if channels == 4:
                # BGRA -> RGBA (透過あり)
                # 注: AVIコーデックによってはAlphaが読めず3chになることがあります
                resized_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGRA2RGBA)
                surf = pygame.image.frombuffer(resized_frame.tobytes(), (new_w, new_h), "RGBA")
                
            elif channels == 3:
                # BGR -> RGB (透過なし)
                # ユーザーへの警告は最初のフレームのみ行う
                if frame_idx == 0:
                    print("  -> Warning: Loaded as 3-channel video (No Transparency detected).")
                resized_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)
                surf = pygame.surfarray.make_surface(resized_frame.swapaxes(0, 1))
                
            else:
                print(f"  -> Warning: Unsupported channel count {channels}. Skipping frame.")
                continue
                
            if surf:
                frames.append(surf)
            
            frame_idx += 1

        cap.release()
        print(f"  -> Success. Loaded {len(frames)} frames.")
        return frames

class MidiVisualizer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def select_file(self, title, filetypes):
        return filedialog.askopenfilename(title=title, filetypes=filetypes)

    def select_dir(self, title):
        return filedialog.askdirectory(title=title)

    def parse_midi(self, midi_path):
        """MIDIファイルを固定BPMで解析し、NoteOnイベントのリストを作成"""
        mid = mido.MidiFile(midi_path)
        tempo = mido.bpm2tempo(FIXED_BPM)
        ticks_per_beat = mid.ticks_per_beat
        merged_msgs = mido.merge_tracks(mid.tracks)
        
        current_time_sec = 0.0
        events = []
        
        for msg in merged_msgs:
            if msg.time > 0:
                seconds = mido.tick2second(msg.time, ticks_per_beat, tempo)
                current_time_sec += seconds
            
            # Note On (Velocity > 0) のみを抽出
            if msg.type == 'note_on' and msg.velocity > 0:
                events.append({
                    'time': current_time_sec,
                    'note': msg.note
                })
        
        # 総時間を取得
        total_duration = current_time_sec
        return events, total_duration

    def calculate_positions(self):
        """鍵盤の描画座標を計算 (黒鍵は白鍵の境界中心)"""
        positions = {}
        
        # 88鍵 (A0=21 to C8=108)
        # 中央寄せ計算
        total_width = 52 * GRID_KEY_WIDTH # 白鍵は約52個
        start_x = (SCREEN_WIDTH - total_width) // 2
        start_y = (SCREEN_HEIGHT // 2) + KEY_START_Y_OFFSET

        white_key_index = 0
        
        for note in range(21, 109):
            # 1オクターブ内の位置 (0=C, 1=C#, ...)
            # A0(21) % 12 = 9 (A) なので注意。ここでは単純に黒鍵判定を行う
            
            # MIDIノート番号における黒鍵判定
            # C=0, C#=1, D=2, D#=3, E=4, F=5, F#=6, G=7, G#=8, A=9, A#=10, B=11
            note_in_octave = note % 12
            is_black = note_in_octave in [1, 3, 6, 8, 10]
            
            if not is_black:
                # 白鍵
                x = start_x + (white_key_index * GRID_KEY_WIDTH)
                y = start_y
                positions[note] = {'x': x, 'y': y, 'is_black': False}
                white_key_index += 1
            else:
                # 黒鍵
                # 現在の white_key_index は「次の白鍵」を指している
                # したがって、白鍵の境界線Xは start_x + (white_key_index * GRID_KEY_WIDTH)
                boundary_x = start_x + (white_key_index * GRID_KEY_WIDTH)
                
                x = boundary_x
                y = start_y - 20 # 少し上に配置
                positions[note] = {'x': x, 'y': y, 'is_black': True}
                
        return positions

    def load_asset_wrapper(self, path):
        """パスの拡張子を見て、画像用ローダーか動画用ローダーかを振り分ける"""
        if not path: return []
        
        ext = os.path.splitext(path)[1].lower()
        if ext in ['.png', '.jpg', '.jpeg']:
            # 画像の場合 (30フレーム=1秒分 生成)
            return AssetLoader.load_static_image(path, ASSET_SCALE, duration_sec=1.0)
        elif ext in ['.avi', '.mp4', '.mov']:
            # 動画の場合
            return AssetLoader.load_video_avi(path, ASSET_SCALE)
        else:
            print(f"Unknown file type: {path}")
            return []

    def run(self):
        # 1. GUIによるファイル選択
        midi_path = self.select_file("1. MIDIファイルを選択", [("MIDI", "*.mid")])
        if not midi_path: return

        white_asset_path = self.select_file("2. 白鍵用の素材(png/avi)", [("Image/Video", "*.png *.jpg *.avi")])
        if not white_asset_path: return

        black_asset_path = self.select_file("3. 黒鍵用の素材(png/avi)", [("Image/Video", "*.png *.jpg *.avi")])
        if not black_asset_path: return

        output_dir = self.select_dir("4. 動画保存先フォルダ")
        if not output_dir: return
        output_path = os.path.join(output_dir, "output_visualizer.mp4")

        # 2. Pygame初期化 (Surface生成に必要)
        pygame.init()
        # 画面は表示せず、オフスクリーンで処理も可能だが、進捗確認のためウィンドウを出す
        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Generating Video...")

        # 3. アセット読み込み
        print("--- Loading Assets ---")
        frames_white = self.load_asset_wrapper(white_asset_path)
        frames_black = self.load_asset_wrapper(black_asset_path)
        
        if not frames_white or not frames_black:
            print("Error: Failed to load assets.")
            return

        # 4. MIDI解析
        print("--- Parsing MIDI ---")
        events, total_duration = self.parse_midi(midi_path)
        print(f"Total Duration: {total_duration:.2f} sec")

        # 5. 動画書き出し準備
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, FPS, (SCREEN_WIDTH, SCREEN_HEIGHT))

        # 6. 再生状態管理用
        # 各キーの状態: {'frame_index': 現在のコマ数, 'active': 再生中か}
        key_states = {note: {'frame_index': 0, 'active': False} for note in range(21, 109)}
        key_positions = self.calculate_positions()

        current_time = 0.0
        event_cursor = 0
        font = pygame.font.SysFont(None, 36)
        
        running = True
        print("--- Start Rendering ---")

        # ループ (曲の長さ + 余韻3秒)
        while running and current_time <= total_duration + 3.0:
            # ウィンドウを閉じるイベントのみ処理(中断用)
            for e in pygame.event.get():
                if e.type == pygame.QUIT: running = False

            # 時間を進める
            dt = 1 / FPS
            current_time += dt

            # MIDIイベント処理
            while event_cursor < len(events) and events[event_cursor]['time'] <= current_time:
                note_num = events[event_cursor]['note']
                if 21 <= note_num <= 108:
                    # NoteOnが来たらフレームを0にリセットして再生開始
                    key_states[note_num]['frame_index'] = 0
                    key_states[note_num]['active'] = True
                event_cursor += 1

            # 描画
            screen.fill(COLOR_BG)
            
            # 白鍵の描画ループ
            self.draw_layer(screen, key_states, key_positions, frames_white, draw_black=False)
            # 黒鍵の描画ループ (上に重ねる)
            self.draw_layer(screen, key_states, key_positions, frames_black, draw_black=True)

            # 情報表示
            info_text = f"Time: {current_time:.1f}/{total_duration:.1f}s | BPM: {FIXED_BPM}"
            screen.blit(font.render(info_text, True, (255, 255, 255)), (20, 20))

            pygame.display.flip()

            # 動画フレーム保存
            # Pygame(RGB) -> Numpy -> OpenCV(BGR)
            # surfarray.array3d は (W, H, 3) を返すため、転置して (H, W, 3) にする
            frame_data = pygame.surfarray.array3d(screen)
            frame_data = frame_data.transpose([1, 0, 2])
            frame_data = cv2.cvtColor(frame_data, cv2.COLOR_RGB2BGR)
            
            out.write(frame_data)

        out.release()
        pygame.quit()
        print(f"--- Completed! Saved to: {output_path} ---")

    def draw_layer(self, screen, key_states, positions, frames, draw_black):
        """指定された種別(白鍵/黒鍵)のみを描画するヘルパーメソッド"""
        
        offset_x, offset_y = BLACK_KEY_OFFSET if draw_black else WHITE_KEY_OFFSET
        total_frames = len(frames)
        
        for note, pos in positions.items():
            # 描画対象の鍵盤タイプでなければスキップ
            if pos['is_black'] != draw_black:
                continue
            
            state = key_states[note]
            if state['active']:
                idx = int(state['frame_index'])
                
                if idx < total_frames:
                    surf = frames[idx]
                    w, h = surf.get_size()
                    
                    # 座標計算:
                    # pos['x'] は白鍵の境界線（中心位置）
                    # 画像の中心を pos['x'] に合わせる
                    draw_x = pos['x'] - (w // 2) + offset_x
                    draw_y = pos['y'] + offset_y
                    
                    screen.blit(surf, (draw_x, draw_y))
                    
                    # 次のフレームへ
                    state['frame_index'] += 1
                else:
                    # 最後まで再生したら停止 (ワンショット再生)
                    state['active'] = False

if __name__ == "__main__":
    app = MidiVisualizer()
    app.run()