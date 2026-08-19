// Arduino Nano stepper bridge for the autofocus Z motor.
// STEP -> PUL+
// DIR  -> DIR+
// PUL-, DIR- -> Arduino GND
//
// Command protocol used by autofocusXZ_hardware.py:
//   PING
//   MOVE_ABS <deg>
//   MOVE_REL <deg>
//   GET_POS
//   ZERO
//   HOME
//
// Responses:
//   READY
//   OK PONG
//   OK <current_position_deg>
//   POS <current_position_deg>
//   ERR <message>
//
// CW is hard-coded as the positive angle direction.

#include <ctype.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

const int STEP_PIN = 2;
const int DIR_PIN = 3;

const long STEPS_PER_REV = 6400;      // Set this to your driver microstep value.
const unsigned int STEP_DELAY_US = 500;
const uint8_t CW_POSITIVE_DIR_LEVEL = HIGH;
const uint8_t CCW_NEGATIVE_DIR_LEVEL = LOW;

long currentPositionSteps = 0;

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

void sendCurrentPosition(const char *prefix)
{
  Serial.print(prefix);
  Serial.print(' ');
  Serial.println(stepsToDegrees(currentPositionSteps), 6);
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
    Serial.println("OK PONG");
    return;
  }

  if (strcmp(command, "GET_POS") == 0)
  {
    sendCurrentPosition("POS");
    return;
  }

  if (strcmp(command, "ZERO") == 0)
  {
    currentPositionSteps = 0;
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

  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, CCW_NEGATIVE_DIR_LEVEL);

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
