#include <cassert>
#include <iostream>
#include "../../arduino/arduino_steppers/arduino_steppers.ino"

std::string send(const std::string &command)
{
  Serial.output.str(""); Serial.output.clear(); Serial.input += command;
  loop(); return Serial.output.str();
}

int main()
{
  setup();
  assert(Serial.output.str() == "READY\n");
  assert(Serial.baud == 115200);
  assert((motors[0].pins == std::array<int,4>{2,4,3,5}));
  assert((motors[1].pins == std::array<int,4>{6,8,7,9}));
  assert((motors[2].pins == std::array<int,4>{10,12,11,13}));
  for (int axis = 0; axis < 3; ++axis) assert(motors[axis].physicalSteps == 0);
  assert(send("PING\r\n") == "OK STEPPERS 1\n");
  assert(send("GET_CONFIG A\n") == "CFG A 2048 12 12\n");
  assert(send("GET_CONFIG B\n") == "CFG B 2048 7 12\n");
  assert(send("GET_POS C\n") == "POS C 0\n");
  assert(send("MOVE_ABS A 6\nMOVE_ABS B -3\nMOVE_ABS C 2\n") == "OK A 6\nOK B -3\nOK C 2\n");
  assert(motors[0].physicalSteps == 6 && motors[1].physicalSteps == -3 && motors[2].physicalSteps == 2);
  long calls = motors[0].calls;
  assert(send("MOVE_ABS A 6\n") == "OK A 6\n");
  assert(motors[0].calls == calls);
  assert(send("SET_SPEED B 4\nGET_CONFIG B\n") == "SPEED B 4\nCFG B 2048 4 12\n");
  assert(motors[1].speed == 4 && motors[1].physicalSteps == -3);
  for (const auto &bad : {"MOVE_ABS A 1.2\n", "MOVE_ABS A 1 garbage\n", "MOVE_ABS A 2147483648\n",
       "MOVE_ABS A -2147483648\n", "MOVE_ABS A nan\n", "MOVE_ABS A\n", "MOVE_ABS D 4\n",
       "HOME A\n", "ZERO A\n", "SET_SPEED B 0\n", "SET_SPEED B 13\n", "stepperA 1\n"}) {
    assert(send(bad).find("ERR ") == 0);
    assert(positions[0] == 6 && positions[1] == -3 && positions[2] == 2);
  }
  assert(send(std::string(80, 'x') + "\nPING\n") == "ERR Command too long\nOK STEPPERS 1\n");
  assert(send("MOVE_ABS C ").empty());
  assert(positions[2] == 2);
  assert(send("0\nGET_POS C\n") == "OK C 0\nPOS C 0\n");
  for (auto write : pinWrites) assert(write.second == LOW);
  std::cout << "Firmware contract passed (fake three-motor and serial I/O)\n";
}
