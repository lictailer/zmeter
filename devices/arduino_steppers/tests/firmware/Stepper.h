// Host-only Arduino/Stepper substitutes. Never included in an Arduino build.
#pragma once
#include <array>
#include <iomanip>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

constexpr int LOW = 0;
inline std::vector<std::pair<int, int>> pinWrites;
inline void digitalWrite(int pin, int value) { pinWrites.emplace_back(pin, value); }

class FakeSerial {
public:
  unsigned long baud = 0;
  std::string input;
  std::ostringstream output;
  void begin(unsigned long value) { baud = value; }
  int available() { return static_cast<int>(input.size()); }
  int read() { unsigned char value = input.front(); input.erase(0, 1); return value; }
  template<class T> void print(const T &value) { output << value; }
  template<class T> void println(const T &value) { output << value << '\n'; }
  void println(double value, int digits) { output << std::fixed << std::setprecision(digits) << value << '\n'; }
};
inline FakeSerial Serial;

class Stepper {
public:
  int stepsPerRevolution;
  std::array<int, 4> pins;
  long speed = 0;
  long physicalSteps = 0;
  long calls = 0;
  Stepper(int steps, int p1, int p2, int p3, int p4): stepsPerRevolution(steps), pins{p1,p2,p3,p4} {}
  void setSpeed(long rpm) { speed = rpm; }
  void step(int steps) { physicalSteps += steps; ++calls; }
};
