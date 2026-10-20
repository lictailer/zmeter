// Runs the real sketch against a fake closed-loop motor whose encoder drives PIND.
#include <cassert>
#include <iostream>
#include "Arduino.h"
void PCINT2_vect();
#include "../../arduino/nema11_stepper/nema11_stepper.ino"

long motorSteps = 0, encoderPhase = 0, pulses = 0;
int dirLevel = LOW;
bool encoderFollows = true;
int encoderWiring = 1;  // -1 simulates A/B swapped relative to motor direction.
const uint8_t GRAY[4] = {0, 1, 3, 2};  // (B,A) quadrature sequence.

void driveEncoder()
{
  long target = encoderWiring * (long)std::floor(motorSteps * (double)ENCODER_COUNTS_PER_REV / STEPS_PER_REV);
  while (encoderFollows && encoderPhase != target) {
    encoderPhase += encoderPhase < target ? 1 : -1;
    uint8_t state = GRAY[((encoderPhase % 4) + 4) % 4];
    PIND = (uint8_t)((PIND & ~0x30) | ((state & 1) << ENC_A_PIN) | (((state >> 1) & 1) << ENC_B_PIN));
    PCINT2_vect();
  }
}

void onDigitalWrite(int pin, int value)
{
  if (pin == DIR_PIN) dirLevel = value;
  if (pin == STEP_PIN && value == HIGH) {
    ++pulses;
    motorSteps += dirLevel == CW_POSITIVE_DIR_LEVEL ? 1 : -1;
    driveEncoder();
  }
}

std::string send(const std::string &command)
{
  Serial.output.str(""); Serial.output.clear(); Serial.input += command;
  while (Serial.available()) loop();
  return Serial.output.str();
}

double reply(const std::string &text, const std::string &prefix)
{
  assert(text.rfind(prefix + " ", 0) == 0);
  return std::stod(text.substr(prefix.size() + 1));
}

int main()
{
  setup();
  assert(Serial.output.str() == "READY\n");
  assert(Serial.baud == 115200);
  assert(PCICR & _BV(PCIE2));
  assert(PCMSK2 == (_BV(4) | _BV(5)));
  assert(send("PING\n") == "OK NEMA11 1\n");
  assert(send("GET_POS\n") == "POS 0.000000\n");

  assert(std::abs(reply(send("MOVE_ABS 90\n"), "OK") - 90.0) < 0.1);
  assert(motorSteps == 1600 && pulses == 1600);
  assert(std::abs(reply(send("GET_POS\n"), "POS") - 90.0) < 0.1);
  assert(send("GET_CMD\n") == "CMD 90.000000\n");
  assert(std::abs(reply(send("MOVE_ABS -45.5\n"), "OK") + 45.5) < 0.1);
  assert(std::abs(reply(send("MOVE_REL 10\n"), "OK") + 35.5) < 0.1);
  long before = pulses;
  assert(std::abs(reply(send("MOVE_ABS -35.5\n"), "OK") + 35.5) < 0.1);
  assert(pulses == before);

  // Encoder reports the real shaft: a stalled motor shows up as a position mismatch.
  encoderFollows = false;
  assert(std::abs(reply(send("MOVE_ABS 0\n"), "OK") + 35.5) < 0.1);
  assert(send("GET_CMD\n") == "CMD 0.000000\n");
  encoderFollows = true;
  driveEncoder();
  assert(std::abs(reply(send("GET_POS\n"), "POS")) < 0.1);

  assert(std::abs(reply(send("MOVE_ABS 12\n"), "OK") - 12.0) < 0.1);
  assert(send("ZERO\n") == "OK 0.000000\n");
  assert(send("GET_CMD\n") == "CMD 0.000000\n");
  assert(std::abs(reply(send("MOVE_REL 5\n"), "OK") - 5.0) < 0.1);
  assert(std::abs(reply(send("HOME\n"), "OK")) < 0.1);
  assert(send("bogus\n") == "ERR Unknown command\n");
  assert(interruptsEnabled);
  std::cout << "Firmware contract passed (fake closed-loop motor, encoder and serial I/O)\n";
}
