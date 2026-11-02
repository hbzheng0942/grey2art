using System;
using System.Collections.Generic;
using System.Collections;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using UnityEngine.SceneManagement;

namespace GreyboxArt.Editor
{
    [InitializeOnLoad]
    public static class GreyboxBridge
    {
        static bool buildingPlayer;
        internal static void RecordGeneratedBuildMetadata()
        {
            if(!buildingPlayer)return;
            var producer=UnityEditor.PackageManager.PackageInfo.GetAllRegisteredPackages().FirstOrDefault(p=>p.name=="com.unity.test-framework.performance"&&p.version=="3.5.0");
            if(producer==null)return;
            foreach(var name in new[]{"PerformanceTestRunInfo.json","PerformanceTestRunSettings.json"})
            {
                string path="Assets/Resources/"+name;
                if(!File.Exists(path)||(request.frozen_source_paths??Array.Empty<string>()).Contains(path))continue;
                byte[] bytes=File.ReadAllBytes(path);if(bytes.Length>65536)throw new InvalidOperationException("Build metadata exceeds bounded output contract");
                string hash;using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
                string evidence=Path.Combine(request.evidence_root,"generated-"+name);File.WriteAllBytes(evidence,bytes);
                report.generated_inputs.Add(new GeneratedBuildInput{path=path,sha256=hash,evidence=evidence,producer=producer.name,producer_version=producer.version});
            }
        }
        const string PendingKey = "GreyboxArt.PendingRequest";
        static BridgeRequest request;
        static BridgeReport report;
        static int firstFrame, lastFrame, captureCount;
        static int gameplayStep;
        static bool stepNeedsFrame;
        static double idleSince;
        static readonly List<float> frameTimes = new List<float>();
        static readonly List<string> runtimeErrors = new List<string>();
        static GreyboxBridge() { EditorApplication.playModeStateChanged += PlayState; }
        public static void Execute()
        {
            string[] args = Environment.GetCommandLineArgs(); int idx = Array.IndexOf(args, "-greyboxRequest");
            if (idx < 0 || idx+1 >= args.Length) { Debug.LogError("-greyboxRequest requires a JSON path"); EditorApplication.Exit(2); return; }
            try
            {
                request = JsonUtility.FromJson<BridgeRequest>(File.ReadAllText(args[idx+1]));
                if (request == null || String.IsNullOrEmpty(request.report) || String.IsNullOrEmpty(request.request_id)) throw new InvalidOperationException("Invalid Greybox request");
                report = NewReport();
                if (request.operation == "fixture") MakeFixture();
                else if (request.operation == "configure") { ConfigurePipeline(); Save(); }
                else if (request.operation == "import") { foreach (string path in request.import_paths ?? Array.Empty<string>()) AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceSynchronousImport); Save(); }
                else
                {
                    EditorSceneManager.OpenScene(request.scene, OpenSceneMode.Single);
                    if (request.operation == "inspect") { Inventory(); Save(); }
                    else if (request.operation == "assemble" || request.operation == "lookdev") { Assemble(); Save(); }
                    else if (request.operation == "export") Export();
                    else if (request.operation == "capture" || request.operation == "validate" || request.operation == "play")
                    {
                        Inventory(); CheckScene();
                        SessionState.SetString(PendingKey, args[idx+1]);
                        // Let startup/import/index callbacks finish before observing gameplay.
                        idleSince=EditorApplication.timeSinceStartup;EditorApplication.update+=EnterWhenIdle;return;
                    }
                    else throw new InvalidOperationException("Unsupported operation: " + request.operation);
                }
            }
            catch (Exception ex) { Fail(ex); }
            EditorApplication.Exit(report != null && report.ok ? 0 : 2);
        }
        static BridgeReport NewReport() { return new BridgeReport { request_id=request.request_id, operation=request.operation, binding_digest=request.binding_digest, scene=request.scene, version=Application.unityVersion, pipeline=GraphicsSettings.currentRenderPipeline ? GraphicsSettings.currentRenderPipeline.GetType().FullName : "Built-in", graphics_device=SystemInfo.graphicsDeviceName, graphics_api=SystemInfo.graphicsDeviceType.ToString(), coverage="Native Unity invocation; artistic/human acceptance remains separate" }; }
        static void Fail(Exception ex)
        {
            Debug.LogException(ex); if (report == null && request != null) report = NewReport();
            if (report != null) { report.errors = report.errors.Concat(new[] { ex.ToString() }).ToArray(); report.ok = false; Save(false); }
        }
        static void Save(bool deriveOk = true)
        {
            if (deriveOk) report.ok = report.errors.Length == 0 && report.checks.All(c=>c.ok);
            Directory.CreateDirectory(Path.GetDirectoryName(request.report)); File.WriteAllText(request.report, JsonUtility.ToJson(report, true)+"\n");
        }
        static string Owned(string name)
        {
            if (String.IsNullOrEmpty(request.output_root) || !request.output_root.StartsWith("Assets/", StringComparison.Ordinal) || request.output_root.Split('/').Contains("..")) throw new InvalidOperationException("Owned output must be inside Assets/");
            string path = request.output_root.TrimEnd('/') + "/" + name; Directory.CreateDirectory(Path.GetDirectoryName(path)); return path;
        }
        static T NewAsset<T>(T asset, string path) where T : UnityEngine.Object
        {
            if (File.Exists(path))
            {
                if(!request.rebuild_owned)throw new InvalidOperationException("Refusing to overwrite existing asset; select a new content-addressed output_root: " + path);
                var existing=AssetDatabase.LoadAssetAtPath<T>(path);if(existing==null)throw new InvalidOperationException("Recorded owned asset changed type: "+path);
                UnityEngine.Object.DestroyImmediate(asset);return existing;
            }
            AssetDatabase.CreateAsset(asset,path); return asset;
        }
        static string GameplayState()
        {
            return String.Join("\n", SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).Where(t=>!IsOwnedArt(t)).Select(t=>RecipeUtility.PathOf(t)+":"+t.gameObject.activeSelf+":"+t.localPosition.ToString("R")+":"+t.localRotation.ToString("R")+":"+t.localScale.ToString("R")+":"+String.Join(",",t.GetComponents<Component>().Where(c=>c != null && !(c is Renderer) && !(c is MeshFilter) && !(c is GreyboxGrass)).Select(c=>c.GetType().FullName+(c is Behaviour b? ":"+b.enabled : c is Collider col? ":"+col.enabled : "")+((c is MonoBehaviour||c is Collider)?EditorJsonUtility.ToJson(c):"")))).OrderBy(x=>x));
        }
        static bool IsOwnedArt(Transform t){for(var p=t;p!=null;p=p.parent)if(p.name.StartsWith("_GreyboxArt",StringComparison.Ordinal))return true;return false;}
        static void Assemble()
        {
            string sourceState = GameplayState(); string sourceScene = request.scene;
            var importedPaths=new HashSet<string>(StringComparer.Ordinal);
            string scenePath = Owned("play.unity");
            if (File.Exists(scenePath)&&!request.rebuild_owned) throw new InvalidOperationException("Scene variant already exists; use a new revision output_root");
            foreach (var binding in request.bindings ?? Array.Empty<BindingSpec>())
            {
                var owner = RecipeUtility.Find(binding.owner);
                if (!String.IsNullOrEmpty(binding.owner_global_id) && GlobalObjectId.TryParse(binding.owner_global_id,out var gid)) owner = (GlobalObjectId.GlobalObjectIdentifierToObjectSlow(gid) as GameObject)?.transform ?? owner;
                if (owner == null) throw new InvalidOperationException("Missing explicit gameplay owner: " + binding.owner);
                foreach (string hide in binding.hide ?? Array.Empty<string>())
                {
                    var visual = RecipeUtility.Find(hide); if (visual == null) throw new InvalidOperationException("Missing hide path: " + hide);
                    foreach (var renderer in visual.GetComponentsInChildren<Renderer>(true)) renderer.enabled = false;
                }
                if (binding.source == null) throw new InvalidOperationException("Binding requires explicit source: " + binding.id);
                GameObject instance;
                if (!String.IsNullOrEmpty(binding.source.path))
                {
                    if(importedPaths.Add(binding.source.path))AssetDatabase.ImportAsset(binding.source.path, ImportAssetOptions.ForceSynchronousImport);
                    var asset = AssetDatabase.LoadAssetAtPath<GameObject>(binding.source.path);
                    if (asset == null) throw new InvalidOperationException("Source must import as a GameObject; install pinned glTFast for glTF: " + binding.source.path);
                    instance = PrefabUtility.InstantiatePrefab(asset) as GameObject;
                    if (instance == null) instance = UnityEngine.Object.Instantiate(asset);
                    if (instance.GetComponentsInChildren<MonoBehaviour>(true).Length > 0 || instance.GetComponentsInChildren<Collider>(true).Length > 0 || instance.GetComponentsInChildren<Camera>(true).Length > 0 || instance.GetComponentsInChildren<Light>(true).Length > 0) throw new InvalidOperationException("Imported art has executable/gameplay/camera/light content; qualify a visual-only prefab before assembly: " + binding.source.path);
                }
                else
                {
                    PrimitiveType primitive;
                    switch (binding.source.primitive) { case "sphere": primitive=PrimitiveType.Sphere; break; case "cylinder": primitive=PrimitiveType.Cylinder; break; case "box": primitive=PrimitiveType.Cube; break; default: throw new InvalidOperationException("Unsupported explicit primitive"); }
                    instance = GameObject.CreatePrimitive(primitive); foreach (var collider in instance.GetComponents<Collider>()) UnityEngine.Object.DestroyImmediate(collider);
                    instance.transform.localScale = RecipeUtility.V(binding.source.size,Vector3.one);
                    if (primitive == PrimitiveType.Cylinder) instance.transform.localScale = new Vector3(instance.transform.localScale.x,instance.transform.localScale.y/2,instance.transform.localScale.z);
                    var material = NewAsset(new Material(Shader.Find("Universal Render Pipeline/Lit")),Owned(binding.id+".mat")); material.color=RecipeUtility.C(binding.source.color,Color.white); instance.GetComponent<Renderer>().sharedMaterial=material;
                }
                instance.name = "_GreyboxArt_" + binding.id; instance.transform.SetParent(owner,false);
                float units = binding.source.units=="cm"?.01f:binding.source.units=="mm"?.001f:binding.source.units=="m"?1:throw new InvalidOperationException("Units must be m/cm/mm");
                if (binding.uniform_scale <= 0 || !float.IsFinite(binding.uniform_scale)) throw new InvalidOperationException("Uniform scale must be finite positive");
                instance.transform.localScale *= binding.uniform_scale*units;
                if (binding.source.basis=="z_up") instance.transform.localRotation=Quaternion.Euler(-90,0,0);
                else if (binding.source.basis!="unity" && binding.source.basis!="gltf" && binding.source.basis!=null) throw new InvalidOperationException("Source basis must be unity/gltf/z_up");
                instance.transform.localRotation *= Quaternion.Euler(RecipeUtility.V(binding.rotation_degrees,Vector3.zero));
                if (binding.normalize != null && (binding.normalize.mode=="uniform_bounds"||binding.normalize.target_size!=null))
                {
                    if (instance.GetComponentsInChildren<SkinnedMeshRenderer>(true).Length > 0) throw new InvalidOperationException("Rigged assets require declared units/anchors; posed bounds normalization is unsupported");
                    var renderers=instance.GetComponentsInChildren<Renderer>(true); if (renderers.Length==0) throw new InvalidOperationException("No renderer for normalization"); var bounds=renderers[0].bounds; foreach(var r in renderers) bounds.Encapsulate(r.bounds);
                    float extent=Mathf.Max(bounds.size.x,Mathf.Max(bounds.size.y,bounds.size.z)); if(extent<=0) throw new InvalidOperationException("Empty source bounds");
                    float fit=binding.normalize.max_extent/extent;
                    if(binding.normalize.target_size!=null)
                    {
                        var target=binding.normalize.target_size;if(target.Length!=3||target.Any(x=>!float.IsFinite(x)||x<=0))throw new InvalidOperationException("normalize.target_size needs three finite positive dimensions");
                        fit=float.PositiveInfinity;for(int axis=0;axis<3;axis++)if(bounds.size[axis]>.000001f)fit=Mathf.Min(fit,target[axis]/bounds.size[axis]);
                    }
                    instance.transform.localScale*=fit;
                }
                if(binding.anchor_mode=="bottom_center")
                {
                    var renderers=instance.GetComponentsInChildren<Renderer>(true);if(renderers.Length==0)throw new InvalidOperationException("bottom_center needs visible renderer bounds");var bounds=renderers[0].bounds;foreach(var renderer in renderers)bounds.Encapsulate(renderer.bounds);
                    Vector3 bottom=new Vector3(bounds.center.x,bounds.min.y,bounds.center.z);instance.transform.position+=owner.TransformPoint(RecipeUtility.V(binding.anchor,Vector3.zero))-bottom;
                }
                else if(String.IsNullOrEmpty(binding.anchor_mode)||binding.anchor_mode=="source")instance.transform.localPosition = RecipeUtility.V(binding.anchor,Vector3.zero) - instance.transform.localRotation * Vector3.Scale(RecipeUtility.V(binding.source_anchor,Vector3.zero),instance.transform.localScale);
                else throw new InvalidOperationException("anchor_mode supports source/bottom_center");
                if(PrefabUtility.IsPartOfPrefabInstance(instance))
                {
                    PrefabUtility.RecordPrefabInstancePropertyModifications(instance);
                    PrefabUtility.RecordPrefabInstancePropertyModifications(instance.transform);
                }
            }
            string assembledState = GameplayState();
            // Added art descendants are excluded together with their whole subtree.
            if (sourceState != assembledState)
            {
                File.WriteAllText(Path.Combine(request.evidence_root,"gameplay-before.txt"),sourceState);
                File.WriteAllText(Path.Combine(request.evidence_root,"gameplay-after.txt"),assembledState);
                throw new InvalidOperationException("Assembly modified baseline gameplay objects/components/active state; compare gameplay-before/after evidence");
            }
            if (request.configure_pipeline) ConfigurePipeline();
            ApplyRecipes();
            NewAsset(new TextAsset(JsonUtility.ToJson(request,true)),Owned("assembly.asset"));
            File.WriteAllText(Owned("assembly.json"),JsonUtility.ToJson(request,true)+"\n");
            if (!EditorSceneManager.SaveScene(SceneManager.GetActiveScene(),scenePath,false)) throw new InvalidOperationException("Failed to save scene variant");
            AssetDatabase.SaveAssets(); AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);
            // URP import attaches AssetVersion subassets and fixes material keywords.
            // Persist those owned changes before Python hashes the artifact, rather
            // than allowing the next PlayMode invocation to change a bound .mat.
            foreach(string guid in AssetDatabase.FindAssets("t:Material",new[]{request.output_root}))
            {
                string materialPath=AssetDatabase.GUIDToAssetPath(guid);AssetDatabase.ImportAsset(materialPath,ImportAssetOptions.ForceSynchronousImport|ImportAssetOptions.ForceUpdate);
                var material=AssetDatabase.LoadAssetAtPath<Material>(materialPath);
                if(material!=null&&material.shader.name.StartsWith("Universal Render Pipeline/",StringComparison.Ordinal)){BaseShaderGUI.SetMaterialKeywords(material);EditorUtility.SetDirty(material);}
            }
            AssetDatabase.SaveAssets();
            request.scene=scenePath; report.scene=scenePath;
            EditorSceneManager.OpenScene(scenePath,OpenSceneMode.Single);
            report.checks.Add(new CheckResult("gameplay-components-preserved",true,"Renderer-only hiding; transforms, collider components, scripts and active state preserved"));
            report.checks.Add(new CheckResult("source-scene-preserved",sourceScene!=scenePath,sourceScene));
            Inventory(); CheckScene();
        }
        static void ConfigurePipeline()
        {
            if (GraphicsSettings.defaultRenderPipeline != null && !(GraphicsSettings.defaultRenderPipeline is UniversalRenderPipelineAsset)) throw new InvalidOperationException("This adapter supports URP; existing pipeline is preserved");
            if (GraphicsSettings.defaultRenderPipeline == null)
            {
                var data=NewAsset(ScriptableObject.CreateInstance<UniversalRendererData>(),Owned("URPRenderer.asset"));
                var pipeline=UniversalRenderPipelineAsset.Create(data); pipeline.supportsCameraDepthTexture=true; pipeline.supportsCameraOpaqueTexture=true; pipeline.supportsHDR=true;
                NewAsset(pipeline,Owned("URP.asset")); GraphicsSettings.defaultRenderPipeline=pipeline; QualitySettings.renderPipeline=pipeline;
                PlayerSettings.colorSpace=ColorSpace.Linear;
            }
            // Unity 6's build preprocessor requires complete defaults. Do this in
            // the explicit configure/preflight operation, before freezing inputs.
            if(GraphicsSettings.TryGetRenderPipelineSettings<URPDefaultVolumeProfileSettings>(out var settings)&&settings.volumeProfile!=null)
            {
                UnityEditor.Rendering.VolumeProfileUtils.EnsureAllOverridesForDefaultProfile(settings.volumeProfile);
                EditorUtility.SetDirty(settings.volumeProfile);
            }
            AssetDatabase.SaveAssets();
        }
        static Material Material(string shader,string filename,float[] color)
        {
            Shader s=Shader.Find(shader); if(s==null) throw new InvalidOperationException("Missing recipe shader: "+shader);
            var m=NewAsset(new Material(s),Owned(filename+".mat")); m.enableInstancing=true; if(m.HasProperty("_BaseColor"))m.SetColor("_BaseColor",RecipeUtility.C(color,Color.white)); return m;
        }
        static GameObject Surface(string name,float[] position,float[] size,Material material)
        {
            if(size==null || size.Length!=2 || size.Any(x=>!float.IsFinite(x)||x<=0))throw new InvalidOperationException("Surface size must contain two finite positive dimensions");
            var go=new GameObject("_GreyboxArt_"+name);go.transform.position=RecipeUtility.V(position,Vector3.zero);
            go.AddComponent<MeshFilter>().sharedMesh=NewAsset(RecipeUtility.Quad(size[0],size[1]),Owned(name+".mesh.asset")); go.AddComponent<MeshRenderer>().sharedMaterial=material; return go;
        }
        static Texture2D Texture(string path,bool linear=false,bool readable=false)
        {
            if(String.IsNullOrEmpty(path))return null;
            var texture=AssetDatabase.LoadAssetAtPath<Texture2D>(path); if(texture==null)throw new InvalidOperationException("Missing texture "+path);
            var importer=AssetImporter.GetAtPath(path) as TextureImporter;
            // Do not rewrite canonical texture imports: calibrated input must already be suitable.
            if(importer!=null && (importer.sRGBTexture==linear || (readable&&!importer.isReadable)))throw new InvalidOperationException("Texture import must be prequalified (color space/readability): "+path);
            return texture;
        }
        static void ApplyRecipes()
        {
            var r=request.recipes;if(r==null)return;
            if(!(GraphicsSettings.currentRenderPipeline is UniversalRenderPipelineAsset))throw new InvalidOperationException("Recipe execution requires active URP; configure_pipeline only for a new project");
            if(r.lighting!=null&&r.lighting.enabled)
            {
                var l=r.lighting;Light sun;
                if(!String.IsNullOrEmpty(l.light_path)){sun=RecipeUtility.Find(l.light_path)?.GetComponent<Light>();if(sun==null)throw new InvalidOperationException("Missing explicit recipe light: "+l.light_path);}
                else sun=new GameObject("_GreyboxArt_Lighting").AddComponent<Light>();
                sun.type=LightType.Directional;sun.intensity=l.sun_energy;sun.color=RecipeUtility.C(l.color,Color.white);sun.shadows=LightShadows.Soft;sun.transform.rotation=Quaternion.Euler(RecipeUtility.V(l.sun_rotation,new Vector3(40,-35,0)));
                RenderSettings.sun=sun;RenderSettings.ambientMode=AmbientMode.Flat;RenderSettings.ambientLight=RecipeUtility.C(l.ambient_color,Color.gray)*l.ambient_energy;RenderSettings.fog=l.fog_density>0;RenderSettings.fogMode=FogMode.Exponential;RenderSettings.fogDensity=l.fog_density;RenderSettings.fogColor=RecipeUtility.C(l.fog_color,Color.gray);
                var volumeGo=new GameObject("_GreyboxArt_Volume");var volume=volumeGo.AddComponent<Volume>();volume.isGlobal=true;volume.priority=20;var profile=NewAsset(ScriptableObject.CreateInstance<VolumeProfile>(),Owned("EnvironmentProfile.asset"));volume.sharedProfile=profile;
                if(!profile.TryGet<Bloom>(out var bloom)){bloom=profile.Add<Bloom>(true);AssetDatabase.AddObjectToAsset(bloom,profile);}bloom.intensity.Override(l.bloom);
                if(!profile.TryGet<ColorAdjustments>(out var color)){color=profile.Add<ColorAdjustments>(true);AssetDatabase.AddObjectToAsset(color,profile);}color.postExposure.Override(l.exposure);
                if(!profile.TryGet<Tonemapping>(out var tone)){tone=profile.Add<Tonemapping>(true);AssetDatabase.AddObjectToAsset(tone,profile);}tone.mode.Override(TonemappingMode.ACES);
                foreach(var camera in UnityEngine.Object.FindObjectsByType<Camera>(FindObjectsSortMode.None)){var data=camera.GetUniversalAdditionalCameraData();data.renderPostProcessing=true;data.requiresDepthOption=CameraOverrideOption.On;}
            }
            if(r.water!=null&&r.water.enabled){var w=r.water;var mat=Material("GreyboxArt/Water","Water",w.color);mat.SetColor("_DeepColor",RecipeUtility.C(w.deep_color,Color.blue));mat.SetFloat("_Speed",w.speed);mat.SetFloat("_Amplitude",w.amplitude);mat.SetFloat("_DepthDistance",w.depth_distance);mat.SetFloat("_ShoreWidth",w.shore_width);mat.SetFloat("_Roughness",w.roughness);var normal=Texture(w.normal_texture,true);if(normal)mat.SetTexture("_NormalMap",normal);var shore=Texture(w.shore_mask,true);if(shore){mat.SetTexture("_ShoreMask",shore);mat.SetFloat("_UseShoreMask",1);}Surface("Water",w.position,w.size,mat);}
            if(r.ground!=null&&r.ground.enabled){var g=r.ground;var mat=Material("GreyboxArt/Ground","Ground",g.color);mat.SetColor("_SecondaryColor",RecipeUtility.C(g.secondary_color,Color.green));mat.SetFloat("_TileScale",g.tile_scale);mat.SetFloat("_BlendScale",g.blend_scale);var texture=Texture(g.texture);if(texture)mat.SetTexture("_BaseMap",texture);var secondary=Texture(g.secondary_texture);if(secondary)mat.SetTexture("_SecondaryMap",secondary);var mask=Texture(g.blend_mask,true);if(mask){mat.SetTexture("_BlendMask",mask);mat.SetFloat("_UseMask",1);}Surface("Ground",g.position,g.size,mat);}
            if(r.grass!=null&&r.grass.enabled){var g=r.grass;var go=new GameObject("_GreyboxArt_Grass");var grass=go.AddComponent<GreyboxGrass>();grass.config=g;grass.mesh=NewAsset(RecipeUtility.GrassCard(g.width,g.height),Owned("Grass.mesh.asset"));grass.material=Material("GreyboxArt/Grass","Grass",g.color);grass.material.SetFloat("_Wind",g.wind);grass.densityMask=Texture(g.density_mask,true,true);grass.Rebuild();}
        }
        static void Inventory()
        {
            report.pipeline=GraphicsSettings.currentRenderPipeline?GraphicsSettings.currentRenderPipeline.GetType().FullName:"Built-in";
            report.dependencies=AssetDatabase.GetDependencies(SceneManager.GetActiveScene().path,true);
            report.objects.Clear();foreach(var root in SceneManager.GetActiveScene().GetRootGameObjects())foreach(var t in root.GetComponentsInChildren<Transform>(true))report.objects.Add(new ObjectRecord{path=RecipeUtility.PathOf(t),global_id=GlobalObjectId.GetGlobalObjectIdSlow(t.gameObject).ToString(),active=t.gameObject.activeSelf,components=t.GetComponents<Component>().Select(c=>c?c.GetType().FullName:"MISSING_SCRIPT").ToArray(),renderers=t.GetComponents<Renderer>().Length,colliders=t.GetComponents<Collider>().Length});
        }
        static void CheckScene()
        {
            var objects=SceneManager.GetActiveScene().GetRootGameObjects().SelectMany(r=>r.GetComponentsInChildren<Transform>(true)).ToArray();
            report.checks.Add(new CheckResult("missing-scripts",objects.All(t=>GameObjectUtility.GetMonoBehavioursWithMissingScriptCount(t.gameObject)==0)));
            var materials=objects.SelectMany(t=>t.GetComponents<Renderer>()).SelectMany(r=>r.sharedMaterials).Where(m=>m!=null).Distinct().ToArray();
            report.checks.Add(new CheckResult("shader-compilation",materials.All(m=>m.shader!=null&&!ShaderUtil.ShaderHasError(m.shader))));
            foreach(var a in request.assertions??Array.Empty<AssertionSpec>())
            {
                var t=RecipeUtility.Find(a.path);bool ok=false;
                switch(a.type){case "exists":ok=(t!=null)==a.expected;break;case "active":ok=t!=null&&t.gameObject.activeInHierarchy==a.expected;break;case "component":ok=t!=null&&t.GetComponents<Component>().Any(c=>c!=null&&(c.GetType().FullName==a.component||c.GetType().Name==a.component))==a.expected;break;case "count":ok=objects.Count(x=>x.name==a.path)==a.count;break;default:report.errors=report.errors.Concat(new[]{"Unsupported declared assertion: "+a.type}).ToArray();break;}
                report.checks.Add(new CheckResult(a.id??("assert-"+a.path),ok,a.type+":"+a.path));
            }
        }
        static void PlayState(PlayModeStateChange state)
        {
            if(state!=PlayModeStateChange.EnteredPlayMode)return;
            string path=SessionState.GetString(PendingKey,"");if(String.IsNullOrEmpty(path))return;
            try{request=JsonUtility.FromJson<BridgeRequest>(File.ReadAllText(path));report=NewReport();report.play_mode=EditorApplication.isPlaying;firstFrame=lastFrame=Time.frameCount;captureCount=gameplayStep=0;stepNeedsFrame=false;frameTimes.Clear();runtimeErrors.Clear();Application.logMessageReceived+=LogMessage;EditorApplication.update+=CaptureUpdate;}
            catch(Exception ex){Fail(ex);SessionState.EraseString(PendingKey);EditorApplication.Exit(2);}
        }
        static void EnterWhenIdle(){if(EditorApplication.isCompiling||EditorApplication.isUpdating){idleSince=EditorApplication.timeSinceStartup;return;}if(EditorApplication.timeSinceStartup-idleSince<1)return;EditorApplication.update-=EnterWhenIdle;EditorApplication.EnterPlaymode();}
        static void LogMessage(string condition,string stack,LogType type){if(type==LogType.Error||type==LogType.Exception||type==LogType.Assert)runtimeErrors.Add(condition+"\n"+stack);}
        static string Quote(string s){return "\""+s.Replace("\\","\\\\").Replace("\"","\\\"").Replace("\n","\\n").Replace("\r","\\r").Replace("\t","\\t")+"\"";}
        static string ValueJson(object value)
        {
            if(value==null)return "null";if(value is string str)return Quote(str);if(value is bool b)return b?"true":"false";
            if(value is IDictionary map){var keys=new List<string>();foreach(object key in map.Keys)keys.Add(Convert.ToString(key,CultureInfo.InvariantCulture));keys.Sort(StringComparer.Ordinal);return "{"+String.Join(",",keys.Select(k=>Quote(k)+":"+ValueJson(map[k])))+"}";}
            if(value is IEnumerable list){var values=new List<string>();foreach(object item in list)values.Add(ValueJson(item));return "["+String.Join(",",values)+"]";}
            if(value is IConvertible)return Convert.ToString(value,CultureInfo.InvariantCulture);throw new InvalidOperationException("Probe observations must contain JSON-compatible values");
        }
        static void RunGameplayStep(ValidationStep step)
        {
            var owner=RecipeUtility.Find(step.hook_path);if(owner==null)throw new InvalidOperationException("Missing gameplay hook owner: "+step.hook_path);
            object actual=null;int matches=0;
            foreach(var component in owner.GetComponents<MonoBehaviour>())
            {
                if(component==null)continue;var method=component.GetType().GetMethod(step.hook_method,System.Reflection.BindingFlags.Instance|System.Reflection.BindingFlags.Public);if(method==null)continue;
                matches++;var parameters=method.GetParameters();if(parameters.Length==1&&parameters[0].ParameterType==typeof(string))actual=method.Invoke(component,new object[]{step.raw_json});else if(parameters.Length==0)actual=method.Invoke(component,null);else throw new InvalidOperationException("Gameplay hook must accept zero args or a JSON step string");
            }
            if(matches!=1||!(actual is IDictionary values))throw new InvalidOperationException("Gameplay hook must uniquely return Dictionary<string,object>: "+step.hook_method);
            bool passed=true;foreach(var e in step.expectations??Array.Empty<Expectation>())
            {
                report.assertions++;bool ok=values.Contains(e.key);object value=ok?values[e.key]:null;
                if(ok)switch(e.kind){case "null":ok=value==null;break;case "bool":ok=value is bool b&&b==e.boolean;break;case "number":ok=value is IConvertible&&Math.Abs(Convert.ToDouble(value,CultureInfo.InvariantCulture)-e.number)<=1e-9;break;case "string":ok=value is string s&&s==e.text;break;default:ok=ValueJson(value)==e.json;break;}
                report.checks.Add(new CheckResult(step.id+":"+e.key,ok,ValueJson(value)));passed&=ok;
            }
            report.states.Add(new StateRecord{id=step.id,actual_json=ValueJson(actual),frame=Time.frameCount});
            if(passed&&(step.expectations?.Length??0)>0)report.passed_check_ids.Add(step.id);
        }
        static void CaptureUpdate()
        {
            if(!EditorApplication.isPlaying||Time.frameCount==lastFrame)return;
            lastFrame=Time.frameCount;
            try
            {
                if(SystemInfo.graphicsDeviceType==GraphicsDeviceType.Null)throw new InvalidOperationException("Real graphics device required; -nographics cannot certify capture");
                if(Time.frameCount-firstFrame<request.warmup_frames)return;
                frameTimes.Add(Time.unscaledDeltaTime*1000);
                if(!stepNeedsFrame&&(Time.frameCount-firstFrame-request.warmup_frames)%request.frame_stride!=0)return;
                if(captureCount>0&&gameplayStep<(request.validation_steps?.Length??0)&&!stepNeedsFrame){RunGameplayStep(request.validation_steps[gameplayStep++]);stepNeedsFrame=true;return;}
                stepNeedsFrame=false;
                Camera camera=String.IsNullOrEmpty(request.camera_path)?Camera.main:RecipeUtility.Find(request.camera_path)?.GetComponent<Camera>();if(camera==null)throw new InvalidOperationException("No declared camera/Camera.main for native capture");
                var rt=new RenderTexture(request.width,request.height,24,RenderTextureFormat.ARGB32);rt.Create();
                var renderRequest=new UniversalRenderPipeline.SingleCameraRequest{destination=rt};
                if(!RenderPipeline.SupportsRenderRequest(camera,renderRequest))throw new InvalidOperationException("Current pipeline does not support URP SingleCameraRequest");
                RenderPipeline.SubmitRenderRequest(camera,renderRequest);
                var previous=RenderTexture.active;RenderTexture.active=rt;var texture=new Texture2D(request.width,request.height,TextureFormat.RGBA32,false);texture.ReadPixels(new Rect(0,0,request.width,request.height),0,0);texture.Apply();RenderTexture.active=previous;
                string output=Path.Combine(request.evidence_root,"frame-"+captureCount.ToString("D3")+".png");byte[] bytes=texture.EncodeToPNG();File.WriteAllBytes(output,bytes);string hash;using(var sha=SHA256.Create())hash=BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
                report.captures.Add(new CaptureRecord{path=output,sha256=hash,frame=Time.frameCount,time=Time.time,width=request.width,height=request.height,frame_ms=Time.unscaledDeltaTime*1000});UnityEngine.Object.DestroyImmediate(texture);rt.Release();UnityEngine.Object.DestroyImmediate(rt);
                captureCount++;if(captureCount<request.capture_frames)return;
                Inventory();CheckScene();report.frames_observed=Time.frameCount-firstFrame;report.allocated_memory=UnityEngine.Profiling.Profiler.GetTotalAllocatedMemoryLong();report.mean_frame_ms=frameTimes.Average();report.max_frame_ms=frameTimes.Max();report.errors=report.errors.Concat(runtimeErrors).ToArray();report.checks.Add(new CheckResult("actual-playmode",report.play_mode));report.checks.Add(new CheckResult("graphics-enabled-capture",report.captures.Count==request.capture_frames));
                report.gameplay_verified=report.assertions>0&&report.passed_check_ids.Count==(request.validation_steps?.Length??0)&&report.errors.Length==0&&report.checks.All(c=>c.ok);Save();FinishPlay();
            }
            catch(Exception ex){Fail(ex);FinishPlay();}
        }
        static void FinishPlay(){EditorApplication.update-=CaptureUpdate;Application.logMessageReceived-=LogMessage;SessionState.EraseString(PendingKey);EditorApplication.Exit(report.ok?0:2);}
        static void Export()
        {
            if(String.IsNullOrEmpty(request.player_output))throw new InvalidOperationException("Export requires explicit Player path");
            BuildTarget target=Application.platform==RuntimePlatform.OSXEditor?BuildTarget.StandaloneOSX:BuildTarget.StandaloneWindows64;
            if(!String.IsNullOrEmpty(request.build_target)&&!Enum.TryParse(request.build_target,out target))throw new InvalidOperationException("Invalid build target");
            if(!BuildPipeline.IsBuildTargetSupported(BuildPipeline.GetBuildTargetGroup(target),target))throw new InvalidOperationException("Requested Unity Player module is not installed: "+target);
            var scenes=request.build_scenes!=null&&request.build_scenes.Length>0?request.build_scenes:new[]{request.scene};
            if(scenes.Distinct().Count()!=scenes.Length||scenes.Any(s=>!s.StartsWith("Assets/")||!s.EndsWith(".unity",StringComparison.OrdinalIgnoreCase)||!File.Exists(s)||s.Split('/').Contains("..")))throw new InvalidOperationException("Player scenes must be unique existing Assets/*.unity files");
            report.build_scenes=scenes;
            BuildReport result;buildingPlayer=true;
            try{result=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=scenes,locationPathName=request.player_output,target=target,options=BuildOptions.None});}
            finally{buildingPlayer=false;}
            report.build_result=result.summary.result.ToString();report.build_bytes=result.summary.totalSize;
            report.build_files=result.GetFiles().Select(f=>new BuildFileRecord{path=f.path,role=f.role,bytes=f.size}).ToArray();
            report.packed_sources=result.packedAssets.SelectMany(p=>p.contents).Select(a=>new PackedSourceRecord{path=a.sourceAssetPath,type=Convert.ToString(a.type),bytes=a.packedSize}).ToArray();
            report.checks.Add(new CheckResult("native-player-build",result.summary.result==BuildResult.Succeeded));if(result.summary.result!=BuildResult.Succeeded)report.errors=new[]{"Build failed with "+result.summary.totalErrors+" errors"};Save();
        }
        static void MakeFixture()
        {
            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);ConfigurePipeline();
            var root=new GameObject("Gameplay");var floor=GameObject.CreatePrimitive(PrimitiveType.Cube);floor.name="Floor";floor.transform.SetParent(root.transform);floor.transform.position=new Vector3(0,-.5f,0);floor.transform.localScale=new Vector3(12,1,12);
            var subject=GameObject.CreatePrimitive(PrimitiveType.Cube);subject.name="Subject";subject.transform.SetParent(root.transform);subject.transform.position=new Vector3(0,.5f,0);
            var cameraGo=new GameObject("Main Camera");cameraGo.tag="MainCamera";var camera=cameraGo.AddComponent<Camera>();cameraGo.transform.position=new Vector3(8,7,-9);cameraGo.transform.LookAt(new Vector3(0,.3f,0));camera.nearClipPlane=.1f;camera.farClipPlane=200;camera.backgroundColor=new Color(.35f,.5f,.65f);camera.clearFlags=CameraClearFlags.SolidColor;camera.GetUniversalAdditionalCameraData().renderPostProcessing=true;
            request.recipes=request.recipes??new RecipeSet{lighting=new LightingRecipe()};ApplyRecipes();if(request.recipes.ground!=null)floor.GetComponent<Renderer>().enabled=false;var path=Owned("baseline.unity");EditorSceneManager.SaveScene(SceneManager.GetActiveScene(),path,false);request.scene=path;report.scene=path;AssetDatabase.SaveAssets();AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);AssetDatabase.SaveAssets();Inventory();CheckScene();Save();
        }
    }
    // The pinned Unity performance-testing package writes two transient metadata
    // Resources in its order-0 callback and removes them after packaging. Record
    // their exact bytes after preprocessors; they are generated build outputs,
    // never silent exceptions for arbitrary new game assets.
    public sealed class GreyboxGeneratedBuildRecorder : UnityEditor.Build.IPreprocessBuildWithReport
    {
        public int callbackOrder => Int32.MaxValue;
        public void OnPreprocessBuild(BuildReport report) { GreyboxBridge.RecordGeneratedBuildMetadata(); }
    }
}
