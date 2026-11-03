# StepIt Macro Voice Commands

<!-- Generated from robots/stepit-macro/robot.yaml by `voicebridge docs`: edit the robot file, not this document. -->

## Table of Contents <!-- omit in toc -->

- [Introduction](#introduction)
- [Confirming and Stopping](#confirming-and-stopping)
- [Sleeping and Waking](#sleeping-and-waking)
- [The Commands at a Glance](#the-commands-at-a-glance)
- [The Commands](#the-commands)
  - [rotate_stage](#rotate_stage)
  - [move_camera](#move_camera)
  - [go_to_mark](#go_to_mark)
  - [manual_drive](#manual_drive)
  - [stop](#stop)
  - [mark](#mark)
  - [set_stack](#set_stack)
  - [start_focus_stack](#start_focus_stack)
  - [describe_stack](#describe_stack)
  - [take_test_shot](#take_test_shot)
  - [set_camera](#set_camera)
  - [live_view](#live_view)
  - [lights](#lights)
  - [report_status](#report_status)
  - [report_progress](#report_progress)
  - [sleep](#sleep)

## Introduction

This document lists every command we can give StepIt Macro by voice, and what each one becomes. It is generated from the robot file `robots/stepit-macro/robot.yaml`: every example below is prepared by the bridge itself, so the sentence read back and the request sent to rosbridge are the real ones.

We do not have to say the examples word for word: the LLM understands other ways of saying the same thing, and the examples teach it the common ones. Whatever it understood, the bridge reads the command back before anything moves.

## Confirming and Stopping

A command that changes the robot is read back, and runs only once we confirm it:

- The read-back ends with "Confirm?" and waits 20 seconds for the answer.
- **Confirm** with an answer made only of: yes, yeah, yep, yup, ok, okay, confirm, confirmed, go, go ahead, go with it, do it, proceed, sure, affirmative, correct, that's correct, that's right.
- **Cancel** with: no, nope, cancel, don't, do not, negative, never mind, wait, wrong. Anything else we say also cancels the command, and is then heard as a new request.
- These words may come with an answer and change nothing: please, thanks, thank you, um, uh, oh, yes please.
- **Stop** with any of: stop, halt, abort, freeze, emergency, anywhere in what we say. The bridge runs `stop` at once, without the LLM and without a confirmation. A sentence that is more than a stop, e.g. "stop the live view", stops the robot and is then heard as a request.

> [!WARNING]
> The voice stop takes about a second, the time to hear the end of the sentence and transcribe it. It does not replace the stop of the gamepad or of the page.

## Sleeping and Waking

The voice can sleep, so that we talk to others without it hearing a command:

- **Sleep** with [`sleep`](#sleep), in our own words, e.g. "go to sleep". It is read back and confirmed like any command, and runs nothing on the robot. The voice says "Going to sleep. To wake me, say: Wake up."
- **Asleep**, it hears nothing but stop and the wake phrase: nothing reaches the LLM, and the voice stays silent. Stop still stops the robot.
- **Wake** it with exactly one of: "Wake up", "wakeup", as a sentence of its own, with nothing after it. The voice says "I'm listening."
- A session starts awake.

## The Commands at a Glance

| Command | What it does | Confirmed |
|---|---|---|
| [`rotate_stage`](#rotate_stage) | Turns the rotary stage, the turntable the subject stands on, by an angle. | yes |
| [`move_camera`](#move_camera) | Moves the camera along the rail, closer to the subject or farther from it, by a distance. | yes |
| [`go_to_mark`](#go_to_mark) | Moves the camera back to the near or the far mark of the focus stack, to check the focus there. | yes |
| [`manual_drive`](#manual_drive) | Enables teleoperation (on), so that the rig is driven by hand, with the gamepad or the sliders, or disables it (off), to take the rig back for the commands. | yes |
| [`stop`](#stop) | Stops whatever the rig is doing, at once. The rig also stops whenever the user says stop. | no, it runs at once |
| [`mark`](#mark) | Marks where the camera is now as the near or the far end of the focus stack: the near end is the closest part of the subject in focus, the far end the farthest. | yes |
| [`set_stack`](#set_stack) | Changes the plan of the focus stack: the shots from the near end to the far one, the angles of the stage, and how far the stage turns either way. Give only what changes. | yes |
| [`start_focus_stack`](#start_focus_stack) | Starts a focus stack with the plan and the marks the rig holds. | yes |
| [`describe_stack`](#describe_stack) | Says the plan of the focus stack and which ends are marked. Changes nothing. | no, it changes nothing |
| [`take_test_shot`](#take_test_shot) | Takes one test picture, to check the framing and the exposure. | yes |
| [`set_camera`](#set_camera) | Changes a setting of the camera. The value is as the camera writes it: an ISO such as 400 or Auto, a shutter speed such as 1/125 or 2, an aperture such as 8 or 5.6, an exposure compensation such as -1 or 0.3, a white balance such as Auto, Daylight or Cloudy. | yes |
| [`live_view`](#live_view) | Starts or stops the live view of the camera. | yes |
| [`lights`](#lights) | Switches the lights of the rig on or off. | yes |
| [`report_status`](#report_status) | Says what the rig is doing now. Changes nothing. | no, it changes nothing |
| [`report_progress`](#report_progress) | Says how far the running or the last focus stack is. Changes nothing. | no, it changes nothing |
| [`sleep`](#sleep) | Puts the voice to sleep: until the user says the wake phrase, it hears nothing but stop. It does not stop the robot. | yes |

## The Commands

### rotate_stage

Turns the rotary stage, the turntable the subject stands on, by an angle.

| Parameter | Values | Description |
|---|---|---|
| `degrees` | 0.1 to 360 | how far to turn, in degrees |
| `direction` | `clockwise`, `counter-clockwise` |  |

**"rotate the rig 10 degrees left"** becomes `rotate_stage(degrees: 10.0, direction: 'counter-clockwise')`.

- It reads back: "Rotating 10 degrees counter-clockwise. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "RotateStageBy",
      "payload": "{deg: -10.0}"
    }
  }
  ```

- When it is done: "Rotated 10 degrees counter-clockwise."

**"turn the stage clockwise by 5 degrees"** becomes `rotate_stage(degrees: 5.0, direction: 'clockwise')`.

- It reads back: "Rotating 5 degrees clockwise. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "RotateStageBy",
      "payload": "{deg: 5.0}"
    }
  }
  ```

- When it is done: "Rotated 5 degrees clockwise."

**"rotate the subject right 2.5 degrees"** becomes `rotate_stage(degrees: 2.5, direction: 'clockwise')`.

- It reads back: "Rotating 2.5 degrees clockwise. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "RotateStageBy",
      "payload": "{deg: 2.5}"
    }
  }
  ```

- When it is done: "Rotated 2.5 degrees clockwise."

### move_camera

Moves the camera along the rail, closer to the subject or farther from it, by a distance.

| Parameter | Values | Description |
|---|---|---|
| `millimetres` | 0.01 to 50 | how far to move, in millimetres |
| `direction` | `closer`, `farther` |  |

**"move the camera closer by 1 mm"** becomes `move_camera(millimetres: 1.0, direction: 'closer')`.

- It reads back: "Moving closer 1 millimetre. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MoveRailBy",
      "payload": "{mm: -1.0}"
    }
  }
  ```

- When it is done: "Moved closer 1 millimetre."

**"move the rail back half a millimetre"** becomes `move_camera(millimetres: 0.5, direction: 'farther')`.

- It reads back: "Moving farther 0.5 millimetres. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MoveRailBy",
      "payload": "{mm: 0.5}"
    }
  }
  ```

- When it is done: "Moved farther 0.5 millimetres."

**"focus 2 millimetres further away"** becomes `move_camera(millimetres: 2.0, direction: 'farther')`.

- It reads back: "Moving farther 2 millimetres. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MoveRailBy",
      "payload": "{mm: 2.0}"
    }
  }
  ```

- When it is done: "Moved farther 2 millimetres."

### go_to_mark

Moves the camera back to the near or the far mark of the focus stack, to check the focus there.

| Parameter | Values | Description |
|---|---|---|
| `mark` | `near`, `far` |  |

**"go to the near mark"** becomes `go_to_mark(mark: 'near')`.

- It reads back: "Going to the near mark. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MoveRailToMark",
      "payload": "{mark: near}"
    }
  }
  ```

- When it is done: "The camera is at the near mark."

**"move the camera back to the far end"** becomes `go_to_mark(mark: 'far')`.

- It reads back: "Going to the far mark. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MoveRailToMark",
      "payload": "{mark: far}"
    }
  }
  ```

- When it is done: "The camera is at the far mark."

### manual_drive

Enables teleoperation (on), so that the rig is driven by hand, with the gamepad or the sliders, or disables it (off), to take the rig back for the commands.

| Parameter | Values | Description |
|---|---|---|
| `state` | `on`, `off` |  |

**"enable teleoperation"** becomes `manual_drive(state: 'on')`.

- It reads back: "Enabling teleoperation. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "ActivateTeleop",
      "payload": ""
    }
  }
  ```

- When it is done: "Teleoperation enabled."

**"switch on manual drive"** becomes `manual_drive(state: 'on')`.

- It reads back: "Enabling teleoperation. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "ActivateTeleop",
      "payload": ""
    }
  }
  ```

- When it is done: "Teleoperation enabled."

**"give me the gamepad"** becomes `manual_drive(state: 'on')`.

- It reads back: "Enabling teleoperation. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "ActivateTeleop",
      "payload": ""
    }
  }
  ```

- When it is done: "Teleoperation enabled."

**"turn teleoperation off"** becomes `manual_drive(state: 'off')`.

- It reads back: "Disabling teleoperation. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "ActivateController",
      "payload": "{controllers: joint_trajectory_controller}"
    }
  }
  ```

- When it is done: "Teleoperation disabled."

### stop

Stops whatever the rig is doing, at once. The rig also stops whenever the user says stop.

**"stop everything"** becomes `stop()`.

- It says: "Stopping."
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/commander/execute_objective/_action/cancel_goal",
    "type": "action_msgs/srv/CancelGoal",
    "args": {}
  }
  ```

- When it is done: "Stopped."

**"halt the robot"** becomes `stop()`.

- It says: "Stopping."
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/commander/execute_objective/_action/cancel_goal",
    "type": "action_msgs/srv/CancelGoal",
    "args": {}
  }
  ```

- When it is done: "Stopped."

### mark

Marks where the camera is now as the near or the far end of the focus stack: the near end is the closest part of the subject in focus, the far end the farthest.

| Parameter | Values | Description |
|---|---|---|
| `end` | `near`, `far` |  |

**"mark the near end"** becomes `mark(end: 'near')`.

- It reads back: "Marking the near end. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MarkNear",
      "payload": ""
    }
  }
  ```

- When it is done: "The near end is marked."

**"this is the far point"** becomes `mark(end: 'far')`.

- It reads back: "Marking the far end. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MarkFar",
      "payload": ""
    }
  }
  ```

- When it is done: "The far end is marked."

**"set the near mark here"** becomes `mark(end: 'near')`.

- It reads back: "Marking the near end. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "MarkNear",
      "payload": ""
    }
  }
  ```

- When it is done: "The near end is marked."

### set_stack

Changes the plan of the focus stack: the shots from the near end to the far one, the angles of the stage, and how far the stage turns either way. Give only what changes.

| Parameter | Values | Description |
|---|---|---|
| `shots` | 1 to 500 | shots from the near end to the far one Optional. |
| `angles` | 1 to 360 | angles of the stage Optional. |
| `turn` | 0 to 180 | how far the stage turns either way, in degrees, e.g. 17 for -17 to 17 Optional. |

**"set the stack to 20 shots"** becomes `set_stack(shots: 20)`.

- It reads back: "Setting 20 shots. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/stack_state/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "state.shots",
          "value": {
            "type": 8,
            "double_array_value": [
              20.0
            ]
          }
        }
      ]
    }
  }
  ```

- When it is done: "The stack is set."

**"use 12 angles and turn 30 degrees either way"** becomes `set_stack(angles: 12, turn: 30.0)`.

- It reads back: "Setting 12 angles, a turn of plus or minus 30 degrees. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/stack_state/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "state.angles",
          "value": {
            "type": 8,
            "double_array_value": [
              12.0
            ]
          }
        },
        {
          "name": "state.turn",
          "value": {
            "type": 8,
            "double_array_value": [
              30.0
            ]
          }
        }
      ]
    }
  }
  ```

- When it is done: "The stack is set."

**"15 shots at 5 angles"** becomes `set_stack(shots: 15, angles: 5)`.

- It reads back: "Setting 15 shots, 5 angles. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/stack_state/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "state.shots",
          "value": {
            "type": 8,
            "double_array_value": [
              15.0
            ]
          }
        },
        {
          "name": "state.angles",
          "value": {
            "type": 8,
            "double_array_value": [
              5.0
            ]
          }
        }
      ]
    }
  }
  ```

- When it is done: "The stack is set."

### start_focus_stack

Starts a focus stack with the plan and the marks the rig holds.

It first reads the robot: `plan` with `get_parameters`.

**"start the focus stack"** becomes `start_focus_stack()`.

- It reads back: "Stacking 10 shots at 35 angles, plus or minus 17 degrees: 350 pictures. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "FocusStack",
      "payload": "{shots: 10, stage_from: -17.0, stage_to: 17.0, angles: 35}"
    }
  }
  ```

- When it is done: "The focus stack is finished, 350 pictures."

**"shoot the stack"** becomes `start_focus_stack()`.

- It reads back: "Stacking 8 shots at 1 angle: 8 pictures. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "FocusStack",
      "payload": "{shots: 8, stage_from: 0.0, stage_to: 0.0, angles: 1}"
    }
  }
  ```

- When it is done: "The focus stack is finished, 8 pictures."

### describe_stack

Says the plan of the focus stack and which ends are marked. Changes nothing.

It first reads the robot: `plan` with `get_parameters`.

**"what is the plan of the stack"** becomes `describe_stack()`.

- It answers: "The stack is 10 shots at 35 angles, from minus 17 to 17 degrees: 350 pictures. The near end is marked, the far end is not."

### take_test_shot

Takes one test picture, to check the framing and the exposure.

**"do a test shot"** becomes `take_test_shot()`.

- It reads back: "Taking a test shot. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "TakeShot",
      "payload": ""
    }
  }
  ```

- When it is done: "The test shot is taken."

**"take a picture"** becomes `take_test_shot()`.

- It reads back: "Taking a test shot. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "send_action_goal",
    "action": "/commander/execute_objective",
    "action_type": "btcpp_ros2_interfaces/action/ExecuteTree",
    "args": {
      "target_tree": "TakeShot",
      "payload": ""
    }
  }
  ```

- When it is done: "The test shot is taken."

### set_camera

Changes a setting of the camera. The value is as the camera writes it: an ISO such as 400 or Auto, a shutter speed such as 1/125 or 2, an aperture such as 8 or 5.6, an exposure compensation such as -1 or 0.3, a white balance such as Auto, Daylight or Cloudy.

| Parameter | Values | Description |
|---|---|---|
| `setting` | `iso`, `shutter_speed`, `aperture`, `exposure_compensation`, `white_balance` |  |
| `value` | any | the value as the camera writes it, e.g. 400, 1/125, 5.6 or Daylight |

**"set the ISO to 400"** becomes `set_camera(setting: 'iso', value: '400')`.

- It reads back: "Setting ISO 400. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "iso",
          "value": {
            "type": 4,
            "string_value": "400"
          }
        }
      ]
    }
  }
  ```

- When it is done: "ISO is 400."

**"aperture f 8"** becomes `set_camera(setting: 'aperture', value: '8')`.

- It reads back: "Setting aperture 8. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "aperture",
          "value": {
            "type": 4,
            "string_value": "8"
          }
        }
      ]
    }
  }
  ```

- When it is done: "Aperture is 8."

**"shutter speed one over 125"** becomes `set_camera(setting: 'shutter_speed', value: '1/125')`.

- It reads back: "Setting shutter speed 1/125. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "shutter_speed",
          "value": {
            "type": 4,
            "string_value": "1/125"
          }
        }
      ]
    }
  }
  ```

- When it is done: "Shutter speed is 1/125."

**"white balance daylight"** becomes `set_camera(setting: 'white_balance', value: 'Daylight')`.

- It reads back: "Setting white balance Daylight. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/set_parameters",
    "type": "rcl_interfaces/srv/SetParameters",
    "args": {
      "parameters": [
        {
          "name": "white_balance",
          "value": {
            "type": 4,
            "string_value": "Daylight"
          }
        }
      ]
    }
  }
  ```

- When it is done: "White balance is Daylight."

### live_view

Starts or stops the live view of the camera.

| Parameter | Values | Description |
|---|---|---|
| `state` | `on`, `off` |  |

**"turn on the live view"** becomes `live_view(state: 'on')`.

- It reads back: "Starting live view. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/start_streaming",
    "type": "std_srvs/srv/Trigger",
    "args": {}
  }
  ```

- When it is done: "The live view is on."

**"live view off"** becomes `live_view(state: 'off')`.

- It reads back: "Stopping live view. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/camera/stop_streaming",
    "type": "std_srvs/srv/Trigger",
    "args": {}
  }
  ```

- When it is done: "The live view is off."

### lights

Switches the lights of the rig on or off.

| Parameter | Values | Description |
|---|---|---|
| `state` | `on`, `off` |  |

It first reads the robot: `outputs` with `read_latched_topic`.

**"lights on"** becomes `lights(state: 'on')`.

- It reads back: "Switching lights on. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/freezer/set_outputs",
    "type": "freezer_msgs/srv/SetOutputs",
    "args": {
      "outputs": 3
    }
  }
  ```

- When it is done: "The lights are on."

**"switch the lights off"** becomes `lights(state: 'off')`.

- It reads back: "Switching lights off. Confirm?"
- It sends to rosbridge:

  ```json
  {
    "op": "call_service",
    "service": "/freezer/set_outputs",
    "type": "freezer_msgs/srv/SetOutputs",
    "args": {
      "outputs": 0
    }
  }
  ```

- When it is done: "The lights are off."

### report_status

Says what the rig is doing now. Changes nothing.

It first reads the robot: `objective` with `read_latched_topic`.

**"what is the rig doing"** becomes `report_status()`.

- It answers: "The rig is running FocusStack."

**"is anything running"** becomes `report_status()`.

- It answers: "The rig is idle."

### report_progress

Says how far the running or the last focus stack is. Changes nothing.

It first reads the robot: `progress` with `read_latched_topic`.

**"how far is the stack"** becomes `report_progress()`.

- It answers: "120 of 350 pictures are taken."

### sleep

Puts the voice to sleep: until the user says the wake phrase, it hears nothing but stop. It does not stop the robot.

**"go to sleep"** becomes `sleep()`.

- It reads back: "Putting the voice to sleep. Confirm?"
- It runs nothing on the robot. The voice says: "Going to sleep. To wake me, say: Wake up."

**"goodnight StepIt"** becomes `sleep()`.

- It reads back: "Putting the voice to sleep. Confirm?"
- It runs nothing on the robot. The voice says: "Going to sleep. To wake me, say: Wake up."

**"take a break"** becomes `sleep()`.

- It reads back: "Putting the voice to sleep. Confirm?"
- It runs nothing on the robot. The voice says: "Going to sleep. To wake me, say: Wake up."
