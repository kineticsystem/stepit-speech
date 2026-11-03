# The Distance in the User's Unit

## Goal

Asked to move the camera "uh one centimetre" back, the voice read back "Moving farther 1 millimetre", three times in a row. Through the proxy, with the same turns before it, Bonsai turned that sentence into 1 millimetre 8 times in 20. "Two centimetres", "three centimetres" and "1 centimetre" in digits always came out right: the spoken "one" is what it got wrong. The pull requests of the day did not cause it: the instructions before #8 and before #9 do the same.

## Decisions

**The LLM copies, the robot file converts.** `move_camera` takes `distance` and `unit`, `millimetres` or `centimetres`, as the user said them. A `let` value, `millimetres`, converts them, and the request uses it. The model is good at copying a number and a word, and bad at arithmetic on a number it heard as a word. With the same sentence, it now gives 1 centimetre 20 times in 20.

**The read-back says the user's unit.** "Moving farther 1 centimetre. Confirm?" is what the user said, so they hear at once whether it is right. A read-back in millimetres asked them to convert while listening.

**The limit holds after the conversion.** `distance` keeps its range, 0.01 to 50, and a `require` refuses more than 50 millimetres once converted: "6 centimetres" is refused, as 60 millimetres was. No code of the bridge changes: `let` and `require` are checked before the read-back.

**No unit, no guess, most of the time.** "Move closer 5" now gets "Millimetres or centimetres?" 16 times in 20; the other 4 times the model gives millimetres, and the read-back says "5 millimetres".

**Rounded to the micrometre.** 0.3 centimetres times 10 is 3.0000000000000004 in floating point: the conversion rounds to 3 decimals.
