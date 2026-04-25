import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import inspect
from dataclasses import dataclass
from pathlib import Path
from tkinter import Tk, StringVar, filedialog, messagebox
from tkinter import ttk


try:
    import mido
except Exception:  # pragma: no cover
    mido = None


SUPPORTED_AUDIO_EXTS = {
    ".mp3",
    ".wav",
    ".flac",
    ".m4a",
    ".aac",
    ".ogg",
    ".mp4",
    ".mkv",
    ".mov",
}

STEM_TYPES = ("vocals", "drums", "bass", "other")
MIDI_ENGINES = ("basic_pitch", "piano_transcription_inference", "mt3")


@dataclass
class MidiInfo:
    note_count: int
    duration_sec: float
    bpm_estimate: float | None


class StudioApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Studio Tools - Stem to MIDI")
        self.root.geometry("980x700")
        self.root.minsize(900, 620)

        self.audio_path_var = StringVar()
        self.stem_type_var = StringVar(value="vocals")
        self.midi_engine_var = StringVar(value="basic_pitch")
        self.output_dir_var = StringVar()
        self.status_var = StringVar(value="Sẵn sàng.")
        self.midi_path_var = StringVar(value="")
        self.worker_running = False
        self.ui_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self._build_ui()
        self.root.after(120, self._drain_queue)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=14)
        main.pack(fill="both", expand=True)

        title = ttk.Label(
            main,
            text="Studio Tools: Tách Stem + Get MIDI (Local)",
            font=("Segoe UI", 15, "bold"),
        )
        title.pack(anchor="w")

        subtitle = ttk.Label(
            main,
            text=(
                "Flow: Chọn file audio/video -> Tách stem (demucs) -> "
                "Get MIDI (basic-pitch/piano/MT3) -> Preview MIDI info"
            ),
            foreground="#555555",
        )
        subtitle.pack(anchor="w", pady=(2, 12))

        # Input section
        input_group = ttk.LabelFrame(main, text="1) Input", padding=10)
        input_group.pack(fill="x")

        ttk.Label(input_group, text="File audio/video:").grid(row=0, column=0, sticky="w")
        ttk.Entry(
            input_group, textvariable=self.audio_path_var, width=90
        ).grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Button(input_group, text="Browse", command=self.browse_audio).grid(
            row=1, column=1, sticky="ew"
        )

        ttk.Label(input_group, text="Stem type:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        stem_combo = ttk.Combobox(
            input_group,
            textvariable=self.stem_type_var,
            values=STEM_TYPES,
            state="readonly",
            width=16,
        )
        stem_combo.grid(row=3, column=0, sticky="w")

        ttk.Label(input_group, text="MIDI engine:").grid(row=2, column=1, sticky="w", pady=(10, 0))
        engine_combo = ttk.Combobox(
            input_group,
            textvariable=self.midi_engine_var,
            values=MIDI_ENGINES,
            state="readonly",
            width=34,
        )
        engine_combo.grid(row=3, column=1, sticky="w")

        ttk.Label(input_group, text="Output folder (optional):").grid(
            row=4, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Entry(
            input_group, textvariable=self.output_dir_var, width=90
        ).grid(row=5, column=0, padx=(0, 8), sticky="ew")
        ttk.Button(input_group, text="Browse", command=self.browse_output).grid(
            row=5, column=1, sticky="ew"
        )
        input_group.columnconfigure(0, weight=1)

        # Actions
        action_group = ttk.LabelFrame(main, text="2) Actions", padding=10)
        action_group.pack(fill="x", pady=(12, 0))
        self.separate_btn = ttk.Button(
            action_group, text="Tách Stem", command=self.run_separation_only
        )
        self.separate_btn.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        self.midi_btn = ttk.Button(
            action_group, text="Get MIDI (từ stem đã có)", command=self.run_midi_only
        )
        self.midi_btn.grid(row=0, column=1, padx=(0, 8), sticky="ew")
        self.all_btn = ttk.Button(action_group, text="Run Full Pipeline", command=self.run_all)
        self.all_btn.grid(row=0, column=2, padx=(0, 8), sticky="ew")
        self.open_btn = ttk.Button(
            action_group, text="Mở output folder", command=self.open_output_folder
        )
        self.open_btn.grid(row=0, column=3, padx=(0, 8), sticky="ew")
        self.copy_btn = ttk.Button(action_group, text="Copy MIDI path", command=self.copy_midi_path)
        self.copy_btn.grid(row=0, column=4, sticky="ew")
        for i in range(5):
            action_group.columnconfigure(i, weight=1)

        # Result
        result_group = ttk.LabelFrame(main, text="3) Result", padding=10)
        result_group.pack(fill="x", pady=(12, 0))
        self.result_text = ttk.Label(result_group, text="Chưa có MIDI output.")
        self.result_text.pack(anchor="w")

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 0))

        status_bar = ttk.Label(main, textvariable=self.status_var, anchor="w")
        status_bar.pack(fill="x", pady=(4, 8))

        # Log
        log_group = ttk.LabelFrame(main, text="Log", padding=10)
        log_group.pack(fill="both", expand=True)
        self.log_text = ttk.Treeview(log_group, columns=("line",), show="tree", height=16)
        self.log_text.pack(fill="both", expand=True)

    def browse_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="Chọn audio/video input",
            filetypes=[
                ("Audio/Video", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg *.mp4 *.mkv *.mov"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.audio_path_var.set(path)

    def browse_output(self) -> None:
        path = filedialog.askdirectory(title="Chọn output folder")
        if path:
            self.output_dir_var.set(path)

    def run_separation_only(self) -> None:
        self._start_worker(pipeline="separate")

    def run_midi_only(self) -> None:
        self._start_worker(pipeline="midi")

    def run_all(self) -> None:
        self._start_worker(pipeline="all")

    def _start_worker(self, pipeline: str) -> None:
        if self.worker_running:
            messagebox.showwarning("Đang chạy", "Tiến trình đang chạy. Vui lòng chờ hoàn tất.")
            return

        audio_path = Path(self.audio_path_var.get().strip())
        if not audio_path.exists():
            messagebox.showerror("Thiếu file", "Vui lòng chọn file audio/video hợp lệ.")
            return
        if audio_path.suffix.lower() not in SUPPORTED_AUDIO_EXTS:
            messagebox.showerror("Không hỗ trợ", f"Định dạng {audio_path.suffix} chưa được hỗ trợ.")
            return

        base_out = self._resolve_output_dir(audio_path)
        base_out.mkdir(parents=True, exist_ok=True)
        self._set_running(True)
        self._append_log(f"== Start pipeline: {pipeline} ==")
        self.result_text.config(text="Đang xử lý...")
        self.status_var.set("Đang chạy...")

        thread = threading.Thread(
            target=self._worker_entry,
            args=(pipeline, audio_path, base_out, self.stem_type_var.get(), self.midi_engine_var.get()),
            daemon=True,
        )
        thread.start()

    def _worker_entry(
        self, pipeline: str, audio_path: Path, base_out: Path, stem_type: str, midi_engine: str
    ) -> None:
        try:
            stem_file: Path | None = None
            if pipeline in ("separate", "all"):
                self._queue("status", "Đang tách stem bằng demucs...")
                try:
                    stem_file = self.run_demucs(audio_path, stem_type, base_out / "stems")
                    self._queue("log", f"[OK] Stem file: {stem_file}")
                except Exception as demucs_exc:
                    self._queue(
                        "log",
                        "[WARN] Demucs lỗi (thường do torchcodec). "
                        "Fallback: dùng input audio làm stem tạm để tiếp tục MIDI.",
                    )
                    self._queue("log", f"[WARN] Demucs error: {demucs_exc}")
                    stem_file = self.prepare_input_as_stem(audio_path, base_out / "stems", stem_type)
                    self._queue("log", f"[OK] Stem fallback file: {stem_file}")

            if pipeline in ("midi", "all"):
                if stem_file is None:
                    stem_file = self.find_existing_stem(audio_path, base_out / "stems", stem_type)
                if stem_file is None:
                    self._queue("log", "[INFO] Không thấy stem sẵn có, chạy tách stem tự động...")
                    self._queue("status", "Không thấy stem, đang tách lại bằng demucs...")
                    try:
                        stem_file = self.run_demucs(audio_path, stem_type, base_out / "stems")
                        self._queue("log", f"[OK] Stem file (auto): {stem_file}")
                    except Exception as demucs_exc:
                        self._queue(
                            "log",
                            "[WARN] Demucs auto lỗi. Fallback: convert input sang stem WAV tạm...",
                        )
                        self._queue("log", f"[WARN] Demucs error: {demucs_exc}")
                        stem_file = self.prepare_input_as_stem(audio_path, base_out / "stems", stem_type)
                        self._queue("log", f"[OK] Stem fallback file (auto): {stem_file}")
                stem_file = self.ensure_wav_stem(stem_file, base_out / "stems")

                detected_bpm = self.detect_bpm_from_audio(stem_file)
                self._queue("log", f"[INFO] BPM sẽ dùng để quantize: {detected_bpm:.1f}")
                self._queue("status", f"Đang convert MIDI bằng {midi_engine}...")
                midi_file = self.run_midi_transcription(
                    stem_file, base_out / "midi", midi_engine, bpm=detected_bpm
                )
                info = self.inspect_midi(midi_file)
                self._queue("result", self._render_result(midi_file, info))
                self._queue("status", f"Hoàn tất! MIDI: {midi_file}")
                self._queue("midi_path", str(midi_file))
            else:
                self._queue("status", "Tách stem xong.")

        except Exception as exc:
            self._queue("error", str(exc))
        finally:
            self._queue("done", "")

    def run_demucs(self, input_audio: Path, stem_type: str, output_root: Path) -> Path:
        output_root.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, "-m", "demucs"]
        if stem_type == "vocals":
            # two-stems=vocals sẽ xuất vocals.wav + no_vocals.wav (nhanh hơn)
            args.append("--two-stems=vocals")
        # Xuất mp3 để tránh lỗi torchaudio/torchcodec khi ghi wav trên một số máy Windows.
        args.append("--mp3")
        args.extend(["--out", str(output_root), str(input_audio)])
        self._stream_process(args, cwd=output_root)
        found = self.find_existing_stem(input_audio, output_root, stem_type)
        if found is None:
            raise RuntimeError("demucs chạy xong nhưng không tìm thấy file stem output (wav/mp3).")
        return found

    def ensure_wav_stem(self, stem_file: Path, stems_root: Path) -> Path:
        if stem_file.suffix.lower() == ".wav":
            return stem_file
        wav_path = stem_file.with_suffix(".wav")
        args = ["ffmpeg", "-y", "-i", str(stem_file), str(wav_path)]
        self._queue("log", "[INFO] Convert stem sang WAV bằng ffmpeg...")
        self._stream_process(args, cwd=stems_root)
        if not wav_path.exists():
            raise RuntimeError("Convert stem sang WAV thất bại.")
        return wav_path

    def prepare_input_as_stem(self, input_audio: Path, output_root: Path, stem_type: str) -> Path:
        output_root.mkdir(parents=True, exist_ok=True)
        fallback_wav = output_root / f"{input_audio.stem}_{stem_type}_fallback.wav"
        args = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_audio),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(fallback_wav),
        ]
        self._queue("status", "Đang tạo stem fallback từ input bằng ffmpeg...")
        self._stream_process(args, cwd=output_root)
        if not fallback_wav.exists():
            raise RuntimeError("Không tạo được stem fallback WAV từ input.")
        return fallback_wav

    def run_midi_transcription(
        self, stem_file: Path, output_root: Path, engine: str, bpm: float | None = None
    ) -> Path:
        output_root.mkdir(parents=True, exist_ok=True)
        stem_file_str = str(stem_file)
        output_root_str = str(output_root)

        if engine == "basic_pitch":
            return self.run_basic_pitch(stem_file, output_root, bpm=bpm)

        if engine == "mt3":
            # Package mt3 có nhiều wrapper khác nhau; thử theo thứ tự phổ biến.
            tried_commands: list[list[str]] = [
                [sys.executable, "-m", "mt3", stem_file_str, "--output_dir", output_root_str],
                [sys.executable, "-m", "mt3", "--output_dir", output_root_str, stem_file_str],
            ]
            self._queue(
                "log",
                "[WARN] MT3 CLI không có chuẩn chung theo từng bản cài; "
                "đang thử command phổ biến trước khi fallback.",
            )
            last_error: Exception | None = None
            for cmd in tried_commands:
                try:
                    self._stream_process(cmd, cwd=output_root)
                    return self._latest_midi_or_raise(output_root, "mt3")
                except Exception as exc:
                    last_error = exc
                    self._queue("log", f"[WARN] MT3 command failed, thử command khác... ({exc})")
            self._queue(
                "log",
                "[WARN] Không chạy được MT3 CLI mặc định. Tự động fallback sang piano_transcription_inference...",
            )
            try:
                return self.run_piano_transcription(stem_file, output_root)
            except Exception as fallback_exc:
                raise RuntimeError(
                    "Không chạy được MT3 CLI và fallback piano_transcription_inference cũng thất bại. "
                    f"Lỗi chi tiết: {fallback_exc}"
                ) from fallback_exc

        if engine == "piano_transcription_inference":
            return self.run_piano_transcription(stem_file, output_root)

        raise RuntimeError(f"MIDI engine không hợp lệ: {engine}")

    def run_basic_pitch(self, stem_file: Path, output_root: Path, bpm: float | None = None) -> Path:
        tuned = dict(
            onset_threshold=0.6,
            frame_threshold=0.4,
            minimum_note_length=80,
            minimum_frequency=32.7,
            maximum_frequency=2093.0,
        )
        start_ts = time.time()

        # 1) Newer API path: predict_and_save (signature differs by version).
        try:
            from basic_pitch.inference import predict_and_save

            sig = inspect.signature(predict_and_save)
            kwargs = {}
            if "output_directory" in sig.parameters:
                kwargs["output_directory"] = str(output_root)
            elif "output_dir" in sig.parameters:
                kwargs["output_dir"] = str(output_root)
            for k, v in tuned.items():
                if k in sig.parameters:
                    kwargs[k] = v
            for k, v in {
                "save_midi": True,
                "sonify_midi": False,
                "save_model_outputs": False,
                "save_notes": False,
            }.items():
                if k in sig.parameters:
                    kwargs[k] = v
            if "melodia_trick" in sig.parameters:
                kwargs["melodia_trick"] = True

            self._queue("log", "[INFO] Chạy predict_and_save (basic-pitch API mới)...")
            predict_and_save([str(stem_file)], **kwargs)
        except Exception as exc_new:
            self._queue("log", f"[WARN] predict_and_save fail, thử predict legacy... ({exc_new})")
            # 2) Legacy API path: predict (some versions don't accept output_directory).
            try:
                from basic_pitch.inference import predict

                sig = inspect.signature(predict)
                kwargs = {}
                for k, v in tuned.items():
                    if k in sig.parameters:
                        kwargs[k] = v
                if "output_directory" in sig.parameters:
                    kwargs["output_directory"] = str(output_root)
                elif "output_dir" in sig.parameters:
                    kwargs["output_dir"] = str(output_root)

                result = predict(str(stem_file), **kwargs)
                wrote = self._write_midi_from_predict_result(result, output_root, stem_file)
                if wrote is not None:
                    self._queue("log", f"[INFO] Legacy predict wrote MIDI: {wrote.name}")
            except Exception as exc_old:
                self._queue(
                    "log",
                    f"[WARN] predict legacy fail, fallback CLI basic_pitch... ({exc_old})",
                )
                # 3) CLI fallback for widest compatibility.
                args = [sys.executable, "-m", "basic_pitch", str(output_root), str(stem_file)]
                self._stream_process(args, cwd=output_root)

        # Last chance: pick freshest midi after invocation.
        midi_files = sorted(
            [*output_root.glob("*.mid"), *output_root.glob("*.midi")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not midi_files:
            # Some very old versions may write beside input file.
            input_side = [
                p
                for p in [*stem_file.parent.glob("*.mid"), *stem_file.parent.glob("*.midi")]
                if p.stat().st_mtime >= start_ts - 2
            ]
            input_side.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            if input_side:
                candidate = input_side[0]
                moved = output_root / candidate.name
                if candidate.resolve() != moved.resolve():
                    shutil.copy2(candidate, moved)
                midi_files = [moved]

        if not midi_files:
            raise RuntimeError(
                "basic-pitch không xuất được MIDI ở mọi đường API/CLI. "
                "Kiểm tra version basic-pitch và log lỗi phía trên."
            )

        midi_file = midi_files[0]
        self._queue("log", f"[INFO] basic_pitch MIDI: {midi_file.name}")
        return self.post_process_midi(midi_file, bpm=bpm)

    def _write_midi_from_predict_result(self, result, output_root: Path, stem_file: Path) -> Path | None:
        # Legacy predict often returns tuple(model_output, midi_data, note_events)
        # where midi_data may expose .write(path).
        midi_obj = None
        if isinstance(result, tuple) and len(result) >= 2:
            midi_obj = result[1]
        elif isinstance(result, dict):
            midi_obj = result.get("midi") or result.get("midi_data")

        if midi_obj is not None and hasattr(midi_obj, "write"):
            target = output_root / f"{stem_file.stem}_basic_pitch.mid"
            midi_obj.write(str(target))
            if target.exists():
                return target
        return None

    def post_process_midi(self, midi_path: Path, bpm: float | None = None) -> Path:
        try:
            import pretty_midi

            pm = pretty_midi.PrettyMIDI(str(midi_path))
            effective_bpm = bpm if bpm is not None else self.estimate_bpm(pm)
            snapped_bpm = max(40, min(240, round(effective_bpm)))
            quantized = self.quantize_to_grid(pm, bpm=snapped_bpm, resolution=0.125)
            cleaned_path = midi_path.with_name(midi_path.stem + "_pretty.mid")
            quantized.write(str(cleaned_path))
            if cleaned_path.exists():
                self._queue(
                    "log",
                    f"[INFO] pretty_midi export: {cleaned_path.name} "
                    f"(quantized, bpm_snap={snapped_bpm})",
                )
                return cleaned_path
        except Exception as exc:
            self._queue("log", f"[WARN] pretty_midi post-process bỏ qua: {exc}")
        return midi_path

    def detect_bpm_from_audio(self, audio_path: Path) -> float:
        try:
            import librosa

            y, sr = librosa.load(str(audio_path), sr=None, mono=True)
            tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
            bpm = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
            bpm = max(40.0, min(240.0, bpm))
            self._queue("log", f"[INFO] librosa BPM detect: {bpm:.1f}")
            return bpm
        except Exception as exc:
            self._queue("log", f"[WARN] librosa BPM fail, dùng 120: {exc}")
            return 120.0

    def estimate_bpm(self, pm) -> float:
        try:
            _, tempi = pm.get_tempo_changes()
            if len(tempi) > 0 and tempi[0] > 0:
                return float(tempi[0])
        except Exception:
            pass
        return 120.0

    def quantize_to_grid(self, pm, bpm: float, resolution: float = 0.125):
        sec_per_beat = 60.0 / max(1.0, bpm)
        step = max(1e-4, sec_per_beat * resolution)
        for instrument in pm.instruments:
            for note in instrument.notes:
                q_start = round(note.start / step) * step
                q_end = round(note.end / step) * step
                if q_end <= q_start:
                    q_end = q_start + step
                note.start = max(0.0, q_start)
                note.end = max(note.start + 1e-4, q_end)
        return pm

    def run_piano_transcription(self, stem_file: Path, output_root: Path) -> Path:
        stem_file_str = str(stem_file)
        output_root_str = str(output_root)

        # Ưu tiên CLI nếu có; nếu fail thì fallback sang Python API.
        cli_commands = [
            [sys.executable, "-m", "piano_transcription_inference", stem_file_str, output_root_str],
            [sys.executable, "-m", "piano_transcription_inference.inference", stem_file_str, output_root_str],
        ]
        for cmd in cli_commands:
            try:
                self._stream_process(cmd, cwd=output_root)
                return self._latest_midi_or_raise(output_root, "piano_transcription_inference")
            except Exception as exc:
                self._queue("log", f"[WARN] Piano CLI failed, thử cách khác... ({exc})")

        # Fallback cuối: gọi Python API trực tiếp để tránh phụ thuộc CLI của từng version.
        try:
            self._queue("log", "[INFO] Chuyển sang Python API của piano_transcription_inference...")
            import torch
            from piano_transcription_inference import (
                PianoTranscription,
                load_audio,
                sample_rate,
            )

            midi_path = output_root / f"{stem_file.stem}_piano_api.mid"
            device = "cuda" if torch.cuda.is_available() else "cpu"
            self._queue("log", f"[INFO] Piano API device: {device}")
            checkpoint_path = self.ensure_piano_checkpoint()
            self._queue("log", f"[INFO] Piano checkpoint: {checkpoint_path}")

            audio, _ = load_audio(stem_file_str, sr=sample_rate, mono=True)
            transcriptor = PianoTranscription(
                checkpoint_path=str(checkpoint_path),
                device=device,
            )
            transcriptor.transcribe(audio, str(midi_path))

            if midi_path.exists():
                return midi_path
            return self._latest_midi_or_raise(output_root, "piano_transcription_inference")
        except Exception as exc:
            raise RuntimeError(
                "piano_transcription_inference bị lỗi ở cả CLI và Python API. "
                f"Kiểm tra package, ffmpeg, và các dependency torch. Lỗi chi tiết: {exc}"
            ) from exc

    def ensure_piano_checkpoint(self) -> Path:
        checkpoint_path = Path.home() / "piano_transcription_inference_data" / (
            "note_F1=0.9677_pedal_F1=0.9186.pth"
        )
        if checkpoint_path.exists() and checkpoint_path.stat().st_size > 160_000_000:
            return checkpoint_path

        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            "https://zenodo.org/record/4034264/files/"
            "CRNN_note_F1%3D0.9677_pedal_F1%3D0.9186.pth?download=1"
        )
        self._queue("status", "Đang tải model piano (~165MB), chờ 1 lần đầu...")
        self._queue("log", f"[INFO] Download checkpoint từ: {url}")
        urllib.request.urlretrieve(url, str(checkpoint_path))
        if not checkpoint_path.exists() or checkpoint_path.stat().st_size < 160_000_000:
            raise RuntimeError("Tải checkpoint thất bại hoặc file model không đầy đủ.")
        return checkpoint_path

    def _latest_midi_or_raise(self, output_root: Path, engine: str) -> Path:
        midi_files = sorted(
            [*output_root.glob("*.mid"), *output_root.glob("*.midi")],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not midi_files:
            raise RuntimeError(
                f"{engine} chạy xong nhưng không tìm thấy file .mid/.midi. "
                "Kiểm tra package engine, đầu vào WAV hợp lệ và ffmpeg."
            )
        return midi_files[0]

    def find_existing_stem(self, input_audio: Path, output_root: Path, stem_type: str) -> Path | None:
        search_roots = [output_root]
        # Demucs thường xuất vào output_root/model_name/input_name/*.wav
        # fallback thêm thư mục cạnh input nếu user đã chạy demucs ngoài app.
        if input_audio.parent not in search_roots:
            search_roots.append(input_audio.parent)

        candidates: list[Path] = []
        for root in search_roots:
            if not root.exists():
                continue
            candidates.extend(root.rglob(f"{stem_type}.wav"))
            candidates.extend(root.rglob(f"{stem_type}.mp3"))
        if candidates:
            return max(candidates, key=lambda p: p.stat().st_mtime)

        # Fallback cho two-stems=vocals: demucs thường xuất vocals.wav và no_vocals.wav
        if stem_type == "other":
            alt: list[Path] = []
            for root in search_roots:
                if root.exists():
                    alt.extend(root.rglob("no_vocals.wav"))
                    alt.extend(root.rglob("no_vocals.mp3"))
            if alt:
                return max(alt, key=lambda p: p.stat().st_mtime)

        # fallback cuối: bất kỳ wav mới nhất trong vùng tìm kiếm
        guessed: list[Path] = []
        for root in search_roots:
            if root.exists():
                guessed.extend(root.rglob("*.wav"))
                guessed.extend(root.rglob("*.mp3"))
        if guessed:
            return max(guessed, key=lambda p: p.stat().st_mtime)
        return None

    def inspect_midi(self, midi_path: Path) -> MidiInfo:
        if mido is None:
            return MidiInfo(note_count=0, duration_sec=0.0, bpm_estimate=None)

        mid = mido.MidiFile(str(midi_path))
        note_count = 0
        tempo_us = None

        for track in mid.tracks:
            for msg in track:
                if msg.type == "note_on" and getattr(msg, "velocity", 0) > 0:
                    note_count += 1
                elif msg.type == "set_tempo" and tempo_us is None:
                    tempo_us = msg.tempo

        bpm = None
        if tempo_us:
            bpm = round(mido.tempo2bpm(tempo_us), 2)
        return MidiInfo(note_count=note_count, duration_sec=mid.length, bpm_estimate=bpm)

    def _render_result(self, midi_path: Path, info: MidiInfo) -> str:
        bpm_display = f"{info.bpm_estimate}" if info.bpm_estimate is not None else "N/A"
        return (
            f"MIDI: {midi_path}\n"
            f"Notes: {info.note_count}\n"
            f"Duration: {info.duration_sec:.2f} sec\n"
            f"BPM estimate: {bpm_display}"
        )

    def _stream_process(self, args: list[str], cwd: Path) -> None:
        self._queue("log", "CMD: " + " ".join(f'"{a}"' if " " in a else a for a in args))
        run_cwd = cwd
        try:
            run_cwd.mkdir(parents=True, exist_ok=True)
        except Exception:
            run_cwd = Path.cwd()
            self._queue(
                "log",
                f"[WARN] CWD không hợp lệ, fallback về current dir: {run_cwd}",
            )

        if not run_cwd.exists():
            run_cwd = Path.cwd()
            self._queue(
                "log",
                f"[WARN] CWD không tồn tại, fallback về current dir: {run_cwd}",
            )
        self._queue("log", f"[INFO] Process CWD: {run_cwd}")

        proc = subprocess.Popen(
            args,
            cwd=str(run_cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert proc.stdout is not None
        last_lines: list[str] = []
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                self._queue("log", line)
                last_lines.append(line)
                if len(last_lines) > 12:
                    last_lines.pop(0)
        code = proc.wait()
        if code != 0:
            details = "\n".join(last_lines[-6:]).strip()
            hint = (
                "\n\nGợi ý: kiểm tra đã cài ffmpeg và package engine tương ứng "
                "(demucs/basic_pitch/piano_transcription_inference/mt3) chưa. "
                "Nếu thấy lỗi TorchCodec thì cài: pip install torchcodec."
            )
            if details:
                raise RuntimeError(f"Command failed with exit code {code}.\n\n{details}{hint}")
            raise RuntimeError(f"Command failed with exit code {code}.{hint}")

    def _resolve_output_dir(self, audio_path: Path) -> Path:
        custom = self.output_dir_var.get().strip()
        if custom:
            return Path(custom)
        safe_stem = "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in audio_path.stem).strip()
        if not safe_stem:
            safe_stem = "audio"
        return audio_path.parent / f"{safe_stem}_studio_output"

    def _queue(self, kind: str, payload: str) -> None:
        self.ui_queue.put((kind, payload))

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, payload = self.ui_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self._append_log(payload)
            elif kind == "status":
                self.status_var.set(payload)
            elif kind == "result":
                self.result_text.config(text=payload)
            elif kind == "midi_path":
                self.midi_path_var.set(payload)
            elif kind == "error":
                self._append_log("[ERROR] " + payload)
                self.status_var.set("Lỗi khi xử lý.")
                messagebox.showerror("Lỗi", payload)
            elif kind == "done":
                self._set_running(False)
                self._append_log("== End ==")

        self.root.after(120, self._drain_queue)

    def _append_log(self, line: str) -> None:
        self.log_text.insert("", "end", text=line)
        children = self.log_text.get_children("")
        if len(children) > 1500:
            for old in children[:200]:
                self.log_text.delete(old)
        tail = self.log_text.get_children("")
        if tail:
            self.log_text.see(tail[-1])

    def _set_running(self, running: bool) -> None:
        self.worker_running = running
        state = "disabled" if running else "normal"
        self.separate_btn.config(state=state)
        self.midi_btn.config(state=state)
        self.all_btn.config(state=state)
        if running:
            self.progress.start(12)
        else:
            self.progress.stop()

    def open_output_folder(self) -> None:
        audio_path = Path(self.audio_path_var.get().strip())
        if not audio_path.exists():
            messagebox.showwarning("Thiếu input", "Chọn file input trước để xác định output folder.")
            return
        out = self._resolve_output_dir(audio_path)
        out.mkdir(parents=True, exist_ok=True)
        os.startfile(str(out))

    def copy_midi_path(self) -> None:
        p = self.midi_path_var.get().strip()
        if not p:
            messagebox.showinfo("Chưa có MIDI", "Chạy Get MIDI trước để copy đường dẫn.")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(p)
        self.status_var.set("Đã copy MIDI path.")


def check_tools() -> list[str]:
    missing: list[str] = []
    for module_name in ("demucs", "basic_pitch"):
        if shutil.which(module_name) is None:
            # module can still run via python -m, check import
            try:
                __import__(module_name)
            except Exception:
                missing.append(module_name)
    return missing


def main() -> None:
    root = Tk()
    app = StudioApp(root)

    missing = check_tools()
    if missing:
        messagebox.showwarning(
            "Thiếu package",
            "Chưa cài đủ package Python:\n"
            + "\n".join(f"- {m}" for m in missing)
            + "\n\nCài bằng lệnh: pip install demucs basic-pitch pretty_midi mido",
        )

    root.mainloop()


if __name__ == "__main__":
    main()
