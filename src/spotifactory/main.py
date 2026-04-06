import argparse


def _is_raspberry_pi() -> bool:
    try:
        with open("/proc/device-tree/model") as f:
            return "Raspberry Pi" in f.read()
    except FileNotFoundError:
        return False


def main():
    parser = argparse.ArgumentParser(description="Spotifactory")
    parser.add_argument(
        "--sim",
        action="store_true",
        help="Run in simulator mode (default on non-Pi hardware)",
    )
    args = parser.parse_args()

    if args.sim or not _is_raspberry_pi():
        from spotifactory.menu.simulated_menu import main as run_sim
        run_sim()
    else:
        from spotifactory.menu.run_on_pi import main as run_pi
        run_pi()


if __name__ == "__main__":
    main()
