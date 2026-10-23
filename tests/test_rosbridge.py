# Copyright (c) 2026 Giovanni Remigi
# SPDX-License-Identifier: MIT
"""The rosbridge client against a fake rosbridge server, and the robot on top of it."""

import asyncio

import pytest

from voicebridge.catalogue import Call
from voicebridge.robot import RosbridgeRobot, judge, render_request
from voicebridge.rosbridge import ActionResult, Rosbridge, RosbridgeError


async def test_call_service(fake_rosbridge):
    fake_rosbridge.services["/camera/start_streaming"] = {"success": True, "message": "on"}
    client = Rosbridge(fake_rosbridge.url)
    try:
        response = await client.call_service("/camera/start_streaming", "std_srvs/srv/Trigger", {})
    finally:
        await client.close()
    assert response == {"success": True, "message": "on"}
    sent = fake_rosbridge.ops("call_service")[0]
    assert (sent["service"], sent["type"], sent["args"]) == ("/camera/start_streaming", "std_srvs/srv/Trigger", {})


async def test_a_refused_call_fails(fake_rosbridge):
    fake_rosbridge.services["/broken"] = RuntimeError("service /broken does not exist")
    client = Rosbridge(fake_rosbridge.url)
    try:
        with pytest.raises(RosbridgeError, match="does not exist"):
            await client.call_service("/broken", "std_srvs/srv/Trigger", {})
        with pytest.raises(RosbridgeError, match="no service /unknown"):
            await client.call_service("/unknown", "std_srvs/srv/Trigger", {})
    finally:
        await client.close()


async def test_send_action_goal(fake_rosbridge):
    fake_rosbridge.actions["/commander/execute_objective"] = (4, {"node_status": {"status": 2},
                                                                  "return_message": ""})
    client = Rosbridge(fake_rosbridge.url)
    try:
        result = await client.send_action_goal("/commander/execute_objective",
                                               "btcpp_ros2_interfaces/action/ExecuteTree",
                                               {"target_tree": "TakeShot", "payload": ""})
    finally:
        await client.close()
    assert result == ActionResult(4, {"node_status": {"status": 2}, "return_message": ""})
    goal = fake_rosbridge.ops("send_action_goal")[0]
    assert goal["action_type"] == "btcpp_ros2_interfaces/action/ExecuteTree"
    assert goal["args"] == {"target_tree": "TakeShot", "payload": ""}


async def test_a_goal_that_does_not_end_in_time_is_cancelled(fake_rosbridge):
    fake_rosbridge.hold_actions = True
    client = Rosbridge(fake_rosbridge.url)
    try:
        with pytest.raises(RosbridgeError, match="did not end"):
            await client.send_action_goal("/arm/move", "arm_msgs/action/Move", {}, timeout_s=0.2)
        await asyncio.sleep(0.1)
    finally:
        await client.close()
    cancel = fake_rosbridge.ops("cancel_action_goal")
    assert cancel and cancel[0]["id"] == fake_rosbridge.ops("send_action_goal")[0]["id"]


async def test_read_topic_with_its_qos(fake_rosbridge):
    fake_rosbridge.topics["/stepit_server/objective"] = {"data": "FocusStack"}
    client = Rosbridge(fake_rosbridge.url)
    qos = {"reliability": "reliable", "durability": "transient_local", "history": "keep_last", "depth": 1}
    try:
        message = await client.read_topic("/stepit_server/objective", "std_msgs/msg/String", qos)
        await asyncio.sleep(0.05)
    finally:
        await client.close()
    assert message == {"data": "FocusStack"}
    assert fake_rosbridge.ops("subscribe")[0]["qos"] == qos
    assert fake_rosbridge.ops("unsubscribe")


async def test_a_silent_topic_times_out(fake_rosbridge):
    client = Rosbridge(fake_rosbridge.url)
    try:
        with pytest.raises(RosbridgeError, match="no message"):
            await client.read_topic("/nothing", "std_msgs/msg/String", timeout_s=0.1)
    finally:
        await client.close()


async def test_publish_advertises_once(fake_rosbridge):
    client = Rosbridge(fake_rosbridge.url)
    try:
        await client.publish("/ui/joy", "sensor_msgs/msg/Joy", {"axes": [0.0]})
        await client.publish("/ui/joy", "sensor_msgs/msg/Joy", {"axes": [0.5]})
        await asyncio.sleep(0.05)
    finally:
        await client.close()
    assert len(fake_rosbridge.ops("advertise")) == 1
    assert [m["msg"] for m in fake_rosbridge.ops("publish")] == [{"axes": [0.0]}, {"axes": [0.5]}]


async def test_fragments_are_joined(fake_rosbridge):
    fake_rosbridge.fragment_size = 20
    fake_rosbridge.services["/big"] = {"message": "x" * 200}
    client = Rosbridge(fake_rosbridge.url)
    try:
        assert await client.call_service("/big", "std_srvs/srv/Trigger", {}) == {"message": "x" * 200}
    finally:
        await client.close()


async def test_no_rosbridge_fails_at_once():
    client = Rosbridge("ws://127.0.0.1:9", connect_timeout_s=1)
    with pytest.raises(RosbridgeError, match="cannot reach rosbridge"):
        await client.call_service("/x", "std_srvs/srv/Trigger", {})


async def test_a_lost_connection_fails_the_goal_and_the_next_call_reconnects(fake_rosbridge):
    fake_rosbridge.hold_actions = True
    fake_rosbridge.services["/ping"] = {"success": True}
    client = Rosbridge(fake_rosbridge.url)
    try:
        goal = asyncio.create_task(client.send_action_goal("/arm/move", "arm_msgs/action/Move", {}))
        await asyncio.sleep(0.1)
        for socket in list(fake_rosbridge.sockets):
            await socket.close()
        with pytest.raises(RosbridgeError, match="lost"):
            await goal
        assert await client.call_service("/ping", "std_srvs/srv/Trigger", {}) == {"success": True}
    finally:
        await client.close()


# ── The robot over rosbridge ────────────────────────────────────────────────

OBJECTIVE = Call(name="objective", kind="action", target="/commander/execute_objective",
                 type="btcpp_ros2_interfaces/action/ExecuteTree",
                 request={"target_tree": "{{ name }}", "payload": ""},
                 success="status == 4 and response.node_status.status == 2",
                 message="{{ response.return_message }}")


async def test_the_robot_judges_an_objective_by_its_tree(fake_rosbridge):
    robot = RosbridgeRobot(Rosbridge(fake_rosbridge.url))
    request = render_request(OBJECTIVE, {"name": "TakeShot"})
    fake_rosbridge.actions["/commander/execute_objective"] = (4, {"node_status": {"status": 2},
                                                                  "return_message": ""})
    assert (await robot.execute(request)).ok
    # The goal succeeded but the tree failed: not a success.
    fake_rosbridge.actions["/commander/execute_objective"] = (4, {"node_status": {"status": 3},
                                                                  "return_message": "no picture came"})
    outcome = await robot.execute(request)
    assert (outcome.ok, outcome.message) == (False, "no picture came")


async def test_the_robot_turns_a_lost_rosbridge_into_a_failure():
    robot = RosbridgeRobot(Rosbridge("ws://127.0.0.1:9", connect_timeout_s=1))
    outcome = await robot.execute(render_request(OBJECTIVE, {"name": "TakeShot"}))
    assert not outcome.ok
    assert "cannot reach rosbridge" in outcome.message


def test_judge_defaults():
    action = Call(name="a", kind="action", target="/a", type="t")
    assert judge(render_request(action, {}), {}, 4).ok
    stopped = judge(render_request(action, {}), {}, 5)
    assert (stopped.ok, stopped.message) == (False, "it was stopped")
    aborted = judge(render_request(action, {}), {}, 6)
    assert (aborted.ok, aborted.message) == (False, "")
    service = Call(name="s", kind="service", target="/s", type="t", result="response.x")
    assert judge(render_request(service, {}), {"x": 7}).value == 7


def test_a_result_that_cannot_be_read_is_a_failure():
    service = Call(name="s", kind="service", target="/s", type="t", success="response.missing.deeper")
    assert not judge(render_request(service, {}), {}).ok
