// Standalone ZMeter three-motor controller. Absolute FULL-STEP coordinates.
// No homing, zeroing, startup motion or automatic calibration.
#include <Stepper.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

// ---- Setup-specific configuration: review before uploading ----
constexpr uint8_t PINS[3][4] = {{2,3,4,5}, {6,7,8,9}, {10,11,12,13}};
constexpr int STEPS_PER_REV[3] = {2048,2048,2048};
constexpr long INITIAL_RPM[3] = {12,7,7};
constexpr long MAX_RPM[3] = {12,12,12}; // Configured ceiling, NOT detected safe speed.
constexpr int DIRECTION[3] = {1,1,1};  // Use -1 to reverse a motor's logical sign.
constexpr bool RELEASE_AFTER_MOVE[3] = {true,true,true}; // Matches supplied sketch.
// --------------------------------------------------------------
static_assert(STEPS_PER_REV[0] > 0 && STEPS_PER_REV[1] > 0 && STEPS_PER_REV[2] > 0, "Positive step counts required");
static_assert(STEPS_PER_REV[0] <= 32767 && STEPS_PER_REV[1] <= 32767 && STEPS_PER_REV[2] <= 32767, "Stepper library int limit");
static_assert((DIRECTION[0] == 1 || DIRECTION[0] == -1) && (DIRECTION[1] == 1 || DIRECTION[1] == -1)
              && (DIRECTION[2] == 1 || DIRECTION[2] == -1), "Directions must be +/-1");
static_assert(INITIAL_RPM[0] > 0 && INITIAL_RPM[0] <= MAX_RPM[0] && MAX_RPM[0] <= 1000
              && INITIAL_RPM[1] > 0 && INITIAL_RPM[1] <= MAX_RPM[1] && MAX_RPM[1] <= 1000
              && INITIAL_RPM[2] > 0 && INITIAL_RPM[2] <= MAX_RPM[2] && MAX_RPM[2] <= 1000, "Review RPM settings");

// Intentional IN1, IN3, IN2, IN4 order for the supplied 28BYJ-48/ULN2003 wiring.
Stepper motors[3] = {
  Stepper(STEPS_PER_REV[0], PINS[0][0], PINS[0][2], PINS[0][1], PINS[0][3]),
  Stepper(STEPS_PER_REV[1], PINS[1][0], PINS[1][2], PINS[1][1], PINS[1][3]),
  Stepper(STEPS_PER_REV[2], PINS[2][0], PINS[2][2], PINS[2][1], PINS[2][3])
};
int32_t positions[3] = {0,0,0};
long speeds[3] = {INITIAL_RPM[0], INITIAL_RPM[1], INITIAL_RPM[2]};

void releaseCoils(int axis)
{
  for (int pin = 0; pin < 4; ++pin) digitalWrite(PINS[axis][pin], LOW);
}

void reply(const char *prefix, int axis, long value)
{
  Serial.print(prefix);
  Serial.print(' ');
  Serial.print((char)('A' + axis));
  Serial.print(' ');
  Serial.println(value);
}

bool parseInteger(const char *text, int32_t &value)
{
  if (!text || !*text) return false;
  // Restrict length before strtol, whose overflow behavior varies by platform.
  const char *digit = text;
  if (*digit == '+' || *digit == '-') ++digit;
  if (!*digit || strlen(digit) > 10) return false;
  for (const char *p = digit; *p; ++p) if (*p < '0' || *p > '9') return false;
  // Parse magnitude without signed overflow, including AVR's 32-bit long.
  uint32_t magnitude = 0;
  for (const char *p = digit; *p; ++p) {
    uint32_t next = (uint32_t)(*p - '0');
    if (magnitude > (2147483647UL - next) / 10UL) return false;
    magnitude = magnitude * 10UL + next;
  }
  value = text[0] == '-' ? -(int32_t)magnitude : (int32_t)magnitude;
  return true;
}

void moveAbsolute(int axis, int32_t target)
{
  int sign = target > positions[axis] ? 1 : -1;
  bool moved = target != positions[axis];
  while (positions[axis] != target) {
    motors[axis].step(sign * DIRECTION[axis]);
    positions[axis] += sign;
  }
  if (moved && RELEASE_AFTER_MOVE[axis]) releaseCoils(axis);
}

void handleCommand(char *command)
{
  const char *delimiters = " \t\r";
  char *verb = strtok(command, delimiters);
  if (!verb) return;
  char *axisText = strtok(NULL, delimiters);
  if (strcmp(verb, "PING") == 0 && !axisText) {
    Serial.println("OK STEPPERS 1");
    return;
  }
  if (!axisText || strlen(axisText) != 1 || axisText[0] < 'A' || axisText[0] > 'C') {
    Serial.println("ERR Expected motor A B or C");
    return;
  }
  int axis = axisText[0] - 'A';
  char *argument = strtok(NULL, delimiters);
  char *extra = strtok(NULL, delimiters);
  if (extra) {
    Serial.println("ERR Extra argument");
    return;
  }
  if (strcmp(verb, "GET_POS") == 0 && !argument) {
    reply("POS", axis, positions[axis]);
  } else if (strcmp(verb, "GET_CONFIG") == 0 && !argument) {
    Serial.print("CFG "); Serial.print((char)('A' + axis)); Serial.print(' ');
    Serial.print(STEPS_PER_REV[axis]); Serial.print(' ');
    Serial.print(speeds[axis]); Serial.print(' '); Serial.println(MAX_RPM[axis]);
  } else if (strcmp(verb, "MOVE_ABS") == 0 || strcmp(verb, "SET_SPEED") == 0) {
    int32_t value;
    if (!parseInteger(argument, value)) {
      Serial.println("ERR Expected signed integer");
      return;
    }
    if (strcmp(verb, "MOVE_ABS") == 0) {
      moveAbsolute(axis, value);
      reply("OK", axis, positions[axis]); // Only after completion.
    } else {
      if (value < 1 || value > MAX_RPM[axis]) {
        Serial.println("ERR RPM outside configured range");
        return;
      }
      motors[axis].setSpeed(value);
      speeds[axis] = value;
      reply("SPEED", axis, value);
    }
  } else Serial.println("ERR Unknown command");
}

void setup()
{
  for (int axis = 0; axis < 3; ++axis) {
    releaseCoils(axis);
    motors[axis].setSpeed(speeds[axis]);
  }
  Serial.begin(115200);
  Serial.println("READY");
}

void loop()
{
  static char buffer[64];
  static size_t used = 0;
  static bool overflow = false;
  while (Serial.available() > 0) {
    char value = (char)Serial.read();
    if (value == '\n') {
      if (overflow) Serial.println("ERR Command too long");
      else { buffer[used] = '\0'; handleCommand(buffer); }
      used = 0; overflow = false;
    } else if (value == '\0') overflow = true;
    else if (used < sizeof(buffer) - 1 && !overflow) buffer[used++] = value;
    else overflow = true;
  }
}
