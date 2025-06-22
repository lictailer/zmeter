import sys
import time

import serial


def main() -> None:
    # Pick up command-line arguments (defaults shown)
    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 38400

    print(f"Opening {port} @ {baud} baud …")

    try:
        with serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=2.0,
            write_timeout=2.0,
        ) as ser:
            ser.reset_input_buffer()

            # Send the “ver” query (CR-LF line ending)
            cmd = "ver\r\n"
            ser.write(cmd.encode())
            print(f"Sent: {cmd.strip()}")

            # Give the controller a moment to respond
            time.sleep(0.5)

            reply = ser.read_all()
            if reply:
                print("Received (raw bytes):")
                print(reply)
                try:
                    print("Decoded text:")
                    print(reply.decode(errors='replace'))
                except Exception:
                    pass
            else:
                print("No reply within 2 s — try another baud rate or port.")

    except serial.SerialException as exc:
        print(f"Serial error: {exc}")


if __name__ == "__main__":
    main()