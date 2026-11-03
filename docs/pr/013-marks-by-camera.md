# The Marks Named by Where the Camera Is

## Goal

By voice, a stack ran from the camera close to the subject to the camera far from it: the other way round from every stack started in StepIt UI. The rotation fix of the day was not the cause. The marks were swapped.

The rig names the ends of a stack after the part of the subject in focus: the near end is the camera at its farthest from the subject, the front sharp; the far end is the camera at its closest, the back sharp. `FocusStack` runs from the near end to the far one. We said "mark the farther position" for the camera far back, and "the closer one" for the camera close, and the voice gave them the rig's names the other way round.

## Decisions

**The voice names the marks by where the camera is.** `mark` and `go_to_mark` take `closer` or `farther`: the closer mark is the camera close to the subject, the farther mark the camera far from it. That is how we say it, at the rig, looking at the camera. "Near" and "far" said alone mean the same as "closer" and "farther".

**The rig does not change.** The robot file turns the camera's names into the rig's: the closer mark runs `MarkFar` and goes to `far`, the farther mark runs `MarkNear` and goes to `near`. A stack still runs from the camera far away to close, as in StepIt UI, whose Mark buttons say neither "near" nor "far": the one above is the farther mark, the one below the closer one.

**Every sentence uses the camera's names.** "Marking the closer mark.", "Set the farther mark first.", "The closer mark is set, the farther one is not."

**The overshoot was never at risk.** `CommandJointPositions` takes the direction of every approach from the stack's first and last positions, and the overshoot is a distance: it does not depend on which way a motor counts.

**Measured.** Through the proxy, 10 times each, every phrase went to the mark meant: "Mark the closer one.", "mark the near end" and "this is the close point" to the closer mark; "Mark the farther position.", "Mark the further one." and "mark the far end" to the farther one; "go to the closer mark" and "go back to the far mark" to theirs.

## Left Out

**Checking the order of the marks before a stack.** The bridge could refuse a stack whose closer mark is not closer than its farther one, from their motor positions; that depends on which way the rail's motor counts, which changed today. Named by where the camera is, the marks are hard to swap by voice.
