using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace GreyboxHarnessV05.Editor
{
    [Serializable] sealed class PropertySpec { public string name, kind, text; public double number; public bool boolean; public float[] values; }
    [Serializable] sealed class EntitySpec
    {
        public string id, role, shape, behavior, component_type, label;
        public string[] tags;
        public float[] position, size, color, interaction_anchor;
        public bool collider;
        public PropertySpec[] properties;
    }
    [Serializable] sealed class PlayerSpec { public float[] position; public float speed, height, radius; public string view; }
    [Serializable] sealed class CameraSpec { public float[] offset; }
    [Serializable] sealed class ObjectiveSpec { public string[] required_ids; public string goal_id; }
    [Serializable] sealed class BuildSpec { public string id, goal, title; public PlayerSpec player; public CameraSpec camera; public EntitySpec[] entities; public ObjectiveSpec objective; }
    [Serializable] sealed class Request
    {
        public string operation, request_id, scene, spec_path, report, evidence_root;
        public bool configure_pipeline;
        public int capture_frames = 3, warmup_frames = 8, width = 960, height = 540, frame_stride = 4;
        public HarnessStep[] steps;
    }
    [Serializable] sealed class AnchorRecord { public string space = "local+world"; public float[] local, world; }
    [Serializable] sealed class BoundsRecord { public string space = "world"; public float[] center, size; }
    [Serializable] sealed class EntityRecord
    {
        public string id, role, behavior, node_path, logic_path, collision_path, visual_path, collision_shape;
        public string[] protected_components;
        public string[] tags;
        public AnchorRecord anchor;
        public BoundsRecord collision_bounds;
        public bool replaceable = true;
        public bool solid_collision;
        public bool collision_enabled;
    }
    [Serializable] sealed class CaptureRecord { public string path, sha256; public int frame, fixed_ticks, width, height; public float time; }
    [Serializable] sealed class Report
    {
        public bool ok, play_mode;
        public string engine = "unity", pipeline = "urp", request_id, operation, scene, graphics_device, input_mode;
        public string[] errors = Array.Empty<string>();
        public List<EntityRecord> entities = new List<EntityRecord>();
        public List<HarnessSnapshot> snapshots = new List<HarnessSnapshot>();
        public List<CaptureRecord> captures = new List<CaptureRecord>();
        public HarnessSnapshot telemetry;
        public int frames_observed;
    }

    [InitializeOnLoad]
    public static class AuthoringBridge
    {
        const string PendingKey = "GreyboxHarnessV05.Pending";
        static Request request;
        static Report report;
        static GreyboxController controller;
        static int initialFrame, lastFrame, consumedSnapshots;
        static double waitSince;
        static readonly List<string> runtimeErrors = new List<string>();
        static AuthoringBridge() { EditorApplication.playModeStateChanged += PlayState; }
        static float[] V(Vector3 p) { return new[] { p.x, p.y, p.z }; }
        static Vector3 V(float[] a) { return new Vector3(a[0], a[1], a[2]); }
        static string NodePath(Transform item) { return item.parent == null ? item.name : NodePath(item.parent) + "/" + item.name; }
        static Report NewReport() { return new Report { request_id = request.request_id, operation = request.operation, scene = request.scene, graphics_device = SystemInfo.graphicsDeviceType.ToString() }; }
        static void Save()
        {
            report.ok = report.errors.Length == 0;
            Directory.CreateDirectory(Path.GetDirectoryName(request.report));
            File.WriteAllText(request.report, JsonUtility.ToJson(report, true) + "\n");
        }
        static void Fail(Exception error)
        {
            if (report == null) report = NewReport();
            report.errors = report.errors.Concat(new[] { error.ToString() }).ToArray();
            Save();
            Debug.LogException(error);
        }
        public static void Execute()
        {
            try
            {
                string[] args = Environment.GetCommandLineArgs();
                int index = Array.IndexOf(args, "-greyboxAuthoringRequest");
                if (index < 0 || index + 1 >= args.Length) throw new InvalidOperationException("Missing authoring request");
                request = JsonUtility.FromJson<Request>(File.ReadAllText(args[index + 1]));
                report = NewReport();
                if (request.operation == "build") { Build(); Save(); EditorApplication.Exit(report.ok ? 0 : 2); }
                else if (request.operation == "run")
                {
                    EnsurePipeline(false);
                    EditorSceneManager.OpenScene(request.scene, OpenSceneMode.Single);
                    report.entities = ReadActualEntities();
                    File.WriteAllText(Path.Combine(request.evidence_root, "scene-bindings.json"), JsonUtility.ToJson(report, true) + "\n");
                    SessionState.SetString(PendingKey, args[index + 1]);
                    waitSince = EditorApplication.timeSinceStartup;
                    EditorApplication.update += EnterWhenIdle;
                }
                else throw new InvalidOperationException("Unsupported authoring operation");
            }
            catch (Exception error) { Fail(error); EditorApplication.Exit(2); }
        }
        static void EnterWhenIdle()
        {
            if (EditorApplication.isCompiling || EditorApplication.isUpdating) { waitSince = EditorApplication.timeSinceStartup; return; }
            if (EditorApplication.timeSinceStartup - waitSince < .5) return;
            EditorApplication.update -= EnterWhenIdle;
            EditorApplication.EnterPlaymode();
        }
        static void EnsurePipeline(bool configure)
        {
            if (configure && GraphicsSettings.defaultRenderPipeline == null)
            {
                const string directory = "Assets/GreyboxHarness/Pipeline";
                Directory.CreateDirectory(directory);
                AssetDatabase.Refresh();
                var renderer = ScriptableObject.CreateInstance<UniversalRendererData>();
                AssetDatabase.CreateAsset(renderer, directory + "/Renderer.asset");
                var pipeline = UniversalRenderPipelineAsset.Create(renderer);
                pipeline.supportsHDR = true;
                pipeline.supportsCameraDepthTexture = true;
                AssetDatabase.CreateAsset(pipeline, directory + "/URP.asset");
                GraphicsSettings.defaultRenderPipeline = pipeline;
                QualitySettings.renderPipeline = pipeline;
                PlayerSettings.colorSpace = ColorSpace.Linear;
                if (GraphicsSettings.TryGetRenderPipelineSettings<URPDefaultVolumeProfileSettings>(out var settings) && settings.volumeProfile != null)
                {
                    UnityEditor.Rendering.VolumeProfileUtils.EnsureAllOverridesForDefaultProfile(settings.volumeProfile);
                    EditorUtility.SetDirty(settings.volumeProfile);
                }
                AssetDatabase.SaveAssets();
            }
            if (!(GraphicsSettings.currentRenderPipeline is UniversalRenderPipelineAsset)) throw new InvalidOperationException("Greybox authoring supports active URP only; existing pipeline is preserved");
        }
        static void SetProperties(Component component, PropertySpec[] properties)
        {
            var serialized = new SerializedObject(component);
            foreach (var value in properties ?? Array.Empty<PropertySpec>())
            {
                var property = serialized.FindProperty(value.name);
                if (property == null || !property.editable) throw new InvalidOperationException("Unknown or uneditable serialized component property: " + value.name);
                switch (property.propertyType)
                {
                    case SerializedPropertyType.Boolean: if (value.kind != "bool") throw new InvalidOperationException("Expected boolean: " + value.name); property.boolValue = value.boolean; break;
                    case SerializedPropertyType.String: if (value.kind != "string") throw new InvalidOperationException("Expected string: " + value.name); property.stringValue = value.text; break;
                    case SerializedPropertyType.Integer: if (value.kind != "number" || value.number != Math.Truncate(value.number)) throw new InvalidOperationException("Expected integer: " + value.name); property.longValue = (long)value.number; break;
                    case SerializedPropertyType.Float: if (value.kind != "number") throw new InvalidOperationException("Expected number: " + value.name); property.doubleValue = value.number; break;
                    case SerializedPropertyType.Vector2: if (value.kind != "vector" || value.values.Length != 2) throw new InvalidOperationException("Expected Vector2: " + value.name); property.vector2Value = new Vector2(value.values[0], value.values[1]); break;
                    case SerializedPropertyType.Vector3: if (value.kind != "vector" || value.values.Length != 3) throw new InvalidOperationException("Expected Vector3: " + value.name); property.vector3Value = V(value.values); break;
                    case SerializedPropertyType.Color: if (value.kind != "vector" || value.values.Length != 4) throw new InvalidOperationException("Expected RGBA color: " + value.name); property.colorValue = new Color(value.values[0], value.values[1], value.values[2], value.values[3]); break;
                    default: throw new InvalidOperationException("Unsupported serialized component property type: " + value.name + " (" + property.propertyType + ")");
                }
            }
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }
        static Transform Child(string name, Transform parent)
        {
            var item = new GameObject(name).transform; item.SetParent(parent, false); return item;
        }
        static void Build()
        {
            EnsurePipeline(request.configure_pipeline);
            var spec = JsonUtility.FromJson<BuildSpec>(File.ReadAllText(request.spec_path));
            var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var root = new GameObject("Greybox_" + spec.id).transform;
            var entityRoot = Child("Entities", root);
            var shader = Shader.Find("Universal Render Pipeline/Lit");
            if (shader == null) throw new InvalidOperationException("URP Lit shader is unavailable");
            string materials = Path.GetDirectoryName(request.scene).Replace('\\', '/') + "/Materials";
            Directory.CreateDirectory(materials); AssetDatabase.Refresh();
            foreach (var item in spec.entities)
            {
                var owner = Child(item.id, entityRoot);
                owner.position = V(item.position);
                var logic = Child("Logic", owner);
                var visual = GameObject.CreatePrimitive(item.shape == "sphere" ? PrimitiveType.Sphere : item.shape == "cylinder" ? PrimitiveType.Cylinder : PrimitiveType.Cube);
                visual.name = "Visual"; visual.transform.SetParent(owner, false);
                visual.transform.localScale = V(item.size);
                if (item.shape == "cylinder") visual.transform.localScale = new Vector3(item.size[0], item.size[1] * .5f, item.size[2]);
                UnityEngine.Object.DestroyImmediate(visual.GetComponent<Collider>());
                var material = new Material(shader);
                material.SetColor("_BaseColor", new Color(item.color[0], item.color[1], item.color[2], item.color[3]));
                material.SetFloat("_Smoothness", .15f);
                AssetDatabase.CreateAsset(material, materials + "/" + item.id + ".mat");
                visual.GetComponent<Renderer>().sharedMaterial = material;
                var collisionRoot = Child("Collision", owner);
                BoxCollider collision = null;
                if (item.collider) { collision = collisionRoot.gameObject.AddComponent<BoxCollider>(); collision.size = V(item.size); }
                if (item.behavior != "none")
                {
                    // collider controls solid blocking. Interaction bounds exist
                    // independently, including on nonblocking collectible zones.
                    var trigger = Child("Interaction", collisionRoot).gameObject.AddComponent<BoxCollider>();
                    trigger.size = V(item.size); trigger.isTrigger = true; collision = trigger;
                }
                var semantic = owner.gameObject.AddComponent<GreyboxEntity>();
                semantic.stableId = item.id; semantic.semanticRole = item.role; semantic.behavior = item.behavior;
                semantic.label = item.label ?? item.id; semantic.tags = item.tags ?? Array.Empty<string>();
                semantic.interactionAnchor = owner.TransformPoint(V(item.interaction_anchor));
                semantic.logic = logic;
                semantic.collisionOwner = collisionRoot;
                semantic.anchor = Child("InteractionAnchor", owner);
                semantic.anchor.localPosition = V(item.interaction_anchor);
                semantic.visual = visual.transform; semantic.collision = collision;
                if (!String.IsNullOrWhiteSpace(item.component_type))
                {
                    var types = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType(item.component_type, false)).Where(t => t != null).ToArray();
                    if (types.Length != 1 || !typeof(MonoBehaviour).IsAssignableFrom(types[0]) || types[0].IsAbstract) throw new InvalidOperationException("component_type must uniquely name a project MonoBehaviour: " + item.component_type);
                    var component = logic.gameObject.AddComponent(types[0]); SetProperties(component, item.properties);
                }
                Physics.SyncTransforms();
                report.entities.Add(new EntityRecord { id = item.id, role = item.role, behavior = item.behavior, node_path = NodePath(owner), logic_path = NodePath(logic), collision_path = NodePath(collisionRoot), visual_path = NodePath(visual.transform), collision_shape = collision != null ? "axis-aligned-box-envelope" : "none", solid_collision = item.collider, anchor = new AnchorRecord { local = item.interaction_anchor, world = V(semantic.interactionAnchor) }, collision_bounds = new BoundsRecord { center = collision != null ? V(collision.bounds.center) : item.position, size = collision != null ? V(collision.bounds.size) : new[] { 0f, 0f, 0f } }, protected_components = new[] { typeof(GreyboxEntity).FullName, "Logic", "Collision" }, tags = semantic.tags });
            }
            var player = Child("Player", root); player.position = V(spec.player.position);
            var body = player.gameObject.AddComponent<CharacterController>();
            body.height = spec.player.height; body.radius = spec.player.radius; body.center = Vector3.up * spec.player.height * .5f;
            body.skinWidth = Mathf.Min(.04f, spec.player.radius * .1f); body.stepOffset = Mathf.Min(.3f, spec.player.height * .2f);
            var capsule = GameObject.CreatePrimitive(PrimitiveType.Capsule); capsule.name = "Visual"; capsule.transform.SetParent(player, false);
            UnityEngine.Object.DestroyImmediate(capsule.GetComponent<Collider>());
            capsule.transform.localPosition = Vector3.up * spec.player.height * .5f;
            capsule.transform.localScale = new Vector3(spec.player.radius * 2, spec.player.height * .5f, spec.player.radius * 2);
            var playerMaterial = new Material(shader); playerMaterial.SetColor("_BaseColor", new Color(.16f, .43f, .9f));
            AssetDatabase.CreateAsset(playerMaterial, materials + "/_Player.mat"); capsule.GetComponent<Renderer>().sharedMaterial = playerMaterial;
            if (spec.player.view == "first_person") capsule.SetActive(false);
            var cameraObject = Child("Camera", root); cameraObject.gameObject.tag = "MainCamera";
            var camera = cameraObject.gameObject.AddComponent<Camera>(); camera.nearClipPlane = .05f; camera.farClipPlane = 1000;
            camera.backgroundColor = new Color(.2f, .25f, .32f); camera.clearFlags = CameraClearFlags.SolidColor;
            cameraObject.gameObject.AddComponent<AudioListener>(); cameraObject.gameObject.AddComponent<UniversalAdditionalCameraData>();
            var controller = player.gameObject.AddComponent<GreyboxController>();
            controller.taskId = spec.id; controller.deliveryGoal = spec.goal; controller.title = spec.title; controller.view = spec.player.view;
            controller.speed = spec.player.speed; controller.height = spec.player.height; controller.startPosition = V(spec.player.position);
            controller.cameraOffset = V(spec.camera.offset); controller.playerCamera = camera;
            controller.requiredIds = spec.objective.required_ids; controller.goalId = spec.objective.goal_id;
            camera.transform.position = player.position + controller.cameraOffset; camera.transform.LookAt(player.position + Vector3.up * spec.player.height * .5f);
            var sun = Child("Sun", root); sun.rotation = Quaternion.Euler(48, -30, 0);
            var light = sun.gameObject.AddComponent<Light>(); light.type = LightType.Directional; light.intensity = 1.6f; light.shadows = LightShadows.Soft;
            RenderSettings.ambientMode = AmbientMode.Flat; RenderSettings.ambientLight = new Color(.45f, .5f, .6f); RenderSettings.sun = light;
            EditorSceneManager.MarkSceneDirty(scene);
            if (!EditorSceneManager.SaveScene(scene, request.scene)) throw new InvalidOperationException("Unity failed to save greybox scene");
            AssetDatabase.SaveAssets();
            report.entities = ReadActualEntities();
        }
        static List<EntityRecord> ReadActualEntities()
        {
            // Read serialized scene state before PlayMode consumes items or moves
            // the player. Entity metadata contains actual object references;
            // names, hierarchy, anchors and bounds come from the opened scene.
            Physics.SyncTransforms();
            var rows = new List<EntityRecord>();
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var semantic in SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(root => root.GetComponentsInChildren<GreyboxEntity>(true)))
            {
                if (String.IsNullOrWhiteSpace(semantic.stableId) || !seen.Add(semantic.stableId)) throw new InvalidOperationException("Missing or duplicate actual semantic stable ID: " + semantic.stableId);
                if (String.IsNullOrWhiteSpace(semantic.semanticRole)) throw new InvalidOperationException("Actual semantic role missing for " + semantic.stableId);
                if (semantic.visual == null || !semantic.visual.IsChildOf(semantic.transform)) throw new InvalidOperationException("Actual Visual reference missing/outside entity for " + semantic.stableId);
                // Legacy harness scenes used a fixed Logic child; new scenes
                // store the reference, so later child renames remain readable.
                var logic = semantic.logic != null ? semantic.logic : semantic.transform.Find("Logic");
                if (logic == null || !logic.IsChildOf(semantic.transform)) throw new InvalidOperationException("Actual Logic reference missing/outside entity for " + semantic.stableId);
                var collision = semantic.collision;
                if (collision != null && !collision.transform.IsChildOf(semantic.transform)) throw new InvalidOperationException("Actual collision reference escaped entity for " + semantic.stableId);
                if (semantic.behavior != "none" && collision == null) throw new InvalidOperationException("Actual interaction collision missing for " + semantic.stableId);
                var collisionRoot = semantic.collisionOwner != null ? semantic.collisionOwner : collision != null && collision.transform.name == "Interaction" ? collision.transform.parent : collision != null ? collision.transform : semantic.transform.Find("Collision");
                if (collisionRoot == null || !collisionRoot.IsChildOf(semantic.transform)) throw new InvalidOperationException("Actual Collision owner missing/outside entity for " + semantic.stableId);
                var worldAnchor = semantic.InteractionWorldAnchor;
                var protectedComponents = new List<string> { typeof(GreyboxEntity).FullName };
                protectedComponents.AddRange(logic.GetComponents<MonoBehaviour>().Where(component => component != null).Select(component => component.GetType().FullName));
                protectedComponents.AddRange(collisionRoot.GetComponentsInChildren<Collider>(true).Select(component => component.GetType().FullName).Distinct());
                rows.Add(new EntityRecord { id = semantic.stableId, role = semantic.semanticRole, behavior = semantic.behavior, node_path = NodePath(semantic.transform), logic_path = NodePath(logic), collision_path = NodePath(collisionRoot), visual_path = NodePath(semantic.visual), collision_shape = collision is BoxCollider ? "axis-aligned-box-envelope" : collision != null ? collision.GetType().FullName : "none", solid_collision = collisionRoot.GetComponentsInChildren<Collider>(true).Any(component => component.enabled && !component.isTrigger), collision_enabled = collision != null && collision.enabled, anchor = new AnchorRecord { local = V(semantic.transform.InverseTransformPoint(worldAnchor)), world = V(worldAnchor) }, collision_bounds = new BoundsRecord { center = collision != null ? V(collision.bounds.center) : V(semantic.transform.position), size = collision != null ? V(collision.bounds.size) : new[] { 0f, 0f, 0f } }, protected_components = protectedComponents.Distinct().ToArray(), tags = semantic.tags ?? Array.Empty<string>() });
            }
            if (rows.Count == 0) throw new InvalidOperationException("Opened scene has no actual semantic entities");
            return rows;
        }
        static void PlayState(PlayModeStateChange state)
        {
            if (state != PlayModeStateChange.EnteredPlayMode) return;
            string path = SessionState.GetString(PendingKey, "");
            if (String.IsNullOrEmpty(path)) return;
            try
            {
                request = JsonUtility.FromJson<Request>(File.ReadAllText(path)); report = NewReport(); report.play_mode = EditorApplication.isPlaying;
                var bindings = JsonUtility.FromJson<Report>(File.ReadAllText(Path.Combine(request.evidence_root, "scene-bindings.json")));
                if (bindings.request_id != request.request_id || bindings.scene != request.scene) throw new InvalidOperationException("Pre-play semantic receipt identity mismatch");
                report.entities = bindings.entities;
                controller = UnityEngine.Object.FindFirstObjectByType<GreyboxController>();
                if (controller == null) throw new InvalidOperationException("GreyboxController missing from declared scene");
                controller.ConfigureReplay(request.steps);
                report.input_mode = request.steps != null && request.steps.Length > 0 ? "action_replay" : "idle_observation";
                initialFrame = lastFrame = Time.frameCount; consumedSnapshots = 0; runtimeErrors.Clear();
                Application.logMessageReceived += LogMessage; EditorApplication.update += Observe;
            }
            catch (Exception error) { Fail(error); Finish(); }
        }
        static void LogMessage(string condition, string stack, LogType type)
        {
            if (type == LogType.Error || type == LogType.Exception || type == LogType.Assert) runtimeErrors.Add(condition + "\n" + stack);
        }
        static void Capture()
        {
            var camera = controller.playerCamera;
            if (SystemInfo.graphicsDeviceType == GraphicsDeviceType.Null) throw new InvalidOperationException("Native graphics device required for greybox capture");
            var render = new RenderTexture(request.width, request.height, 24, RenderTextureFormat.ARGB32); render.Create();
            var renderRequest = new UniversalRenderPipeline.SingleCameraRequest { destination = render };
            if (!RenderPipeline.SupportsRenderRequest(camera, renderRequest)) throw new InvalidOperationException("Active pipeline does not support URP SingleCameraRequest");
            RenderPipeline.SubmitRenderRequest(camera, renderRequest);
            var previous = RenderTexture.active; RenderTexture.active = render;
            var pixels = new Texture2D(request.width, request.height, TextureFormat.RGBA32, false);
            pixels.ReadPixels(new Rect(0, 0, request.width, request.height), 0, 0); pixels.Apply(); RenderTexture.active = previous;
            string output = Path.Combine(request.evidence_root, "frame-" + report.captures.Count.ToString("D3") + ".png");
            byte[] bytes = pixels.EncodeToPNG(); File.WriteAllBytes(output, bytes);
            string hash; using (var sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
            report.captures.Add(new CaptureRecord { path = output, sha256 = hash, frame = Time.frameCount, fixed_ticks = controller.fixedTicks, width = request.width, height = request.height, time = Time.time });
            UnityEngine.Object.DestroyImmediate(pixels); render.Release(); UnityEngine.Object.DestroyImmediate(render);
        }
        static void Observe()
        {
            if (!EditorApplication.isPlaying || Time.frameCount == lastFrame) return;
            lastFrame = Time.frameCount;
            try
            {
                if (Time.frameCount - initialFrame < request.warmup_frames) return;
                if (controller.Snapshots.Count > consumedSnapshots)
                {
                    report.snapshots.Add(controller.Snapshots[consumedSnapshots++]); Capture(); controller.ReplayWaiting = false;
                }
                else if (controller.ReplayFinished && report.captures.Count < request.capture_frames && (Time.frameCount - initialFrame) % request.frame_stride == 0) Capture();
                if (!controller.ReplayFinished || consumedSnapshots != controller.Snapshots.Count || report.captures.Count < request.capture_frames) return;
                report.telemetry = controller.Snapshot(); report.frames_observed = Time.frameCount - initialFrame;
                report.errors = runtimeErrors.ToArray(); Save(); Finish();
            }
            catch (Exception error) { Fail(error); Finish(); }
        }
        static void Finish()
        {
            EditorApplication.update -= Observe; Application.logMessageReceived -= LogMessage;
            SessionState.EraseString(PendingKey); EditorApplication.Exit(report.ok ? 0 : 2);
        }
    }
}
