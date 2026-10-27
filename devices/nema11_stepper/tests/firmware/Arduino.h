// Host-only Arduino substitutes. Never included in an Arduino build.
#pragma once
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <sstream>
#include <string>

constexpr int LOW = 0, HIGH = 1, OUTPUT = 1, INPUT_PULLUP = 2, PCIE2 = 2;
#define _BV(bit) (1 << (bit))
#define ISR(vector) void vector()
inline uint8_t PIND = 0, PCMSK2 = 0, PCICR = 0;
inline bool interruptsEnabled = true;
inline void noInterrupts() { interruptsEnabled = false; }
inline void interrupts() { interruptsEnabled = true; }
inline void pinMode(int, int) {}
inline void delay(unsigned long) {}
inline void delayMicroseconds(unsigned int) {}
inline void onDigitalWrite(int pin, int value);
inline void digitalWrite(int pin, int value) { onDigitalWrite(pin, value); }

class FakeSerial {
public:
  unsigned long baud = 0;
  std::string input;
  std::ostringstream output;
  void begin(unsigned long value) { baud = value; }
  int available() { return static_cast<int>(input.size()); }
  size_t readBytesUntil(char terminator, char *buffer, size_t length) {
    size_t used = 0;
    while (!input.empty() && used < length) {
      char value = input.front(); input.erase(0, 1);
      if (value == terminator) break;
      buffer[used++] = value;
    }
    return used;
  }
  template<class T> void print(const T &value) { output << value; }
  template<class T> void println(const T &value) { output << value << '\n'; }
  void println(double value, int digits) { output << std::fixed << std::setprecision(digits) << value << '\n'; }
};
inline FakeSerial Serial;
