// Arduino Nano stepper bridge for the autofocus Z motor.
// Motor: NEMA 11 closed-loop stepper with 1000 PPR (4000 CPR) encoder.
// Driver: closed-loop STEP/DIR driver (CL42T V4.1). See ../../README.md.
//
// STEP -> PUL+
// DIR  -> DIR+
// PUL-, DIR- -> Arduino GND
// Encoder EA+ -> ENC_A_PIN, EB+ -> ENC_B_PIN, encoder EGND -> Arduino GND
// (read-only tap; the encoder stays plugged into the driver)
//
// Command protocol used by devices/nema11_stepper/nema11_hardware.py:
//   PING
//   MOVE_ABS <deg>
//   MOVE_REL <deg>
//   GET_POS        encoder (real) position
//   GET_CMD        commanded position
//   ZERO
//   HOME
//
// Responses:
//   READY
//   OK NEMA11 1
//   OK <encoder_position_deg>
//   POS <encoder_position_deg>
//   CMD <commanded_position_deg>
//   ERR <message>
//
// CW is hard-coded as the positive angle direction.

#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#if defined(ARDUINO) && !defined(__AVR_ATmega328P__)
#error "Encoder pin-change interrupt assumes an ATmega328P board (Nano/Uno)"
#endif

const int STEP_PIN = 2;
const int DIR_PIN = 3;
// Encoder pins must be D4..D7 (port D, pin-change interrupt group 2).
const int ENC_A_PIN = 4;
const int ENC_B_PIN = 5;

const long STEPS_PER_REV = 6400;      // Set this to your driver microstep value.
const unsigned int STEP_DELAY_US = 500;
const uint8_t CW_POSITIVE_DIR_LEVEL = HIGH;
const uint8_t CCW_NEGATIVE_DIR_LEVEL = LOW;

const long ENCODER_COUNTS_PER_REV = 4000;  // 1000 PPR x4 quadrature.
const int ENCODER_SIGN = 1;                // Use -1 if GET_POS runs opposite to MOVE.
const unsigned int SETTLE_MS = 20;         // Closed-loop follow time before replying.

long currentPositionSteps = 0;
volatile long encoderCount = 0;
volatile uint8_t encoderState = 0;

uint8_t readEncoderPins()
{
  return ((PIND >> ENC_A_PIN) & 1) | (((PIND >> ENC_B_PIN) & 1) << 1);
}

ISR(PCINT2_vect)
{
  // Index: previous state (B,A) << 2 | current state (B,A).
  static const int8_t QUADRATURE[16] = {0, 1, -1, 0, -1, 0, 0, 1, 1, 0, 0, -1, 0, -1, 1, 0};
  uint8_t state = readEncoderPins();
  encoderCount += QUADRATURE[(encoderState << 2) | state];
  encoderState = state;
}

long readEncoderCount()
{
  noInterrupts();
  long count = encoderCount;
  interrupts();
  return count;
}

void pulseStep()
{
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(STEP_DELAY_US);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(STEP_DELAY_US);
}

void setPositiveDirection(bool positiveDirection)
{
  digitalWrite(
    DIR_PIN,
    positiveDirection ? CW_POSITIVE_DIR_LEVEL : CCW_NEGATIVE_DIR_LEVEL
  );
  delayMicroseconds(10);
}

long degreesToSteps(float degrees)
{
  return lround(degrees * STEPS_PER_REV / 360.0);
}

float stepsToDegrees(long steps)
{
  return steps * 360.0 / STEPS_PER_REV;
}

float encoderDegrees()
{
  return ENCODER_SIGN * readEncoderCount() * 360.0 / ENCODER_COUNTS_PER_REV;
}

void moveRelativeSteps(long deltaSteps)
{
  if (deltaSteps == 0)
  {
    return;
  }

  bool positiveDirection = (deltaSteps > 0);
  long stepCount = positiveDirection ? deltaSteps : -deltaSteps;

  setPositiveDirection(positiveDirection);
  for (long i = 0; i < stepCount; ++i)
  {
    pulseStep();
  }

  currentPositionSteps += deltaSteps;
  delay(SETTLE_MS);
}

void moveAbsoluteDegrees(float targetDegrees)
{
  long targetSteps = degreesToSteps(targetDegrees);
  moveRelativeSteps(targetSteps - currentPositionSteps);
}

void moveRelativeDegrees(float deltaDegrees)
{
  moveRelativeSteps(degreesToSteps(deltaDegrees));
}

void sendPosition(const char *prefix, float degrees)
{
  Serial.print(prefix);
  Serial.print(' ');
  Serial.println(degrees, 6);
}

void sendCurrentPosition(const char *prefix)
{
  sendPosition(prefix, encoderDegrees());
}

void trimTrailingWhitespace(char *buffer)
{
  int length = strlen(buffer);
  while (length > 0 && isspace(buffer[length - 1]))
  {
    buffer[length - 1] = '\0';
    --length;
  }
}

bool startsWith(const char *text, const char *prefix)
{
  return strncmp(text, prefix, strlen(prefix)) == 0;
}

void handleCommand(char *command)
{
  while (*command != '\0' && isspace(*command))
  {
    ++command;
  }

  if (*command == '\0')
  {
    return;
  }

  if (strcmp(command, "PING") == 0)
  {
    Serial.println("OK NEMA11 1");
    return;
  }

  if (strcmp(command, "GET_POS") == 0)
  {
    sendCurrentPosition("POS");
    return;
  }

  if (strcmp(command, "GET_CMD") == 0)
  {
    sendPosition("CMD", stepsToDegrees(currentPositionSteps));
    return;
  }

  if (strcmp(command, "ZERO") == 0)
  {
    currentPositionSteps = 0;
    noInterrupts();
    encoderCount = 0;
    interrupts();
    sendCurrentPosition("OK");
    return;
  }

  if (strcmp(command, "HOME") == 0)
  {
    moveAbsoluteDegrees(0.0);
    sendCurrentPosition("OK");
    return;
  }

  if (startsWith(command, "MOVE_ABS "))
  {
    float targetDegrees = atof(command + 9);
    moveAbsoluteDegrees(targetDegrees);
    sendCurrentPosition("OK");
    return;
  }

  if (startsWith(command, "MOVE_REL "))
  {
    float deltaDegrees = atof(command + 9);
    moveRelativeDegrees(deltaDegrees);
    sendCurrentPosition("OK");
    return;
  }

  Serial.println("ERR Unknown command");
}

void setup()
{
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  pinMode(ENC_A_PIN, INPUT_PULLUP);
  pinMode(ENC_B_PIN, INPUT_PULLUP);

  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, CCW_NEGATIVE_DIR_LEVEL);

  encoderState = readEncoderPins();
  PCMSK2 |= _BV(ENC_A_PIN) | _BV(ENC_B_PIN);  // PCINT16..23 map to D0..D7.
  PCICR |= _BV(PCIE2);

  Serial.begin(115200);
  delay(1000);
  Serial.println("READY");
}

void loop()
{
  static char commandBuffer[48];

  if (!Serial.available())
  {
    return;
  }

  size_t length = Serial.readBytesUntil('\n', commandBuffer, sizeof(commandBuffer) - 1);
  commandBuffer[length] = '\0';
  trimTrailingWhitespace(commandBuffer);
  handleCommand(commandBuffer);
}
