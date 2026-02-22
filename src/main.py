"""
IronSight Golf Simulator — entry point.

Supports multiple modes:
  - CLI mode (Phase 1-2): prints shot data to console
  - GUI mode (Phase 4+): launches PyQt6 application

Usage:
    python -m src.main                    # Auto-detect OptiShot, fallback to mock
    python -m src.main --mock             # Force mock mode
    python -m src.main --mock --preset slicer
    python -m src.main --usb              # Force USB mode (requires OptiShot)
    python -m src.main --camera           # Enable camera capture
    python -m src.main --gui              # Launch full GUI (Phase 4+)
"""

import argparse
import logging
import signal
import sys

from PyQt6.QtCore import QCoreApplication


def setup_logging(verbose: bool = False):
    """Configure logging for the application."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def create_reader(args):
    """Create the appropriate USB reader based on CLI args."""
    mode = args.mode

    if mode == "mock":
        from src.mock_usb_reader import MockOptiShotReader
        preset = getattr(args, "preset", "consistent_player")
        reader = MockOptiShotReader(
            club_type=args.club,
            preset=preset,
            swing_interval=(args.interval_min, args.interval_max),
        )
        return reader

    elif mode == "usb":
        from src.usb_reader import OptiShotReader
        return OptiShotReader(club_type=args.club)

    else:  # auto
        # Try USB first, fallback to mock
        try:
            import hid
            devices = hid.enumerate(0x0547, 0x3294)
            if devices:
                from src.usb_reader import OptiShotReader
                logging.info("OptiShot 2 detected — using USB mode")
                return OptiShotReader(club_type=args.club)
        except Exception:
            pass

        logging.info("OptiShot 2 not detected — using mock mode")
        from src.mock_usb_reader import MockOptiShotReader
        return MockOptiShotReader(
            club_type=args.club,
            preset=getattr(args, "preset", "consistent_player"),
        )


def run_cli(args):
    """Run in CLI mode: print shot data to console."""
    app = QCoreApplication(sys.argv)

    reader = create_reader(args)
    camera = None
    shot_count = [0]

    def on_swing(club_data):
        shot_count[0] += 1
        print(f"\n{'='*60}")
        print(f"  Shot #{shot_count[0]}")
        print(f"{'='*60}")
        print(f"  Club:          {club_data.club_type}")
        print(f"  Club Speed:    {club_data.club_speed_mph} mph")
        print(f"  Face Angle:    {club_data.face_angle_deg}° "
              f"({'open' if club_data.face_angle_deg > 0 else 'closed' if club_data.face_angle_deg < 0 else 'square'})")
        print(f"  Swing Path:    {club_data.path_deg}° "
              f"({'in-to-out' if club_data.path_deg > 0 else 'out-to-in' if club_data.path_deg < 0 else 'neutral'})")
        print(f"  Contact:       {club_data.contact_point}")
        if club_data.tempo:
            print(f"  Tempo:         {club_data.tempo}")
        print(f"{'='*60}")

        # Trigger clip extraction if camera is active
        if camera:
            camera.extract_clip()

    def on_clip_saved(path):
        print(f"  📹 Video clip saved: {path}")

    def on_connected():
        mode_label = "mock" if args.mode == "mock" else "USB"
        print(f"\n✅ OptiShot connected ({mode_label} mode)")
        print(f"   Club: {args.club}")
        if camera:
            print(f"   Camera: enabled")
        print(f"   Waiting for swings... (Ctrl+C to quit)\n")

    def on_error(msg):
        print(f"\n❌ Error: {msg}")

    reader.swing_detected.connect(on_swing)
    reader.device_connected.connect(on_connected)
    reader.error_occurred.connect(on_error)

    # Set up camera if requested
    if args.camera:
        from src.camera import CameraCapture
        config = Config() if 'Config' in dir() else None
        camera = CameraCapture(
            camera_index=0,
            fps=30,
            pre_seconds=2.0,
            post_seconds=2.0,
        )
        camera.clip_saved.connect(on_clip_saved)
        camera.camera_error.connect(lambda msg: print(f"📷 Camera error: {msg}"))
        camera.camera_opened.connect(lambda: print("📷 Camera ready"))
        camera.start()

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        print("\n\nShutting down...")
        reader.stop()
        if camera:
            camera.stop()
            camera.wait(3000)
        reader.wait(3000)
        app.quit()

    signal.signal(signal.SIGINT, signal_handler)

    # Start the reader thread
    reader.start()

    # Process Qt events (needed for signals to work)
    # Use a timer to check for SIGINT
    from PyQt6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(lambda: None)  # Keep event loop alive
    timer.start(100)

    sys.exit(app.exec())


def main():
    parser = argparse.ArgumentParser(
        description="IronSight Golf Simulator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mock", dest="mode", action="store_const", const="mock",
        help="Use mock swing simulator (no hardware needed)",
    )
    mode_group.add_argument(
        "--usb", dest="mode", action="store_const", const="usb",
        help="Force USB connection to OptiShot 2",
    )
    parser.set_defaults(mode="auto")

    # Mock options
    parser.add_argument(
        "--preset", type=str, default="consistent_player",
        choices=["consistent_player", "beginner", "slicer", "hooker", "tour_pro"],
        help="Player preset for mock mode (default: consistent_player)",
    )
    parser.add_argument(
        "--interval-min", type=float, default=3.0,
        help="Minimum seconds between mock swings (default: 3.0)",
    )
    parser.add_argument(
        "--interval-max", type=float, default=8.0,
        help="Maximum seconds between mock swings (default: 8.0)",
    )

    # Club selection
    parser.add_argument(
        "--club", type=str, default="7-Iron",
        help="Initial club selection (default: 7-Iron)",
    )

    # Camera
    parser.add_argument(
        "--camera", action="store_true",
        help="Enable webcam capture (Phase 2+)",
    )

    # GUI
    parser.add_argument(
        "--gui", action="store_true",
        help="Launch full GUI (Phase 4+)",
    )

    # Verbosity
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.gui:
        # Phase 4+: launch GUI
        try:
            from src.main_window import launch_gui
            launch_gui(args)
        except ImportError:
            print("GUI not yet implemented. Use CLI mode for now.")
            print("Run without --gui flag.")
            sys.exit(1)
    else:
        run_cli(args)


if __name__ == "__main__":
    main()
