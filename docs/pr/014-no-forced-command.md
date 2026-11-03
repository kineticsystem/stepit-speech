# No Forced Command

## Goal

When the model said in words that the robot was acting, the proxy asked again with the commands only: the schema left the model no reply, so it had to call one. On the rig it called commands nobody asked for:

- after an echo of the robot's own "The stack is finished.", heard as "The stack.", the model said "The stack is running.", and forced, proposed a new stack; we said no;
- "What setting do you want to change?" was taken for an action because of "setting", and forced, the model called `report_status`, which rule 15 refused;
- after a stop, "Done." forced a second `stop`.

And the model refused to start the live view, "The live view is already on.", after a test shot had turned it off.

## Decisions

**Asked again, never forced.** A reply that pretends is asked again once, with the reply and a turn that says why it was refused; the schema still allows a reply. The model may call the command it meant, or reply without pretending. If it pretends again, the voice says "Sorry, I did not get that as a command. Please say it again." Replayed through the proxy, ten times, the echoed "The stack." proposed a stack 2 times instead of 5.

**The correction is a user turn, from the system.** It starts with "[System]": a chat template may refuse a system message after the first.

**A verb counts where it acts.** "Setting" is the first word of a read-back, "Setting ISO 400.", and also a noun. A verb of the robot now pretends only first in a sentence, or after "is", "now", "I'm" and the like: "The stack is running." pretends, "Which setting?" does not. "Done", "turning" and the words of falling asleep still count anywhere.

**The model never knows the robot's state.** A new instruction: the lights, the live view and the camera change without the model, so it never refuses a command because it thinks it is already done. Replayed after a test shot, "Can you switch the live view on?" called `live_view` ten times in ten.

## Left Out

**The echo.** Through the laptop's speakers, the robot hears itself. Without a forced command, an echo proposes a stack less often, but still sometimes; the read-back catches it. A headset, the clip-on microphone or an echo filter in the bridge removes the cause.

**"Started", "finished".** A reply in the past tense, "I have started the focus stack.", uses no verb of a read-back and is not caught. It runs nothing.
