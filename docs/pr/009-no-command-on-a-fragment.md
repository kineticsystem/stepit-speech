# No Command on a Fragment

## Goal

A command that runs without confirmation, the stop command or a query, must not run on a fragment. On the rig, "Three centimeter.", said to correct the read-back "Moving closer 20 millimetres", made the LLM call `stop`; earlier, half sentences such as "Can you" called `report_status`. Nothing reads such a command back, so nothing caught the guess.

## Decisions

**The bridge checks, not the LLM.** A command with `confirm: false` runs only when the user's last words share a word with it: a word of its name or of its examples, or a stop phrase for the stop command. Otherwise the LLM is told it was not asked for, and asks the user what they want. It is safety rule 15, in `safety/asked.py`.

**The examples are the words.** The robot file already lists what a user says for each command, to teach the LLM; the same lists now say what asks for a command. To let "what's happening" ask for `report_status`, we add it as an example.

**Common words do not count.** "What", "is", "the" and the like are in every question: "what is the rig doing" asks for `report_status` with "rig" and "doing", not with "what". A plural counts as its singular, "stacks" as "stack".

**A stop the LLM calls needs a stop word.** The bridge already stops on any stop phrase, at once, without the LLM. A stop the LLM calls with none of them was a guess, as "Three centimeter." was. A stop missed by the LLM costs nothing, as the stop phrases catch every real stop.

**The LLM is also told why.** The bridge cancels a command waiting for its yes when we say anything else; the instructions said so, and the model read it as a reason to call stop. They now say that the system cancels it, never a command, and that a few words that only give a value complete the last command.

**Sleep is left as it is.** Going to sleep is read back and confirmed, so a guess is caught there.

## Left Out

**A check of the robot file.** An example of a command with `confirm: false` made only of common words, e.g. "what is it", would ask for nothing. `voicebridge check` does not say so yet; a test checks StepIt Macro's examples.

## Open Items

- Bonsai still fills in a value from an earlier turn: "Move closer." became 20 millimetres. The read-back catches it.
