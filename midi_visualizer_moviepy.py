import pygame
import mido
import cv2
import numpy as np
import tkinter as tk
from tkinter import filedialog
import os
import sys

# --- MoviePyのインポート ---
# 動画の透過読み込みにおける重要なライブラリです
try:
    from moviepy import VideoFileClip
except ImportError:
    print("【エラー】'moviepy' ライブラリが見つかりません。")
    print("以下のコマンドを実行してインストールしてください: pip install moviepy")
    sys.exit(1)

# ==========================================
# 設定エリア
# ==========================================

# 出力動画の設定
SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720
FPS = 30

# MIDI設定
FIXED_BPM = 174  # MIDIファイルにBPM情報がない場合に使用

# 鍵盤レイアウト設定
GRID_KEY_WIDTH = 24      # 白鍵1つあたりの配置間隔(px)
KEY_START_Y_OFFSET = -320   # 画面中央からのY座標のズレ

# アセット(画像/動画)の表示設定
ASSET_SCALE = 1.0         # 拡大率 (0.5なら半分、2.0なら倍)
WHITE_KEY_OFFSET = (0, 0) # 白鍵の表示位置微調整 (x, y)
BLACK_KEY_OFFSET = (0, 0) # 黒鍵の表示位置微調整 (x, y)

# 背景色 (R, G, B)
COLOR_BG = (20, 20, 20)

# ==========================================
# アセット読み込みクラス
# ==========================================

class AssetLoader:
    """
    画像と動画を適切なライブラリで読み込み、
    Pygameで描画可能な [Surface, Surface, ...] のリストに変換して返すクラス。
    """

    @staticmethod
    def load_static_image(path, scale, duration_sec=1.0):
        """
        【画像用】Pygame標準機能で読み込み（透過確実）
        """
        print(f"[Image Loader] 読み込み中: {os.path.basename(path)}")
        frames = []
        try:
            # convert_alpha() は必須です
            img_surf = pygame.image.load(path).convert_alpha()
            
            # リサイズ
            w, h = img_surf.get_size()
            new_w, new_h = int(w * scale), int(h * scale)
            img_surf = pygame.transform.smoothscale(img_surf, (new_w, new_h))
            
            # 指定秒数分だけ同じ画像を複製してリストにする
            # これにより動画と同じように「コマ送り」で扱える
            frame_count = int(FPS * duration_sec)
            frames = [img_surf] * frame_count
            
        except Exception as e:
            print(f"  -> 画像読み込みエラー: {e}")
            
        return frames

    @staticmethod
    def load_video_with_moviepy(path, scale):
        """
        【動画用】MoviePyを使用して透過AVIを確実に読み込む
        """
        print(f"[Video Loader (MoviePy)] 読み込み中: {os.path.basename(path)}")
        frames = []
        
        try:
            # has_mask=True でアルファチャンネルを意識させる
            clip = VideoFileClip(path, has_mask=True)
            
            # 【重要】
            # clip.iter_frames() は RGB (3ch) しか返さないことが多いため、
            # clip.mask (アルファチャンネル) がある場合は手動で結合する処理を行う
            
            if clip.mask:
                print("  -> アルファチャンネル(マスク)を検出しました。RGBA合成モードで読み込みます。")
                # RGBフレームとマスクフレームを同時に回す
                # clip.mask.iter_frames() は 0.0〜1.0 のfloatを返すことが多いので uint8 (0-255) に変換が必要
                for frame_rgb, frame_alpha in zip(clip.iter_frames(fps=FPS, dtype="uint8"), clip.mask.iter_frames(fps=FPS, dtype="float")):
                    
                    # マスク(float 0-1) を 0-255 に変換して次元を合わせる
                    # frame_alpha は (H, W) なので (H, W, 1) に拡張
                    alpha_uint8 = (frame_alpha * 255).astype("uint8")
                    if len(alpha_uint8.shape) == 2:
                        alpha_uint8 = np.expand_dims(alpha_uint8, axis=2)
                    
                    # RGB と Alpha を結合して RGBA (H, W, 4) を作成
                    frame_rgba = np.dstack((frame_rgb, alpha_uint8))
                    
                    # ここからは共通処理 (リサイズとPygame変換)
                    h, w = frame_rgba.shape[:2]
                    new_w, new_h = int(w * scale), int(h * scale)
                    if new_w <= 0 or new_h <= 0: continue
                    
                    resized_frame = cv2.resize(frame_rgba, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    
                    # RGBA -> Pygame Surface
                    surf = pygame.image.frombuffer(resized_frame.tobytes(), (new_w, new_h), "RGBA")
                    frames.append(surf)
                    
            else:
                print("  -> アルファチャンネルが検出されませんでした(RGBモード)。")
                # マスクがない場合は従来の処理 (RGBのみ)
                for frame in clip.iter_frames(fps=FPS, dtype="uint8"):
                    h, w = frame.shape[:2]
                    new_w, new_h = int(w * scale), int(h * scale)
                    if new_w <= 0 or new_h <= 0: continue
                    
                    resized_frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
                    
                    # RGB -> Pygame Surface
                    surf = pygame.image.frombuffer(resized_frame.tobytes(), (new_w, new_h), "RGB")
                    frames.append(surf)
            
            clip.close()
            print(f"  -> 完了。{len(frames)} フレームを読み込みました。")
            
        except Exception as e:
            print(f"  -> 動画読み込みエラー (MoviePy): {e}")
            import traceback
            traceback.print_exc()

        return frames

# ==========================================
# メインアプリケーションクラス
# ==========================================

class MidiVisualizer:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()

    def select_file(self, title, filetypes):
        f = filedialog.askopenfilename(title=title, filetypes=filetypes)
        return f

    def select_dir(self, title):
        d = filedialog.askdirectory(title=title)
        return d

    def parse_midi(self, midi_path):
        """MIDI解析 (NoteOnのみ抽出)"""
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
            
            if msg.type == 'note_on' and msg.velocity > 0:
                events.append({
                    'time': current_time_sec,
                    'note': msg.note
                })
        
        return events, current_time_sec

    def calculate_positions(self):
        """鍵盤座標計算: 黒鍵は白鍵境界の中心に"""
        positions = {}
        
        # 画面中央寄せのための計算
        total_width = 52 * GRID_KEY_WIDTH
        start_x = (SCREEN_WIDTH - total_width) // 2
        start_y = (SCREEN_HEIGHT // 2) + KEY_START_Y_OFFSET

        white_key_index = 0
        
        for note in range(21, 109): # A0 to C8
            # 1オクターブ内の位置 (0=C ... 11=B)
            note_in_octave = note % 12
            is_black = note_in_octave in [1, 3, 6, 8, 10]
            
            if not is_black:
                # 白鍵の位置
                x = start_x + (white_key_index * GRID_KEY_WIDTH)
                y = start_y
                positions[note] = {'x': x, 'y': y, 'is_black': False}
                white_key_index += 1
            else:
                # 黒鍵の位置 (前の白鍵と次の白鍵の境界線上)
                # white_key_index は「次の白鍵」のインデックスを指している
                boundary_x = start_x + (white_key_index * GRID_KEY_WIDTH)
                
                x = boundary_x
                y = start_y
                positions[note] = {'x': x, 'y': y, 'is_black': True}
                
        return positions

    def load_asset_wrapper(self, path):
        """拡張子で判断してローダーを振り分け"""
        if not path: return []
        ext = os.path.splitext(path)[1].lower()
        
        if ext in ['.png', '.jpg', '.jpeg']:
            return AssetLoader.load_static_image(path, ASSET_SCALE)
        elif ext in ['.avi', '.mp4', '.mov']:
            return AssetLoader.load_video_with_moviepy(path, ASSET_SCALE)
        else:
            print(f"非対応のファイル形式です: {path}")
            return []

    def run(self):
        # 1. ファイル選択 GUI
        midi_path = self.select_file("1. MIDIファイル (.mid)", [("MIDI", "*.mid")])
        if not midi_path: return

        white_asset = self.select_file("2. 白鍵用素材 (.png, .avi)", [("Image/Video", "*.png *.jpg *.avi *.mp4")])
        if not white_asset: return

        black_asset = self.select_file("3. 黒鍵用素材 (.png, .avi)", [("Image/Video", "*.png *.jpg *.avi *.mp4")])
        if not black_asset: return

        output_dir = self.select_dir("4. 保存先フォルダ")
        if not output_dir: return
        output_path = os.path.join(output_dir, "output_visualizer.mp4")

        # 2. Pygame初期化
        pygame.init()
        screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))
        pygame.display.set_caption("Generating Video...")

        # 3. アセット読み込み (ここでMoviePyが活躍)
        print("\n--- アセット読み込み開始 ---")
        frames_white = self.load_asset_wrapper(white_asset)
        frames_black = self.load_asset_wrapper(black_asset)
        
        if not frames_white or not frames_black:
            print("エラー: アセットの読み込みに失敗しました。処理を中断します。")
            return

        # 4. MIDI解析
        print("\n--- MIDI解析開始 ---")
        events, total_duration = self.parse_midi(midi_path)
        print(f"曲の長さ: {total_duration:.2f}秒")

        # 5. 動画書き出し設定
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, FPS, (SCREEN_WIDTH, SCREEN_HEIGHT))

        # 6. 実行ループ準備
        key_states = {note: {'frame_index': 0, 'active': False} for note in range(21, 109)}
        key_positions = self.calculate_positions()

        current_time = 0.0
        event_cursor = 0
        running = True
        font = pygame.font.SysFont(None, 34)
        
        print("\n--- レンダリング開始 ---")
        
        # メインループ
        while running and current_time <= total_duration + 3.0:
            for e in pygame.event.get():
                if e.type == pygame.QUIT: running = False

            dt = 1 / FPS
            current_time += dt

            # MIDIイベント発火
            while event_cursor < len(events) and events[event_cursor]['time'] <= current_time:
                note = events[event_cursor]['note']
                if note in key_states:
                    key_states[note]['frame_index'] = 0
                    key_states[note]['active'] = True
                event_cursor += 1

            # --- 描画 ---
            screen.fill(COLOR_BG)

            # 白鍵レイヤー (奥)
            self.draw_layer(screen, key_states, key_positions, frames_white, draw_black=False)
            
            # 黒鍵レイヤー (手前)
            self.draw_layer(screen, key_states, key_positions, frames_black, draw_black=True)

            # 情報テキスト
            text = f"Time: {current_time:.1f} / {total_duration:.1f}s  (BPM: {FIXED_BPM})"
            screen.blit(font.render(text, True, (255, 255, 255)), (20, 20))

            pygame.display.flip()

            # --- 録画 (Pygame -> OpenCV) ---
            # 1. Pygameの画面データを取得 (幅, 高さ, RGB)
            frame_data = pygame.surfarray.array3d(screen)
            # 2. 転置して (高さ, 幅, RGB) にする
            frame_data = frame_data.transpose([1, 0, 2])
            # 3. RGB を BGR に変換 (OpenCV用)
            frame_data = cv2.cvtColor(frame_data, cv2.COLOR_RGB2BGR)
            
            out.write(frame_data)

        out.release()
        pygame.quit()
        print(f"\n完了しました！保存先: {output_path}")

    def draw_layer(self, screen, key_states, positions, frames, draw_black):
        """指定レイヤー(白/黒)のキーを描画"""
        total_frames = len(frames)
        off_x, off_y = BLACK_KEY_OFFSET if draw_black else WHITE_KEY_OFFSET
        
        for note, pos in positions.items():
            if pos['is_black'] != draw_black:
                continue
            
            state = key_states[note]
            if state['active']:
                idx = int(state['frame_index'])
                
                if idx < total_frames:
                    surf = frames[idx]
                    w, h = surf.get_size()
                    
                    # 座標計算 (画像の中心を基準点に合わせる)
                    draw_x = pos['x'] - (w // 2) + off_x
                    draw_y = pos['y'] + off_y
                    
                    screen.blit(surf, (draw_x, draw_y))
                    
                    # コマを進める
                    state['frame_index'] += 1
                else:
                    # 最後まで再生したら消える
                    state['active'] = False

if __name__ == "__main__":
    app = MidiVisualizer()
    app.run()