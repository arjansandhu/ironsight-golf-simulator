"""
IronSight Main Window — PyQt6 GUI.

Unified training interface with:
  - 3D ball flight visualization (Three.js in QWebEngineView)
  - Swing video player
  - Shot data panel
  - Session history
  - Club selector
"""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import (
    Qt, QTimer, QUrl, pyqtSignal, pyqtSlot, QSize,
)
from PyQt6.QtGui import QImage, QPixmap, QAction, QFont, QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QLabel, QPushButton, QComboBox, QTextEdit,
    QListWidget, QListWidgetItem, QStatusBar, QToolBar,
    QFrame, QGroupBox, QGridLayout, QSlider, QFileDialog,
    QMessageBox,
)
from PyQt6.QtWebEngineWidgets import QWebEngineView

from src.ball_flight import compute_shot
from src.models.shot import ClubData, Shot
from src.models.session import Session
from src.models.club import ClubType

logger = logging.getLogger(__name__)

# Path to visualizer HTML
VISUALIZER_DIR = Path(__file__).parent / "visualizer"
VISUALIZER_HTML = VISUALIZER_DIR / "index.html"


class MainWindow(QMainWindow):
    """Main application window for IronSight Golf Simulator."""

    def __init__(self, reader, camera=None, parent=None):
        """
        Args:
            reader: OptiShotReader or MockOptiShotReader instance.
            camera: CameraCapture instance (optional).
        """
        super().__init__(parent)
        self.reader = reader
        self.camera = camera
        self.session = Session()
        self.shots: list[Shot] = []
        self.current_shot_idx = -1

        self.setWindowTitle("IronSight Golf Simulator")
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

        self._setup_ui()
        self._connect_signals()
        self._start_threads()

        self.statusBar().showMessage("Ready — waiting for swings")

    def _setup_ui(self):
        """Build the main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(4, 4, 4, 4)
        main_layout.setSpacing(4)

        # --- Toolbar ---
        self._setup_toolbar()

        # --- Main content: splitter with viz + video ---
        content_splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: 3D Visualization
        self.web_view = QWebEngineView()
        url = QUrl.fromLocalFile(str(VISUALIZER_HTML.resolve()))
        self.web_view.setUrl(url)
        self.web_view.setMinimumWidth(600)
        content_splitter.addWidget(self.web_view)

        # Right: Video + Shot Data
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        # Video display
        video_group = QGroupBox("Swing Video")
        video_layout = QVBoxLayout(video_group)
        self.video_label = QLabel("No camera")
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.setMinimumSize(320, 240)
        self.video_label.setStyleSheet(
            "background-color: #1a1a2e; color: #666; "
            "border: 1px solid #333; border-radius: 4px;"
        )
        video_layout.addWidget(self.video_label)

        # Playback controls
        playback_layout = QHBoxLayout()
        self.btn_slow_mo = QPushButton("0.5x")
        self.btn_slow_mo.setMaximumWidth(50)
        self.btn_normal = QPushButton("1x")
        self.btn_normal.setMaximumWidth(50)
        playback_layout.addWidget(self.btn_slow_mo)
        playback_layout.addWidget(self.btn_normal)
        playback_layout.addStretch()
        video_layout.addLayout(playback_layout)

        right_layout.addWidget(video_group)

        # Shot data panel
        shot_group = QGroupBox("Shot Data")
        shot_grid = QGridLayout(shot_group)
        shot_grid.setSpacing(4)

        self.shot_labels = {}
        stats = [
            ("Club Speed", "club_speed"), ("Ball Speed", "ball_speed"),
            ("Launch Angle", "vla"), ("Spin Rate", "spin"),
            ("Carry", "carry"), ("Total", "total"),
            ("Apex", "apex"), ("Lateral", "lateral"),
            ("Shot Shape", "shape"),
        ]
        for i, (label_text, key) in enumerate(stats):
            row, col = divmod(i, 2)
            lbl = QLabel(f"<span style='color:#888;font-size:11px;'>{label_text}</span>")
            val = QLabel("<span style='color:#4CAF50;font-size:16px;font-weight:bold;'>—</span>")
            val.setTextFormat(Qt.TextFormat.RichText)
            lbl.setTextFormat(Qt.TextFormat.RichText)
            shot_grid.addWidget(lbl, row, col * 2)
            shot_grid.addWidget(val, row, col * 2 + 1)
            self.shot_labels[key] = val

        right_layout.addWidget(shot_group)
        right_panel.setMaximumWidth(400)
        content_splitter.addWidget(right_panel)
        content_splitter.setSizes([900, 400])

        main_layout.addWidget(content_splitter, stretch=3)

        # --- Session History ---
        history_group = QGroupBox("Session History")
        history_layout = QVBoxLayout(history_group)
        history_layout.setContentsMargins(4, 4, 4, 4)
        self.shot_list = QListWidget()
        self.shot_list.setMaximumHeight(150)
        self.shot_list.setAlternatingRowColors(True)
        self.shot_list.setStyleSheet(
            "QListWidget { background-color: #1e1e2e; color: #e0e0e0; "
            "border: 1px solid #333; font-size: 13px; }"
            "QListWidget::item:selected { background-color: #2d5a1e; }"
            "QListWidget::item:alternate { background-color: #252540; }"
        )
        self.shot_list.itemClicked.connect(self._on_shot_selected)
        history_layout.addWidget(self.shot_list)
        main_layout.addWidget(history_group, stretch=1)

        # Apply dark theme
        self._apply_dark_theme()

    def _setup_toolbar(self):
        """Create the toolbar with club selector and controls."""
        toolbar = QToolBar("Main Toolbar")
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(24, 24))
        self.addToolBar(toolbar)

        # Club selector
        club_label = QLabel(" Club: ")
        club_label.setStyleSheet("color: #ccc; font-weight: bold;")
        toolbar.addWidget(club_label)

        self.club_combo = QComboBox()
        self.club_combo.setMinimumWidth(120)
        for ct in ClubType:
            self.club_combo.addItem(ct.value)
        self.club_combo.setCurrentText("7-Iron")
        self.club_combo.currentTextChanged.connect(self._on_club_changed)
        toolbar.addWidget(self.club_combo)

        toolbar.addSeparator()

        # Clear shots button
        btn_clear = QPushButton("Clear Shots")
        btn_clear.clicked.connect(self._clear_shots)
        toolbar.addWidget(btn_clear)

        # Reset camera button
        btn_reset_cam = QPushButton("Reset Camera")
        btn_reset_cam.clicked.connect(
            lambda: self.web_view.page().runJavaScript("window.resetCamera()")
        )
        toolbar.addWidget(btn_reset_cam)

        toolbar.addSeparator()

        # Trigger mock swing (useful for testing)
        btn_trigger = QPushButton("Trigger Swing")
        btn_trigger.setToolTip("Manually trigger a simulated swing")
        btn_trigger.clicked.connect(self._trigger_mock_swing)
        toolbar.addWidget(btn_trigger)

        toolbar.addSeparator()

        # Export CSV
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self._export_csv)
        toolbar.addWidget(btn_export)

    def _apply_dark_theme(self):
        """Apply a dark color scheme."""
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e2e; }
            QWidget { color: #e0e0e0; }
            QGroupBox {
                color: #aaa;
                border: 1px solid #333;
                border-radius: 4px;
                margin-top: 8px;
                padding-top: 16px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
            }
            QToolBar {
                background-color: #252540;
                border-bottom: 1px solid #333;
                spacing: 8px;
                padding: 4px;
            }
            QPushButton {
                background-color: #2d5a1e;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 14px;
                font-weight: bold;
            }
            QPushButton:hover { background-color: #3d8b2e; }
            QPushButton:pressed { background-color: #1e4a10; }
            QComboBox {
                background-color: #333;
                color: #e0e0e0;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QComboBox::drop-down { border: none; }
            QStatusBar { background-color: #1a1a2e; color: #888; }
        """)

    def _connect_signals(self):
        """Connect reader and camera signals to handlers."""
        self.reader.swing_detected.connect(self._on_swing)
        self.reader.device_connected.connect(
            lambda: self.statusBar().showMessage("OptiShot connected")
        )
        self.reader.device_disconnected.connect(
            lambda: self.statusBar().showMessage("OptiShot disconnected")
        )
        self.reader.error_occurred.connect(
            lambda msg: self.statusBar().showMessage(f"Error: {msg}")
        )

        if self.camera:
            self.camera.frame_ready.connect(self._on_camera_frame)
            self.camera.clip_saved.connect(self._on_clip_saved)

    def _start_threads(self):
        """Start the USB reader and camera threads."""
        self.reader.start()
        if self.camera:
            self.camera.start()

    @pyqtSlot(object)
    def _on_swing(self, club_data: ClubData):
        """Handle a swing event from the USB reader."""
        # Compute ball flight
        launch, trajectory = compute_shot(club_data)

        # Create shot record
        shot = Shot(
            club_data=club_data,
            ball_launch=launch,
            trajectory=trajectory,
            carry_yards=trajectory.carry_yards,
            total_yards=trajectory.total_yards,
            lateral_yards=trajectory.lateral_yards,
            apex_yards=trajectory.apex_yards,
        )
        shot.compute_shape()

        # Store shot
        self.shots.append(shot)
        self.session.add_shot(shot)
        self.current_shot_idx = len(self.shots) - 1

        # Trigger camera clip extraction
        if self.camera:
            self.camera.extract_clip()

        # Send trajectory to Three.js visualizer
        self._send_shot_to_viz(shot)

        # Update shot data panel
        self._update_shot_panel(shot)

        # Add to session history
        self._add_to_history(shot, len(self.shots))

        self.statusBar().showMessage(
            f"Shot #{len(self.shots)}: {club_data.club_type} "
            f"| Carry: {trajectory.carry_yards}yd "
            f"| {shot.shot_shape}"
        )
        logger.info(
            f"Shot #{len(self.shots)}: {club_data.club_type} "
            f"{trajectory.carry_yards}yd {shot.shot_shape}"
        )

    def _send_shot_to_viz(self, shot: Shot):
        """Send shot data to the Three.js visualizer via JS bridge."""
        if not shot.trajectory:
            return

        shot_json = json.dumps({
            "points": shot.trajectory.points,
            "carry": shot.trajectory.carry_yards,
            "total": shot.trajectory.total_yards,
            "apex": shot.trajectory.apex_yards,
            "lateral": shot.trajectory.lateral_yards,
            "flightTime": shot.trajectory.flight_time_s,
            "clubSpeed": shot.club_data.club_speed_mph,
            "ballSpeed": shot.ball_launch.ball_speed_mph if shot.ball_launch else 0,
            "vla": shot.ball_launch.vla_deg if shot.ball_launch else 0,
            "backspin": shot.ball_launch.backspin_rpm if shot.ball_launch else 0,
            "clubType": shot.club_data.club_type,
            "shotShape": shot.shot_shape,
        })

        self.web_view.page().runJavaScript(
            f"window.addShot({shot_json})"
        )

    def _update_shot_panel(self, shot: Shot):
        """Update the shot data display panel."""
        def fmt(key, val, unit=""):
            self.shot_labels[key].setText(
                f"<span style='color:#4CAF50;font-size:16px;"
                f"font-weight:bold;'>{val}{unit}</span>"
            )

        cd = shot.club_data
        bl = shot.ball_launch
        tr = shot.trajectory

        fmt("club_speed", cd.club_speed_mph, " mph")
        fmt("ball_speed", bl.ball_speed_mph if bl else "—", " mph")
        fmt("vla", f"{bl.vla_deg}°" if bl else "—", "")
        fmt("spin", f"{bl.backspin_rpm}" if bl else "—", " rpm")
        fmt("carry", f"{tr.carry_yards}" if tr else "—", " yd")
        fmt("total", f"{tr.total_yards}" if tr else "—", " yd")
        fmt("apex", f"{tr.apex_yards}" if tr else "—", " yd")

        lat = tr.lateral_yards if tr else 0
        lat_dir = "R" if lat > 0 else "L" if lat < 0 else ""
        fmt("lateral", f"{abs(lat):.1f} {lat_dir}", " yd")
        fmt("shape", shot.shot_shape, "")

    def _add_to_history(self, shot: Shot, num: int):
        """Add a shot to the session history list."""
        cd = shot.club_data
        tr = shot.trajectory
        text = (
            f"#{num}  {cd.club_type:8s}  "
            f"{tr.carry_yards:5.0f}yd  "
            f"{shot.shot_shape:8s}  "
            f"Speed: {cd.club_speed_mph}mph"
        )
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, num - 1)  # Store index
        self.shot_list.addItem(item)
        self.shot_list.scrollToBottom()

    def _on_shot_selected(self, item: QListWidgetItem):
        """Handle clicking on a shot in the history list."""
        idx = item.data(Qt.ItemDataRole.UserRole)
        if 0 <= idx < len(self.shots):
            shot = self.shots[idx]
            self._update_shot_panel(shot)
            # Re-animate this shot's trajectory
            self._send_shot_to_viz(shot)
            self.current_shot_idx = idx

            # If there's a video, replay it
            if shot.video_path and os.path.exists(shot.video_path):
                self._play_video(shot.video_path)

    @pyqtSlot(object)
    def _on_camera_frame(self, frame: np.ndarray):
        """Display a live camera frame in the video panel."""
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        q_img = QImage(rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img).scaled(
            self.video_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.video_label.setPixmap(pixmap)

    @pyqtSlot(str)
    def _on_clip_saved(self, path: str):
        """Associate a saved clip with the most recent shot."""
        if self.shots:
            self.shots[-1].video_path = path
            logger.info(f"Video clip linked to shot #{len(self.shots)}: {path}")

    def _play_video(self, video_path: str):
        """Play a video clip in the video panel."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return

        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        frame_delay = int(1000 / fps)

        def show_frame():
            ret, frame = cap.read()
            if ret:
                self._on_camera_frame(frame)
                QTimer.singleShot(frame_delay, show_frame)
            else:
                cap.release()

        show_frame()

    def _on_club_changed(self, club_name: str):
        """Handle club selector change."""
        self.reader.set_club(club_name)
        self.statusBar().showMessage(f"Club changed to {club_name}")

    def _trigger_mock_swing(self):
        """Manually trigger a swing (mock mode only)."""
        if hasattr(self.reader, 'trigger_swing'):
            self.reader.trigger_swing()
        else:
            self.statusBar().showMessage(
                "Manual trigger only works in mock mode"
            )

    def _clear_shots(self):
        """Clear all shots from the visualization and history."""
        self.web_view.page().runJavaScript("window.clearShots()")
        self.shot_list.clear()
        self.shots.clear()
        self.current_shot_idx = -1
        # Reset shot data panel
        for key, label in self.shot_labels.items():
            label.setText(
                "<span style='color:#4CAF50;font-size:16px;"
                "font-weight:bold;'>—</span>"
            )
        self.statusBar().showMessage("Shots cleared")

    def _export_csv(self):
        """Export session data to CSV."""
        if not self.shots:
            QMessageBox.information(self, "Export", "No shots to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Session CSV", "session.csv", "CSV Files (*.csv)"
        )
        if not path:
            return

        import csv
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Shot#", "Club", "ClubSpeed_mph", "FaceAngle_deg",
                "Path_deg", "BallSpeed_mph", "VLA_deg", "HLA_deg",
                "Backspin_rpm", "SpinAxis_deg", "Carry_yd", "Total_yd",
                "Apex_yd", "Lateral_yd", "ShotShape", "VideoPath",
            ])
            for i, s in enumerate(self.shots, 1):
                cd = s.club_data
                bl = s.ball_launch
                writer.writerow([
                    i, cd.club_type, cd.club_speed_mph,
                    cd.face_angle_deg, cd.path_deg,
                    bl.ball_speed_mph if bl else "",
                    bl.vla_deg if bl else "",
                    bl.hla_deg if bl else "",
                    bl.backspin_rpm if bl else "",
                    bl.spin_axis_deg if bl else "",
                    s.carry_yards, s.total_yards,
                    s.apex_yards, s.lateral_yards,
                    s.shot_shape, s.video_path or "",
                ])

        self.statusBar().showMessage(f"Exported {len(self.shots)} shots to {path}")

    def closeEvent(self, event):
        """Clean up threads on window close."""
        self.reader.stop()
        if self.camera:
            self.camera.stop()
            self.camera.wait(3000)
        self.reader.wait(3000)
        event.accept()


def launch_gui(args):
    """Launch the full GUI application."""
    app = QApplication(sys.argv)
    app.setApplicationName("IronSight")
    app.setStyle("Fusion")  # Consistent cross-platform look

    # Create reader
    from src.main import create_reader
    reader = create_reader(args)

    # Create camera (if requested)
    camera = None
    if args.camera:
        from src.camera import CameraCapture
        camera = CameraCapture()

    window = MainWindow(reader, camera)
    window.show()

    sys.exit(app.exec())
