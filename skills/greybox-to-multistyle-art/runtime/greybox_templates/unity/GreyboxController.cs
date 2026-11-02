using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace GreyboxHarnessV05
{
    [Serializable] public sealed class HarnessActions
    {
        public float move_right, move_left, move_forward, move_backward;
        public float turn_right, turn_left, look_up, look_down;
        public float jump, interact, restart, pause;
    }
    [Serializable] public sealed class HarnessStep
    {
        public string id;
        public HarnessActions actions;
        public int frames = 1;
    }
    [Serializable] public sealed class HarnessSnapshot
    {
        public string id;
        public float[] player_position;
        public string[] collected_ids, interacted_ids;
        public int collected_count, restart_count, fixed_ticks;
        public bool failed, goal_reached, paused, objective_complete, grounded;
    }
    public sealed class GreyboxController : MonoBehaviour
    {
        public string taskId, deliveryGoal, title, view;
        public float speed = 5, height = 1.8f;
        public Vector3 startPosition, cameraOffset = new Vector3(0, 12, 8);
        public string[] requiredIds;
        public string goalId;
        public Camera playerCamera;
        public bool failed, goalReached, paused;
        public int restartCount, fixedTicks;
        public bool ReplayActive { get; private set; }
        public bool ReplayWaiting { get; set; }
        public bool ReplayFinished { get; private set; }
        public readonly List<HarnessSnapshot> Snapshots = new List<HarnessSnapshot>();
        CharacterController body;
        GreyboxEntity[] entities;
        readonly HashSet<string> collected = new HashSet<string>();
        readonly HashSet<string> interacted = new HashSet<string>();
        HarnessActions device = new HarnessActions();
        HarnessStep[] replay;
        int replayIndex, replayTick;
        float verticalVelocity, yaw, pitch, previousFixedDelta;

        void Awake()
        {
            body = GetComponent<CharacterController>();
            entities = FindObjectsByType<GreyboxEntity>(FindObjectsSortMode.None);
            previousFixedDelta = Time.fixedDeltaTime;
            Time.fixedDeltaTime = 1f / 60f;
            ResetWorld(false);
        }
        void OnDestroy() { Time.fixedDeltaTime = previousFixedDelta; }
        void Update()
        {
            if (ReplayActive) return;
            var next = ReadDevice();
            // Preserve one-shot button presses until the next controller tick.
            next.restart = Mathf.Max(next.restart, device.restart);
            next.pause = Mathf.Max(next.pause, device.pause);
            next.interact = Mathf.Max(next.interact, device.interact);
            next.jump = Mathf.Max(next.jump, device.jump);
            device = next;
        }
        HarnessActions ReadDevice()
        {
            var a = new HarnessActions();
#if ENABLE_LEGACY_INPUT_MANAGER
            a.move_right = Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1 : 0;
            a.move_left = Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1 : 0;
            a.move_forward = Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1 : 0;
            a.move_backward = Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1 : 0;
            a.interact = Input.GetKeyDown(KeyCode.E) ? 1 : 0;
            a.restart = Input.GetKeyDown(KeyCode.R) ? 1 : 0;
            a.pause = Input.GetKeyDown(KeyCode.Escape) || Input.GetKeyDown(KeyCode.Space) ? 1 : 0;
            a.jump = Input.GetKeyDown(KeyCode.J) ? 1 : 0;
            if (Input.GetMouseButton(1)) { a.turn_right = Input.GetAxisRaw("Mouse X"); a.look_down = Input.GetAxisRaw("Mouse Y"); }
#elif ENABLE_INPUT_SYSTEM
            var k = UnityEngine.InputSystem.Keyboard.current;
            if (k != null)
            {
                a.move_right = k.dKey.isPressed || k.rightArrowKey.isPressed ? 1 : 0;
                a.move_left = k.aKey.isPressed || k.leftArrowKey.isPressed ? 1 : 0;
                a.move_forward = k.wKey.isPressed || k.upArrowKey.isPressed ? 1 : 0;
                a.move_backward = k.sKey.isPressed || k.downArrowKey.isPressed ? 1 : 0;
                a.interact = k.eKey.wasPressedThisFrame ? 1 : 0;
                a.restart = k.rKey.wasPressedThisFrame ? 1 : 0;
                a.pause = k.escapeKey.wasPressedThisFrame || k.spaceKey.wasPressedThisFrame ? 1 : 0;
                a.jump = k.jKey.wasPressedThisFrame ? 1 : 0;
            }
            var mouse = UnityEngine.InputSystem.Mouse.current;
            if (mouse != null && mouse.rightButton.isPressed) { var delta = mouse.delta.ReadValue(); a.turn_right = delta.x * .08f; a.look_down = delta.y * .08f; }
#endif
            return a;
        }
        public void ConfigureReplay(HarnessStep[] steps)
        {
            replay = steps ?? Array.Empty<HarnessStep>();
            ReplayActive = replay.Length > 0;
            ReplayFinished = replay.Length == 0;
            replayIndex = replayTick = 0;
            Snapshots.Clear();
        }
        void FixedUpdate()
        {
            if (ReplayActive)
            {
                if (ReplayFinished || ReplayWaiting) return;
                var step = replay[replayIndex];
                ApplyActions(step.actions ?? new HarnessActions(), replayTick == 0);
                replayTick++;
                if (replayTick >= step.frames)
                {
                    Snapshots.Add(Snapshot(step.id));
                    replayIndex++; replayTick = 0; ReplayWaiting = true;
                    if (replayIndex >= replay.Length) ReplayFinished = true;
                }
            }
            else
            {
                ApplyActions(device, true);
                device.restart = device.pause = device.interact = device.jump = 0;
            }
        }
        // Both native replay and actual device input call this same method.
        public void ApplyActions(HarnessActions actions, bool pulse)
        {
            fixedTicks++;
            if (pulse && actions.restart > 0) ResetWorld(true);
            if (pulse && actions.pause > 0) paused = !paused;
            if (paused || failed || goalReached) return;
            yaw += (actions.turn_right - actions.turn_left) * 2;
            pitch = Mathf.Clamp(pitch + (actions.look_up - actions.look_down) * 2, -80, 80);
            Vector3 direction = new Vector3(actions.move_right - actions.move_left, 0, actions.move_forward - actions.move_backward);
            if (view == "first_person") direction = Quaternion.Euler(0, yaw, 0) * direction;
            else if (playerCamera != null)
            {
                // Top-down controls follow the camera's screen plane. Explicit
                // camera offsets must not reverse W/D or replay action meaning.
                var forward = Vector3.ProjectOnPlane(playerCamera.transform.forward, Vector3.up);
                if (forward.sqrMagnitude < .0001f) forward = Vector3.ProjectOnPlane(playerCamera.transform.up, Vector3.up);
                var right = Vector3.ProjectOnPlane(playerCamera.transform.right, Vector3.up);
                direction = right.normalized * direction.x + forward.normalized * direction.z;
            }
            direction = Vector3.ClampMagnitude(direction, 1);
            if (body.isGrounded && verticalVelocity < 0) verticalVelocity = -2;
            if (pulse && actions.jump > 0 && body.isGrounded) verticalVelocity = 6;
            verticalVelocity -= 20 * Time.fixedDeltaTime;
            body.Move((direction * speed + Vector3.up * verticalVelocity) * Time.fixedDeltaTime);
            Physics.SyncTransforms();
            if (transform.position.y < startPosition.y - 20) failed = true;
            foreach (var entity in entities)
            {
                if (entity == null || entity.consumed || entity.collision == null || !entity.collision.enabled) continue;
                var bounds = entity.collision.bounds;
                if (!bounds.Intersects(body.bounds))
                {
                    if (entity.behavior == "interactable" && pulse && actions.interact > 0 && Vector3.Distance(transform.position + Vector3.up * height * .5f, entity.InteractionWorldAnchor) < 2) interacted.Add(entity.stableId);
                    continue;
                }
                switch (entity.behavior)
                {
                    case "collectible": collected.Add(entity.stableId); entity.Consume(); break;
                    case "hazard": failed = true; break;
                    case "interactable": if (pulse && actions.interact > 0) interacted.Add(entity.stableId); break;
                }
            }
            if (!failed && deliveryGoal == "playable" && (requiredIds ?? Array.Empty<string>()).All(id => collected.Contains(id)))
            {
                var goal = entities.FirstOrDefault(e => e != null && e.stableId == goalId);
                goalReached = goal != null && goal.collision != null && goal.collision.bounds.Intersects(body.bounds);
            }
        }
        public void ResetWorld(bool count)
        {
            if (count) restartCount++;
            failed = goalReached = paused = false;
            collected.Clear(); interacted.Clear(); verticalVelocity = 0; yaw = pitch = 0;
            body.enabled = false; transform.position = startPosition; body.enabled = true;
            foreach (var entity in entities) if (entity != null) entity.ResetEntity();
            Physics.SyncTransforms();
        }
        public HarnessSnapshot Snapshot(string id = "final")
        {
            var p = transform.position;
            return new HarnessSnapshot { id = id, player_position = new[] { p.x, p.y, p.z }, collected_ids = collected.OrderBy(x => x).ToArray(), interacted_ids = interacted.OrderBy(x => x).ToArray(), collected_count = collected.Count, restart_count = restartCount, fixed_ticks = fixedTicks, failed = failed, goal_reached = goalReached, paused = paused, objective_complete = deliveryGoal == "playable" && goalReached, grounded = body.isGrounded };
        }
        void LateUpdate()
        {
            if (playerCamera == null) return;
            if (view == "first_person") { playerCamera.transform.position = transform.position + Vector3.up * height * .9f; playerCamera.transform.rotation = Quaternion.Euler(pitch, yaw, 0); }
            else { playerCamera.transform.position = transform.position + cameraOffset; playerCamera.transform.LookAt(transform.position + Vector3.up * height * .5f); }
        }
        void OnGUI()
        {
            GUI.Box(new Rect(12, 12, 480, 94), "");
            GUI.Label(new Rect(24, 18, 450, 24), title + " | " + (paused ? "PAUSED" : failed ? "FAILED — R restart" : goalReached ? "COMPLETE — R restart" : "EXPLORE"));
            GUI.Label(new Rect(24, 44, 450, 24), "WASD / arrows move · E interact · R restart · Space / Esc pause");
            GUI.Label(new Rect(24, 70, 450, 24), deliveryGoal == "playable" ? "Collected " + collected.Count + " / " + (requiredIds?.Length ?? 0) + " — reach the goal" : "Spatial prototype — walk, inspect scale and interaction anchors");
        }
    }
}
