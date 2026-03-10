// Simple Arduino Nano control for CL42T stepper driver
// STEP -> PUL+
// DIR  -> DIR+
// PUL-, DIR- -> Arduino GND
//
// Serial commands:
//   AS <steps>   -> move to absolute position in steps
//   RS <steps>   -> move relative steps
//   AD <deg>     -> move to absolute position in degrees
//   RD <deg>     -> move relative degrees
//   V <us>       -> set delayMicroseconds between steps
//   P            -> print status
//   Z            -> zero current position
//
// Example:
//   AS 1600
//   RS -800
//   AD 90
//   RD -180
//   V 300
//   P
//   Z

const int STEP_PIN = 2;
const int DIR_PIN  = 3;

const long STEPS_PER_REV = 6400;   // change to match your microstep setting

unsigned int stepDelayUs = 500;    // can be changed from Serial

long currentPositionSteps = 0;     // commanded position
bool currentDirectionCW = true;    // last commanded direction

void pulseStep()
{
  digitalWrite(STEP_PIN, HIGH);
  delayMicroseconds(stepDelayUs);
  digitalWrite(STEP_PIN, LOW);
  delayMicroseconds(stepDelayUs);
}

void setDirection(bool cw)
{
  currentDirectionCW = cw;
  digitalWrite(DIR_PIN, cw ? HIGH : LOW);
  delayMicroseconds(10); // small setup time
}

void moveRelativeSteps(long deltaSteps)
{
  if (deltaSteps == 0) return;

  if (deltaSteps > 0)
  {
    setDirection(true);
    for (long i = 0; i < deltaSteps; i++)
    {
      pulseStep();
    }
  }
  else
  {
    setDirection(false);
    for (long i = 0; i < -deltaSteps; i++)
    {
      pulseStep();
    }
  }

  currentPositionSteps += deltaSteps;
}

void moveAbsoluteSteps(long targetSteps)
{
  long delta = targetSteps - currentPositionSteps;
  moveRelativeSteps(delta);
}

long degreesToSteps(float deg)
{
  return lround(deg * STEPS_PER_REV / 360.0);
}

float stepsToDegrees(long steps)
{
  return steps * 360.0 / STEPS_PER_REV;
}

void moveRelativeDegrees(float deltaDeg)
{
  long deltaSteps = degreesToSteps(deltaDeg);
  moveRelativeSteps(deltaSteps);
}

void moveAbsoluteDegrees(float targetDeg)
{
  long targetSteps = degreesToSteps(targetDeg);
  moveAbsoluteSteps(targetSteps);
}

void printStatus()
{
  Serial.println("----- Status -----");
  Serial.print("Current position (steps): ");
  Serial.println(currentPositionSteps);
  Serial.print("Current position (deg): ");
  Serial.println(stepsToDegrees(currentPositionSteps), 3);
  Serial.print("Current direction: ");
  Serial.println(currentDirectionCW ? "CW" : "CCW");
  Serial.print("Delay between step edges (us): ");
  Serial.println(stepDelayUs);
  Serial.println("------------------");
}

String readCommandLine()
{
  String cmd = "";
  while (Serial.available())
  {
    char c = Serial.read();
    if (c == '\n' || c == '\r')
    {
      if (cmd.length() > 0) break;
    }
    else
    {
      cmd += c;
    }
  }
  return cmd;
}

void handleCommand(String cmd)
{
  cmd.trim();
  if (cmd.length() == 0) return;

  if (cmd == "P")
  {
    printStatus();
    return;
  }

  if (cmd == "Z")
  {
    currentPositionSteps = 0;
    Serial.println("Position reset to zero.");
    return;
  }

  if (cmd.startsWith("AS "))
  {
    long value = cmd.substring(3).toInt();
    moveAbsoluteSteps(value);
    Serial.println("Done: absolute steps move.");
    printStatus();
    return;
  }

  if (cmd.startsWith("RS "))
  {
    long value = cmd.substring(3).toInt();
    moveRelativeSteps(value);
    Serial.println("Done: relative steps move.");
    printStatus();
    return;
  }

  if (cmd.startsWith("AD "))
  {
    float value = cmd.substring(3).toFloat();
    moveAbsoluteDegrees(value);
    Serial.println("Done: absolute degree move.");
    printStatus();
    return;
  }

  if (cmd.startsWith("RD "))
  {
    float value = cmd.substring(3).toFloat();
    moveRelativeDegrees(value);
    Serial.println("Done: relative degree move.");
    printStatus();
    return;
  }

  if (cmd.startsWith("V "))
  {
    int value = cmd.substring(2).toInt();
    if (value > 0)
    {
      stepDelayUs = (unsigned int)value;
      Serial.print("New delayMicroseconds: ");
      Serial.println(stepDelayUs);
    }
    else
    {
      Serial.println("Invalid delay value.");
    }
    return;
  }

  Serial.println("Unknown command.");
  Serial.println("Use:");
  Serial.println("  AS <steps>");
  Serial.println("  RS <steps>");
  Serial.println("  AD <deg>");
  Serial.println("  RD <deg>");
  Serial.println("  V <us>");
  Serial.println("  P");
  Serial.println("  Z");
}

void setup()
{
  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);

  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, LOW);

  Serial.begin(115200);
  delay(1000);

  Serial.println("Stepper control ready.");
  Serial.println("Commands:");
  Serial.println("  AS <steps>   -> absolute position in steps");
  Serial.println("  RS <steps>   -> relative move in steps");
  Serial.println("  AD <deg>     -> absolute position in degrees");
  Serial.println("  RD <deg>     -> relative move in degrees");
  Serial.println("  V <us>       -> set delayMicroseconds between steps");
  Serial.println("  P            -> print status");
  Serial.println("  Z            -> zero current position");
  printStatus();
}

void loop()
{
  if (Serial.available())
  {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();  // remove \r or spaces
    handleCommand(cmd);
  }
}