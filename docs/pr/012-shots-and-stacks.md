# A Shot, a Stack and a Full Stack

## Goal

On the rig, "Take a shot." and "Take another shot." were answered with "Do you want a focus stack or a single test shot?". The robot file said "a shoot" is a focus stack, and the model heard "a shot" in it. Replayed through the proxy after the turns of that session, "Take a shot." asked 4 times in 20.

We say three things, and the rig had two commands for them:

| We say | We mean |
|---|---|
| "a shot", "another shot" | a test shot |
| "a stack", "take a stack" | one focus stack, where the stage stands |
| "a full stack", "a stack session", "a 3D stack" | the full stack, at every angle of the plan |

## Decisions

**Two stack commands.** `start_full_stack` is the old `start_focus_stack`: every angle of the plan, turning the stage. `start_stack` shoots one stack where the stage stands, with the plan's shots and marks. Both need the near and the far mark.

**One stack is the same objective.** `FocusStack` takes its angles from where the stage stands, so one angle, from 0 to 0, does not turn it: `{shots: 10, stage_from: 0.0, stage_to: 0.0, angles: 1}`. Nothing changes on the rig.

**The read-backs tell them apart.** "Stacking 10 shots at this angle." against "Stacking 10 shots at 35 angles, plus or minus 17 degrees: 350 pictures.": a mix-up is heard before the yes.

**"A shoot" is gone.** It sounded like "a shot". The instructions now say that a shot is a test shot, never a stack.

**Measured.** Through the proxy, 10 times each: "take a shot" and "take another shot" gave a test shot, "take a stack" and "take one stack" one stack, "start a full stack", "start a stack session" and "do the full 3D stack" the full stack, every time. After the turns of the session, "Take a shot." gave a test shot 20 times in 20.

**"Start the focus stack" is one stack.** It says "a stack", not "a full stack".
