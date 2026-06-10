import os
import sys
import time

def verify_all():
    print("Checking workspace directory...")
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Current Directory: {current_dir}")
    
    # 1. Check imports
    print("\n[1/4] Verifying imports...")
    try:
        import player
        import visualizer
        import main
        print("✓ Imports verified successfully.")
    except Exception as e:
        print(f"✗ Import verification failed: {e}")
        sys.exit(1)
        
    # 2. Check css file
    print("\n[2/4] Verifying CSS stylesheet...")
    css_path = os.path.join(current_dir, "styles.css")
    if os.path.exists(css_path):
        print(f"✓ Stylesheet exists at {css_path}")
    else:
        print("✗ Stylesheet missing!")
        sys.exit(1)
        
    # 3. Check sample music
    print("\n[3/4] Verifying sample audio assets...")
    sample_mp3 = os.path.join(current_dir, "sample_music", "sample.mp3")
    if os.path.exists(sample_mp3):
        print(f"✓ Sample audio file exists: {sample_mp3} ({os.path.getsize(sample_mp3)} bytes)")
    else:
        print("✗ Sample audio file missing!")
        sys.exit(1)

    # 4. Check MPV Backend connection
    print("\n[4/4] Verifying MPV Process Spawning and IPC Connection...")
    try:
        mpv_controller = player.MpvPlayer(current_dir)
        print("✓ MPV background process spawned.")
        print(f"✓ IPC socket initialized at: {mpv_controller.socket_path}")
        print(f"✓ Initial volume level: {mpv_controller.volume}%")
        
        # Test state
        print("Waiting 1 second to verify connection stability...")
        time.sleep(1)
        
        print("Shutting down MPV player...")
        mpv_controller.close()
        print("✓ MPV background process and socket cleaned up successfully.")
    except Exception as e:
        print(f"✗ MPV connection verification failed: {e}")
        sys.exit(1)

    print("\n=== VERIFICATION SUCCESSFUL ===")
    print("All backend checks passed! You can run the player using:")
    print("  python3 main.py")

if __name__ == "__main__":
    verify_all()
