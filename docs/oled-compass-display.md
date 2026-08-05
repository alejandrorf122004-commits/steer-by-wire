# OLED compass display

This small screen module is the bench-test view for the steering encoder.

## What it shows

- A large arrow indicator
- The current angle in degrees
- A tiny fault label only when the magnet is missing or misread

## Intended use

The script can run in three ways:

- `live` mode: reads the AS5600 over I2C and updates the arrow in real time
- `demo` mode: sweeps through a set of angles for screen checks
- `--angle` mode: shows a fixed angle for calibration or visual inspection

## Example

```bash
python3 tools/oled_compass.py
python3 tools/oled_compass.py --demo
python3 tools/oled_compass.py --angle 123.4
```

## Notes

- The OLED stays on I2C address `0x3C`.
- The AS5600 stays on I2C address `0x36`.
- The display code is separated from the sensor code so the AS5600 can be added
  without rewriting the screen logic.
