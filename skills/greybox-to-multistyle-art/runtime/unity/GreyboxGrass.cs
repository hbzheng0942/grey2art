using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace GreyboxArt
{
    [Serializable] public class SourceSpec { public string path, primitive = "box", route, units = "m", basis = "unity"; public float[] size = { 1, 1, 1 }; public float[] color; }
    [Serializable] public class NormalizeSpec { public string mode = "none", space = "world"; public float max_extent = 1; public float[] target_size; }
    [Serializable] public class BindingSpec { public string id, owner, owner_global_id, anchor_mode; public string[] hide; public SourceSpec source; public float[] anchor, source_anchor, rotation_degrees; public float uniform_scale = 1; public NormalizeSpec normalize; }
    [Serializable] public class LightingRecipe { public bool enabled = true; public string light_path; public float sun_energy = 1.5f, ambient_energy = .6f, fog_density = .005f, exposure = 0, bloom = .2f; public float[] sun_rotation = { 40, -35, 0 }; public float[] color = { 1, .94f, .82f, 1 }; public float[] ambient_color = { .48f, .58f, .7f, 1 }; public float[] fog_color = { .65f, .75f, .85f, 1 }; }
    [Serializable] public class WaterRecipe { public bool enabled = true; public float[] position = { 0, 0, 0 }, size = { 10, 10 }, color = { .05f, .4f, .5f, .85f }, deep_color = { .015f, .12f, .2f, 1 }; public float speed = .3f, amplitude = .08f, depth_distance = 3, shore_width = .3f, roughness = .2f; public string normal_texture, shore_mask; }
    [Serializable] public class ExclusionRect { public float[] bounds; }
    [Serializable] public class GrassRecipe { public bool enabled = true; public float[] bounds = { -5, -5, 5, 5 }, color = { .2f, .45f, .12f, 1 }; public int count = 1200, seed = 1; public float height = .6f, width = .15f, wind = .15f, cull_distance = 60, chunk_size = 10, ground_y = 0, mask_threshold = .1f; public string density_mask; public ExclusionRect[] exclusions; }
    [Serializable] public class GroundRecipe { public bool enabled = true; public float[] position = { 0, -.02f, 0 }, size = { 10, 10 }, color = { .35f, .4f, .2f, 1 }, secondary_color = { .16f, .25f, .08f, 1 }; public float tile_scale = 1, blend_scale = .1f; public string texture, secondary_texture, blend_mask; }
    [Serializable] public class RecipeSet { public LightingRecipe lighting; public WaterRecipe water; public GrassRecipe grass; public GroundRecipe ground; }
    [Serializable] public class AssertionSpec { public string id, type = "exists", path, component; public int count = -1; public bool expected = true; }
    [Serializable] public class Expectation { public string key, kind, json, text; public double number; public bool boolean; }
    [Serializable] public class ValidationStep { public string id, raw_json, hook_path, hook_method; public Expectation[] expectations; }
    [Serializable] public class StateRecord { public string id, actual_json; public int frame; }
    [Serializable] public class BridgeRequest
    {
        public int schema = 1; public string request_id, operation, scene, output_root, report, evidence_root, style, binding_digest;
        public BindingSpec[] bindings; public RecipeSet recipes; public AssertionSpec[] assertions; public ValidationStep[] validation_steps;
        public int width = 1280, height = 720, warmup_frames = 8, capture_frames = 3, frame_stride = 8;
        public string camera_path, player_output, build_target; public bool configure_pipeline, fixture, rebuild_owned; public string[] import_paths, build_scenes, frozen_source_paths;
    }
    [Serializable] public class CheckResult { public string id, detail; public bool ok; public CheckResult(string id, bool ok, string detail = "") { this.id = id; this.ok = ok; this.detail = detail; } }
    [Serializable] public class ObjectRecord { public string path, global_id; public bool active; public string[] components; public int renderers, colliders; }
    [Serializable] public class CaptureRecord { public string path, sha256; public int frame, width, height; public float time, frame_ms; }
    [Serializable] public class BuildFileRecord { public string path, role; public ulong bytes; }
    [Serializable] public class PackedSourceRecord { public string path, type; public ulong bytes; }
    [Serializable] public class GeneratedBuildInput { public string path, sha256, evidence, producer, producer_version; }
    [Serializable] public class BridgeReport
    {
        public int schema = 1; public bool ok; public string engine = "unity", request_id, operation, binding_digest, scene, version, pipeline, graphics_device, graphics_api, build_result;
        public string[] errors = Array.Empty<string>(), dependencies = Array.Empty<string>(); public List<CheckResult> checks = new List<CheckResult>(); public List<ObjectRecord> objects = new List<ObjectRecord>(); public List<CaptureRecord> captures = new List<CaptureRecord>();
        public bool play_mode; public int frames_observed; public long allocated_memory; public float mean_frame_ms, max_frame_ms; public string coverage;
        public bool gameplay_verified; public int assertions; public List<string> passed_check_ids = new List<string>(); public List<StateRecord> states = new List<StateRecord>();
        public string[] build_scenes = Array.Empty<string>(); public ulong build_bytes;
        public BuildFileRecord[] build_files = Array.Empty<BuildFileRecord>(); public PackedSourceRecord[] packed_sources = Array.Empty<PackedSourceRecord>();
        public List<GeneratedBuildInput> generated_inputs = new List<GeneratedBuildInput>();
    }

    public static class RecipeUtility
    {
        public static Vector3 V(float[] v, Vector3 fallback) { return v != null && v.Length == 3 ? new Vector3(v[0], v[1], v[2]) : fallback; }
        public static Color C(float[] v, Color fallback) { return v != null && v.Length >= 3 ? new Color(v[0], v[1], v[2], v.Length > 3 ? v[3] : 1) : fallback; }
        public static Transform Find(string path)
        {
            if (String.IsNullOrEmpty(path)) return null;
            Transform result = null;
            foreach (var root in UnityEngine.SceneManagement.SceneManager.GetActiveScene().GetRootGameObjects())
            {
                Transform candidate = root.name == path ? root.transform : path.StartsWith(root.name + "/", StringComparison.Ordinal) ? root.transform.Find(path.Substring(root.name.Length + 1)) : root.transform.Find(path);
                if (candidate == null) continue;
                if (result != null && result != candidate) throw new InvalidOperationException("Ambiguous scene path: " + path);
                result = candidate;
            }
            return result;
        }
        public static string PathOf(Transform t) { return t.parent ? PathOf(t.parent) + "/" + t.name : t.name; }
        public static Mesh Quad(float width, float depth)
        {
            var mesh = new Mesh { name = "GreyboxBoundedSurface" };
            mesh.vertices = new[] { new Vector3(-width/2,0,-depth/2), new Vector3(-width/2,0,depth/2), new Vector3(width/2,0,depth/2), new Vector3(width/2,0,-depth/2) };
            mesh.uv = new[] { Vector2.zero, Vector2.up, Vector2.one, Vector2.right };
            mesh.triangles = new[] { 0,1,2,0,2,3 }; mesh.RecalculateNormals(); mesh.RecalculateBounds(); return mesh;
        }
        public static Mesh GrassCard(float width, float height)
        {
            var mesh = new Mesh { name = "GreyboxGrassCard" };
            mesh.vertices = new[] { new Vector3(-width/2,0,0), new Vector3(width/2,0,0), new Vector3(width*.2f,height,0), new Vector3(-width*.2f,height,0) };
            mesh.uv = new[] { Vector2.zero, Vector2.right, Vector2.one, Vector2.up }; mesh.triangles = new[] {0,2,1,0,3,2}; mesh.RecalculateNormals(); mesh.RecalculateBounds(); return mesh;
        }
    }

    // Only this component owns grass rendering. Gameplay collision never depends on it.
    public class GreyboxGrass : MonoBehaviour
    {
        public GrassRecipe config; public Mesh mesh; public Material material; public Texture2D densityMask;
        class Chunk { public readonly List<Matrix4x4> matrices = new List<Matrix4x4>(); public readonly List<Matrix4x4[]> batches = new List<Matrix4x4[]>(); public Bounds bounds; }
        readonly List<Chunk> chunks = new List<Chunk>();
        void OnEnable() { Rebuild(); }
        public void Rebuild()
        {
            chunks.Clear(); if (config == null || mesh == null || material == null) return;
            if (config.bounds == null || config.bounds.Length != 4 || config.count < 0 || config.count > 1000000 || config.chunk_size <= 0) throw new InvalidOperationException("Invalid bounded grass recipe");
            var b = config.bounds; var random = new System.Random(config.seed); var map = new Dictionary<Vector2Int, Chunk>();
            if (b[2] <= b[0] || b[3] <= b[1]) throw new InvalidOperationException("Grass bounds must have positive area");
            for (int i = 0; i < config.count; i++)
            {
                float x = Mathf.Lerp(b[0], b[2], (float)random.NextDouble()), z = Mathf.Lerp(b[1], b[3], (float)random.NextDouble()); bool excluded = false;
                if (config.exclusions != null) foreach (var item in config.exclusions) { var e = item.bounds; if (e != null && e.Length == 4 && x >= e[0] && x <= e[2] && z >= e[1] && z <= e[3]) excluded = true; }
                if (excluded) continue;
                if (densityMask != null) { var density = densityMask.GetPixelBilinear(Mathf.InverseLerp(b[0], b[2], x), Mathf.InverseLerp(b[1], b[3], z)).grayscale; if (density < config.mask_threshold || random.NextDouble() > density) continue; }
                var key = new Vector2Int(Mathf.FloorToInt(x / config.chunk_size), Mathf.FloorToInt(z / config.chunk_size));
                if (!map.TryGetValue(key, out var chunk)) { chunk = new Chunk { bounds = new Bounds(new Vector3((key.x+.5f)*config.chunk_size, config.ground_y + config.height/2, (key.y+.5f)*config.chunk_size), new Vector3(config.chunk_size+config.wind*2,config.height+config.wind*2,config.chunk_size+config.wind*2)) }; map.Add(key, chunk); chunks.Add(chunk); }
                float scale = Mathf.Lerp(.75f,1.25f,(float)random.NextDouble());
                chunk.matrices.Add(Matrix4x4.TRS(new Vector3(x, config.ground_y, z), Quaternion.Euler(0,(float)random.NextDouble()*360,0), Vector3.one*scale));
            }
            foreach(var chunk in chunks)for(int first=0;first<chunk.matrices.Count;first+=1023){int count=Math.Min(1023,chunk.matrices.Count-first);var batch=new Matrix4x4[count];chunk.matrices.CopyTo(first,batch,0,count);chunk.batches.Add(batch);}
        }
        void LateUpdate()
        {
            if (config == null || material == null || mesh == null) return;
            var camera = Camera.main; if (camera == null) camera = Camera.current; if (camera == null) return;
            var planes = GeometryUtility.CalculateFrustumPlanes(camera);
            foreach (var chunk in chunks)
            {
                if (Vector3.Distance(camera.transform.position, chunk.bounds.ClosestPoint(camera.transform.position)) > config.cull_distance || !GeometryUtility.TestPlanesAABB(planes, chunk.bounds)) continue;
                foreach(var batch in chunk.batches) Graphics.DrawMeshInstanced(mesh, 0, material, batch, batch.Length, null, ShadowCastingMode.Off, true, gameObject.layer);
            }
        }
    }
}
